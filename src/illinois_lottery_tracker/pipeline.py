"""Nightly unpaid-prizes pipeline: validate → parse → import → metrics.

This module contains the pure orchestration logic. It never fetches the network
directly — the caller supplies a raw HTML file path. Commit/rollback is also
the caller's responsibility, which makes dry-run trivial.
"""

from __future__ import annotations

import hashlib
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, distinct, exists, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from .analytics.persistence import acquire_analytics_run, mark_analytics_run_failed
from .analytics.service import compute_analytics
from .importer import import_unpaid_prizes_parse_result
from .lifecycle import synchronize_active_games
from .metrics import compute_snapshot_metrics
from .models import Game, GameSnapshot, PrizeTierSnapshot, RawSourceSnapshot, ScrapeRun
from .parser import parse_html
from .raw_collector import UNPAID_PRIZES_URL, cloudflare_challenge_marker
from .source_quality import (
    CHICAGO_TIME_ZONE,
    assess_parse_result,
    chicago_source_date,
    evaluate_source_completeness,
)

LOCAL_TIME_ZONE = CHICAGO_TIME_ZONE
PIPELINE_VERSION = "unpaid-prizes-v2"
PARSER_VERSION = "unpaid-prizes-html-v1"
ORCHESTRATION_ADVISORY_LOCK_KEY = 4_927_604_981_102_026
_SQLITE_ORCHESTRATION_LOCK = threading.Lock()


@contextmanager
def orchestration_lock(engine: Engine):
    """Yield whether this process acquired the project-wide nightly lock.

    PostgreSQL uses a session advisory lock on an autocommit connection, so
    holding the orchestration lock during network collection never holds an
    open database transaction. SQLite uses a process-local lock for tests.
    """
    if engine.dialect.name != "postgresql":
        acquired = _SQLITE_ORCHESTRATION_LOCK.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                _SQLITE_ORCHESTRATION_LOCK.release()
        return
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = bool(
            connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": ORCHESTRATION_ADVISORY_LOCK_KEY},
            )
        )
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": ORCHESTRATION_ADVISORY_LOCK_KEY},
                )

# ---------------------------------------------------------------------------
# File capture-time extraction
# ---------------------------------------------------------------------------

_FILENAME_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def _parse_file_capture_time(raw_path: Path) -> datetime:
    """Return the timestamp when the raw HTML file was captured.

    Prefers the UTC timestamp embedded in the filename (e.g. 20260510T000519Z).
    Falls back to the file's modification time when no parseable timestamp is found.
    """
    match = _FILENAME_TS_RE.search(raw_path.name)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.fromtimestamp(raw_path.stat().st_mtime, UTC)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_CONTENT_MARKER = b"unclaimed-prizes-table__row"


class ValidationError(Exception):
    """Raised when the raw HTML fails content validation before import."""


class DuplicateImportError(ValidationError):
    """Raised when the same raw file content has already been imported.

    The check is content-based (sha256) so path variations (relative vs
    absolute, symlinks) do not affect detection. A collect-only run that
    stored a ``RawSourceSnapshot`` without any ``GameSnapshot`` is NOT
    considered a prior import and does not trigger this error.
    """


class SourceQuarantinedError(ValidationError):
    """Raised after recording a parsed source that failed completeness gates."""

    def __init__(self, scrape_run_id: int, reasons: tuple[str, ...]) -> None:
        self.scrape_run_id = scrape_run_id
        self.reasons = reasons
        super().__init__(
            f"source quarantined as scrape_run_id={scrape_run_id}: {', '.join(reasons)}"
        )


def validate_unpaid_prizes_html(content: bytes) -> None:
    """Raise ``ValidationError`` when *content* is not a valid unpaid-prizes page.

    Checks, in order:
    1. Cloudflare challenge markers → rejected immediately.
    2. Absence of the prize table class → rejected as wrong page.
    """
    marker = cloudflare_challenge_marker(content)
    if marker is not None:
        raise ValidationError(
            f"Cloudflare challenge detected (marker: {marker!r})"
        )
    if _CONTENT_MARKER not in content:
        raise ValidationError(
            "unpaid-prizes table not found — captured page is not the prizes page"
        )


