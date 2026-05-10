"""Nightly unpaid-prizes pipeline: validate → parse → import → metrics.

This module contains the pure orchestration logic. It never fetches the network
directly — the caller supplies a raw HTML file path. Commit/rollback is also
the caller's responsibility, which makes dry-run trivial.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from .importer import import_unpaid_prizes_parse_result
from .metrics import compute_snapshot_metrics
from .models import Game, GameSnapshot, PrizeTierSnapshot, RawSourceSnapshot, ScrapeRun
from .parser import parse_html
from .raw_collector import UNPAID_PRIZES_URL

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

_CLOUDFLARE_MARKERS: tuple[bytes, ...] = (
    b"cf-browser-verification",
    b"Just a moment...",
    b"challenge-form",
    b"Attention Required! | Cloudflare",
)

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


def validate_unpaid_prizes_html(content: bytes) -> None:
    """Raise ``ValidationError`` when *content* is not a valid unpaid-prizes page.

    Checks, in order:
    1. Cloudflare challenge markers → rejected immediately.
    2. Absence of the prize table class → rejected as wrong page.
    """
    for marker in _CLOUDFLARE_MARKERS:
        if marker in content:
            raise ValidationError(
                f"Cloudflare challenge detected (marker: {marker.decode()!r})"
            )
    if _CONTENT_MARKER not in content:
        raise ValidationError(
            "unpaid-prizes table not found — captured page is not the prizes page"
        )


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineResult:
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


def run_from_file(
    session: Session,
    raw_path: Path,
    *,
    min_games: int = 20,
    fetch_method: str | None = None,
    force: bool = False,
) -> PipelineResult:
    """Validate, parse, import, and compute metrics from a saved raw HTML file.

    Raises ``ValidationError`` for bad content (Cloudflare, wrong page, too few
    games). Raises ``DuplicateImportError`` when the same file content has already
    been imported, unless ``force=True``. All DB writes are staged but not
    committed — the caller commits or rolls back.
    """
    content = raw_path.read_bytes()
    validate_unpaid_prizes_html(content)

    parse_result = parse_html(raw_path)

    if len(parse_result.games) == 0:
        raise ValidationError("parsed 0 games from the raw file — import aborted")
    if len(parse_result.games) < min_games:
        raise ValidationError(
            f"parsed only {len(parse_result.games)} games "
            f"(minimum expected: {min_games}) — import aborted"
        )

    now = datetime.now(UTC)
    content_captured_at = _parse_file_capture_time(raw_path)
    sha256 = hashlib.sha256(content).hexdigest()

    if not force:
        prior_run_id = _find_prior_import(session, sha256)
        if prior_run_id is not None:
            raise DuplicateImportError(
                f"content (sha256={sha256[:16]}...) was already imported "
                f"as scrape_run_id={prior_run_id}; use --force to override"
            )

    scrape_run = ScrapeRun(
        started_at=now,
        finished_at=now,
        status="success",
        source_url=UNPAID_PRIZES_URL,
        raw_file_path=str(raw_path),
    )
    session.add(scrape_run)
    session.flush()

    session.add(
        RawSourceSnapshot(
            scrape_run_id=scrape_run.id,
            source_url=UNPAID_PRIZES_URL,
            content_type="text/html; charset=utf-8",
            file_path=str(raw_path),
            sha256=sha256,
            captured_at=content_captured_at,
        )
    )
    session.flush()

    import_result = import_unpaid_prizes_parse_result(
        session, parse_result, scrape_run=scrape_run
    )

    metrics_result = compute_snapshot_metrics(session)

    session.flush()
    total_games = session.scalar(select(func.count()).select_from(Game))
    total_snapshots = session.scalar(select(func.count()).select_from(GameSnapshot))
    total_prize_tiers = session.scalar(select(func.count()).select_from(PrizeTierSnapshot))

    import_issues = [
        f"game_number={i.game_number!r} game={i.game_name!r}: {i.message}"
        for i in import_result.issues
    ]

    return PipelineResult(
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