def find_successful_snapshot_run_for_source_date(
    session: Session,
    *,
    source_date: date,
    min_games: int,
    tz: ZoneInfo = LOCAL_TIME_ZONE,
) -> int | None:
    """Return a scrape_run_id for a complete imported snapshot on *source_date*.

    Completion is based on database state, not logs or raw files alone:
    - scrape_run.status is ``success``
    - the run has a RawSourceSnapshot whose captured_at falls on *source_date*
      in the supplied timezone
    - the run has at least ``min_games`` game snapshots
    - the run has at least one prize-tier snapshot
    """
    provenance_run = session.scalar(
        select(ScrapeRun.id)
        .where(
            ScrapeRun.workflow == "unpaid_prizes",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
            ScrapeRun.source_date == source_date,
            ScrapeRun.parsed_game_count >= min_games,
        )
        .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
        .limit(1)
    )
    if provenance_run is not None:
        return provenance_run

    if session.bind is None or session.bind.dialect.name != "sqlite":
        return None

    # Compatibility for pre-0002 SQLite fixtures only.
    rows = session.execute(
        select(
            ScrapeRun.id,
            func.min(RawSourceSnapshot.captured_at).label("source_captured_at"),
            func.count(distinct(GameSnapshot.id)).label("game_snapshot_count"),
            func.count(PrizeTierSnapshot.id).label("prize_tier_count"),
        )
        .join(RawSourceSnapshot, RawSourceSnapshot.scrape_run_id == ScrapeRun.id)
        .outerjoin(GameSnapshot, GameSnapshot.scrape_run_id == ScrapeRun.id)
        .outerjoin(PrizeTierSnapshot, PrizeTierSnapshot.game_snapshot_id == GameSnapshot.id)
        .where(ScrapeRun.status == "success")
        .group_by(ScrapeRun.id)
    ).all()

    candidates: list[tuple[datetime, int]] = []
    for run_id, captured_at, game_count, tier_count in rows:
        captured_at = _ensure_aware(captured_at, tz=UTC)
        if captured_at.astimezone(tz).date() != source_date:
            continue
        if game_count < min_games:
            continue
        if tier_count < 1:
            continue
        candidates.append((captured_at, run_id))

    if not candidates:
        return None
    return max(candidates)[1]


def _ensure_aware(value: datetime, *, tz: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineResult:
    scrape_run_id: int
    raw_file_path: str
    raw_file_bytes: int
    fetch_method: str | None
    parsed_game_count: int
    parser_warning_count: int
    games_upserted: int
    snapshots_inserted: int
    snapshots_skipped_existing: int
    prize_tiers_inserted: int
    metrics_games_updated: int
    metrics_snapshots_computed: int
    metrics_skipped_no_odds: int
    total_games: int
    total_snapshots: int
    total_prize_tiers: int
    import_issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnalyticsStageResult:
    source_run_id: int
    analytics_run_id: int | None
    status: str
    error_message: str | None = None


def run_analytics_stage(
    session_factory: sessionmaker[Session],
    *,
    source_run_id: int,
    semantic_version: str = "2.0.0",
    compute_fn=compute_analytics,
) -> AnalyticsStageResult:
    """Compute analytics in its own transaction and persist an honest failure."""
    with session_factory(expire_on_commit=False) as session:
        try:
            result = compute_fn(
                session,
                scrape_run_id=source_run_id,
                semantic_version=semantic_version,
            )
            session.commit()
            return AnalyticsStageResult(
                source_run_id=source_run_id,
                analytics_run_id=result.analytics_run_id,
                status="success",
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            failure = acquire_analytics_run(
                session,
                as_of_scrape_run_id=source_run_id,
                semantic_version=semantic_version,
            ).run
            mark_analytics_run_failed(session, failure, error_message=str(exc))
            session.commit()
            return AnalyticsStageResult(
                source_run_id=source_run_id,
                analytics_run_id=failure.id,
                status="failed",
                error_message=str(exc),
            )


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def _find_prior_import(session: Session, sha256: str) -> int | None:
    """Return the scrape_run_id of a prior import of this content, or None.

    A "prior import" is a ``RawSourceSnapshot`` with the given sha256 whose
    parent ``ScrapeRun`` has at least one associated ``GameSnapshot``. A
    collect-only run (no game snapshots) is not considered a prior import.
    """
    return session.scalar(
        select(RawSourceSnapshot.scrape_run_id)
        .where(
            RawSourceSnapshot.sha256 == sha256,
            exists(
                select(GameSnapshot.id).where(
                    GameSnapshot.scrape_run_id == RawSourceSnapshot.scrape_run_id
                )
            ),
        )
        .limit(1)
    )


def _prior_complete_counts(
    session: Session, *, observed_before: datetime
) -> tuple[int | None, int | None]:
    row = session.execute(
        select(ScrapeRun.parsed_game_count, ScrapeRun.parsed_prize_tier_count)
        .where(
            ScrapeRun.workflow == "unpaid_prizes",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
            ScrapeRun.source_observed_at < observed_before,
        )
        .order_by(ScrapeRun.source_observed_at.desc(), ScrapeRun.id.desc())
        .limit(1)
    ).one_or_none()
    return (None, None) if row is None else (row[0], row[1])


def _new_source_run(
    *,
    raw_path: Path,
    now: datetime,
    captured_at: datetime,
    sha256: str,
    status: str,
    parsed_game_count: int,
    parsed_tier_count: int,
    manual_approval_reason: str | None,
) -> ScrapeRun:
    return ScrapeRun(
        started_at=now,
        finished_at=now,
        status=status,
        source_url=UNPAID_PRIZES_URL,
        raw_file_path=str(raw_path),
        parser_version=PARSER_VERSION,
        workflow="unpaid_prizes",
        source_observed_at=captured_at,
        source_date=chicago_source_date(captured_at),
        source_sha256=sha256,
        is_complete=False,
        parsed_game_count=parsed_game_count,
        parsed_prize_tier_count=parsed_tier_count,
        pipeline_version=PIPELINE_VERSION,
        manually_approved_at=now if manual_approval_reason else None,
        manual_approval_reason=manual_approval_reason,
    )


def _add_raw_source(
    session: Session,
    *,
    scrape_run: ScrapeRun,
    raw_path: Path,
    sha256: str,
    captured_at: datetime,
) -> None:
    session.add(
        RawSourceSnapshot(
            scrape_run=scrape_run,
            source_url=UNPAID_PRIZES_URL,
            content_type="text/html; charset=utf-8",
            file_path=str(raw_path),
            sha256=sha256,
            captured_at=captured_at,
        )
    )


def run_from_file(
    session: Session,
    raw_path: Path,
    *,
    min_games: int = 40,
    fetch_method: str | None = None,
    force: bool = False,
    manual_approval_reason: str | None = None,
) -> PipelineResult:
    """Validate, parse, import, and compute metrics from a saved raw HTML file.

    Raises ``ValidationError`` for bad content (Cloudflare, wrong page, too few
    games). Raises ``DuplicateImportError`` when the same immutable source content
    has already been imported, including with ``force=True``. All DB writes are
    staged but not committed — the caller commits or rolls back.
    """
    content = raw_path.read_bytes()
    validate_unpaid_prizes_html(content)

    now = datetime.now(UTC)
    content_captured_at = _parse_file_capture_time(raw_path)
    sha256 = hashlib.sha256(content).hexdigest()
    parse_result = parse_html(raw_path)
    quality = assess_parse_result(parse_result)

    prior_run_id = _find_prior_import(session, sha256)
    if prior_run_id is not None:
        force_note = " --force cannot duplicate an immutable complete source" if force else ""
        raise DuplicateImportError(
            f"content (sha256={sha256[:16]}...) was already imported "
            f"as scrape_run_id={prior_run_id}; import is idempotently skipped.{force_note}"
        )

    prior_game_count, prior_tier_count = _prior_complete_counts(
        session, observed_before=content_captured_at
    )
    decision = evaluate_source_completeness(
        quality,
        prior_game_count=prior_game_count,
        prior_prize_tier_count=prior_tier_count,
        minimum_games=min_games,
        manually_approved=manual_approval_reason is not None,
    )
    if not decision.is_complete:
        quarantined = _new_source_run(
            raw_path=raw_path,
            now=now,
            captured_at=content_captured_at,
            sha256=sha256,
            status="quarantined",
            parsed_game_count=quality.parsed_game_count,
            parsed_tier_count=quality.parsed_prize_tier_count,
            manual_approval_reason=manual_approval_reason,
        )
        quarantined.error_message = ",".join(decision.reasons)
        session.add(quarantined)
        _add_raw_source(
            session,
            scrape_run=quarantined,
            raw_path=raw_path,
            sha256=sha256,
            captured_at=content_captured_at,
        )
        session.flush()
        raise SourceQuarantinedError(quarantined.id, decision.reasons)

    scrape_run = _new_source_run(
        raw_path=raw_path,
        now=now,
        captured_at=content_captured_at,
        sha256=sha256,
        status="success",
        parsed_game_count=quality.parsed_game_count,
        parsed_tier_count=quality.parsed_prize_tier_count,
        manual_approval_reason=manual_approval_reason,
    )
    session.add(scrape_run)
    _add_raw_source(
        session,
        scrape_run=scrape_run,
        raw_path=raw_path,
        sha256=sha256,
        captured_at=content_captured_at,
    )
    session.flush()

    import_result = import_unpaid_prizes_parse_result(
        session,
        parse_result,
        scrape_run=scrape_run,
        captured_at=content_captured_at,
    )

    if import_result.snapshots_inserted != quality.parsed_game_count:
        raise ValidationError(
            "imported game count does not reconcile with validated parsed game count"
        )
    if import_result.prize_tiers_inserted != quality.parsed_prize_tier_count:
        raise ValidationError(
            "imported tier count does not reconcile with validated parsed tier count"
        )
    scrape_run.is_complete = True
    synchronize_active_games(session, scrape_run.id)

    metrics_result = compute_snapshot_metrics(session, include_legacy=False)

    session.flush()
    total_games = session.scalar(select(func.count()).select_from(Game))
    total_snapshots = session.scalar(select(func.count()).select_from(GameSnapshot))
    total_prize_tiers = session.scalar(select(func.count()).select_from(PrizeTierSnapshot))

    import_issues = [
        f"game_number={i.game_number!r} game={i.game_name!r}: {i.message}"
        for i in import_result.issues
    ]

    return PipelineResult(
        scrape_run_id=scrape_run.id,
        raw_file_path=str(raw_path),
        raw_file_bytes=len(content),
        fetch_method=fetch_method,
        parsed_game_count=len(parse_result.games),
        parser_warning_count=len(parse_result.warnings),
        games_upserted=import_result.games_upserted,
        snapshots_inserted=import_result.snapshots_inserted,
        snapshots_skipped_existing=import_result.snapshots_skipped_existing,
        prize_tiers_inserted=import_result.prize_tiers_inserted,
        metrics_games_updated=metrics_result.games_updated,
        metrics_snapshots_computed=metrics_result.snapshots_computed,
        metrics_skipped_no_odds=metrics_result.snapshots_skipped_no_odds,
        total_games=total_games,
        total_snapshots=total_snapshots,
        total_prize_tiers=total_prize_tiers,
        import_issues=import_issues,
    )
