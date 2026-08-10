"""Targeted, retry-aware enrichment of stable game metadata."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .catalog import (
    CatalogPageCapture,
    collect_catalog_pages,
    normalize_catalog_name,
    persist_catalog_run,
    reconcile_catalog_run_mappings,
)
from .config import Settings, get_settings
from .importer import import_instant_ticket_detail_metadata
from .instant_ticket_detail_parser import (
    ParsedInstantTicketDetail,
    parse_instant_ticket_detail_html,
)
from .models import Game, GameSnapshot, MetadataAttempt
from .raw_collector import (
    BatchPageResult,
    RawCollectionResult,
    collect_pages_batch,
    collect_raw_snapshot,
)

DETAIL_WAIT_SELECTOR = "div.itg-details-block"
RETRY_DAYS = (1, 3, 7, 30)
KNOWN_METADATA_MISSING_GAME_NUMBERS = frozenset()

CollectRawSnapshot = Callable[..., RawCollectionResult]
CollectPagesBatch = Callable[..., list[BatchPageResult]]
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class MissingMetadataGame:
    id: int
    game_number: str
    name: str
    ticket_price: Decimal | None
    source_url: str | None


@dataclass(frozen=True)
class MetadataBackfillResult:
    missing_before: int
    ignored_known_missing: tuple[str, ...]
    attempted_games: tuple[str, ...]
    detail_urls_discovered: int
    detail_pages_fetched: int
    detail_pages_failed: int
    detail_pages_parsed: int
    matching_details: int
    games_created: int
    games_updated: int
    details_skipped: int
    ambiguous_games: tuple[str, ...] = ()
    not_due_games: tuple[str, ...] = ()
    parser_warnings: tuple[str, ...] = ()
    import_issues: tuple[str, ...] = ()
    still_missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed_games(self) -> int:
        return self.games_created + self.games_updated


@dataclass(frozen=True)
class MetadataTargetPlan:
    due_games: tuple[MissingMetadataGame, ...]


@dataclass(frozen=True)
class MetadataNetworkInputs:
    catalog_pages: tuple[CatalogPageCapture, ...]
    batch_results: tuple[BatchPageResult, ...]


def _metadata_incomplete_clause():
    return (
        (Game.source_url.is_(None))
        | (Game.launch_date.is_(None))
        | (Game.overall_odds_one_in.is_(None))
        | (Game.category.is_(None))
    )


def find_missing_metadata_games(
    session: Session,
    *,
    ignored_game_numbers: set[str] | frozenset[str] = KNOWN_METADATA_MISSING_GAME_NUMBERS,
) -> list[MissingMetadataGame]:
    """Return current games whose stable detail metadata is incomplete."""
    statement = (
        select(Game.id, Game.game_number, Game.name, Game.ticket_price, Game.source_url)
        .where(
            Game.is_active.is_(True),
            exists(select(GameSnapshot.id).where(GameSnapshot.game_id == Game.id)),
            _metadata_incomplete_clause(),
        )
        .order_by(Game.game_number)
    )
    if ignored_game_numbers:
        statement = statement.where(Game.game_number.not_in(tuple(ignored_game_numbers)))
    return [MissingMetadataGame(*row) for row in session.execute(statement).all()]


def ignored_missing_metadata_game_numbers(
    session: Session,
    *,
    ignored_game_numbers: set[str] | frozenset[str] = KNOWN_METADATA_MISSING_GAME_NUMBERS,
) -> tuple[str, ...]:
    """Compatibility hook; retry state replaces the former hard-coded exception."""
    if not ignored_game_numbers:
        return ()
    return tuple(
        session.scalars(
            select(Game.game_number)
            .where(
                Game.is_active.is_(True),
                exists(select(GameSnapshot.id).where(GameSnapshot.game_id == Game.id)),
                Game.game_number.in_(tuple(ignored_game_numbers)),
                _metadata_incomplete_clause(),
            )
            .order_by(Game.game_number)
        ).all()
    )


def discover_instant_ticket_detail_urls(
    settings: Settings,
    *,
    collect_raw_snapshot_fn: CollectRawSnapshot = collect_raw_snapshot,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Compatibility helper returning URLs from one normalized catalog crawl."""
    pages = collect_catalog_pages(
        settings=settings,
        collect_raw_snapshot_fn=collect_raw_snapshot_fn,
        progress=progress,
    )
    return _unique_detail_urls(pages)


def _unique_detail_urls(pages: list[CatalogPageCapture]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for page in pages:
        for ticket in page.discovery.tickets:
            if ticket.detail_url not in seen:
                seen.add(ticket.detail_url)
                urls.append(ticket.detail_url)
    return urls


def _latest_attempts(session: Session) -> dict[int, MetadataAttempt]:
    rows = session.scalars(
        select(MetadataAttempt).order_by(
            MetadataAttempt.game_id,
            MetadataAttempt.attempted_at.desc(),
            MetadataAttempt.id.desc(),
        )
    ).all()
    latest: dict[int, MetadataAttempt] = {}
    for attempt in rows:
        latest.setdefault(attempt.game_id, attempt)
    return latest


def _is_due(attempt: MetadataAttempt | None, now: datetime, *, force: bool) -> bool:
    if force or attempt is None or attempt.next_retry_at is None:
        return force or attempt is None or attempt.outcome_code != "success"
    retry_at = attempt.next_retry_at
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return retry_at <= now


def _next_retry(attempt_number: int, now: datetime) -> datetime:
    day_index = min(attempt_number - 1, len(RETRY_DAYS) - 1)
    return now + timedelta(days=RETRY_DAYS[day_index])


def _write_attempt(
    session: Session,
    *,
    game: MissingMetadataGame,
    now: datetime,
    previous: MetadataAttempt | None,
    outcome: str,
    candidate_url: str | None = None,
    error: str | None = None,
) -> MetadataAttempt:
    attempt_number = 1 if previous is None else previous.attempt_number + 1
    attempt = MetadataAttempt(
        game_id=game.id,
        attempted_at=now,
        candidate_url=candidate_url,
        outcome_code=outcome,
        attempt_number=attempt_number,
        next_retry_at=None if outcome == "success" else _next_retry(attempt_number, now),
        error_message=error,
    )
    session.add(attempt)
    return attempt


def _candidate_map(
    pages: list[CatalogPageCapture],
) -> tuple[dict[str, object], dict[tuple[str, Decimal], list[object]]]:
    by_url: dict[str, object] = {}
    by_name_price: dict[tuple[str, Decimal], list[object]] = {}
    for page in pages:
        for card in page.discovery.tickets:
            by_url.setdefault(card.detail_url.rstrip("/"), card)
            if card.display_name and card.ticket_price is not None:
                key = (normalize_catalog_name(card.display_name), Decimal(card.ticket_price))
                candidates = by_name_price.setdefault(key, [])
                if all(item.detail_url != card.detail_url for item in candidates):
                    candidates.append(card)
    return by_url, by_name_price


def plan_metadata_targets(
    session: Session,
    *,
    ignored_game_numbers: set[str] | frozenset[str] = KNOWN_METADATA_MISSING_GAME_NUMBERS,
    now: datetime | None = None,
    force: bool = False,
    full_refresh: bool = False,
) -> MetadataTargetPlan:
    """Read and detach the due target set; no network access occurs here."""
    observed_now = (now or datetime.now(UTC)).astimezone(UTC)
    if full_refresh:
        targets = [
            MissingMetadataGame(*row)
            for row in session.execute(
                select(
                    Game.id,
                    Game.game_number,
                    Game.name,
                    Game.ticket_price,
                    Game.source_url,
                )
                .where(Game.is_active.is_(True))
                .order_by(Game.game_number)
            ).all()
        ]
    else:
        targets = find_missing_metadata_games(
            session, ignored_game_numbers=ignored_game_numbers
        )
    latest = _latest_attempts(session)
    return MetadataTargetPlan(
        due_games=tuple(
            game
            for game in targets
            if _is_due(latest.get(game.id), observed_now, force=force)
        )
    )


def collect_metadata_network_inputs(
    plan: MetadataTargetPlan,
    *,
    settings: Settings | None = None,
    max_detail_pages: int | None = None,
    collect_raw_snapshot_fn: CollectRawSnapshot = collect_raw_snapshot,
    collect_pages_batch_fn: CollectPagesBatch = collect_pages_batch,
    progress: ProgressCallback | None = None,
) -> MetadataNetworkInputs:
    """Perform all catalog/detail network work without a database session."""
    if not plan.due_games:
        return MetadataNetworkInputs(catalog_pages=(), batch_results=())
    settings = settings or get_settings()
    pages = collect_catalog_pages(
        settings=settings,
        collect_raw_snapshot_fn=collect_raw_snapshot_fn,
        progress=progress,
    )
    by_url, by_name_price = _candidate_map(pages)
    selected: list[tuple[MissingMetadataGame, str]] = []
    for game in plan.due_games:
        candidate = by_url.get(game.source_url.rstrip("/")) if game.source_url else None
        if candidate is not None:
            candidates = [candidate]
        elif game.ticket_price is not None:
            candidates = by_name_price.get(
                (normalize_catalog_name(game.name), Decimal(game.ticket_price)), []
            )
        else:
            candidates = []
        if len(candidates) == 1:
            selected.append((game, candidates[0].detail_url))
    if max_detail_pages is not None:
        selected = selected[:max_detail_pages]
    pairs = [(url, f"instant-ticket-detail-{_slug_from_url(url)}") for _, url in selected]
    if progress:
        progress(f"Fetching {len(pairs)} targeted detail pages")
    batch_results = (
        collect_pages_batch_fn(pairs, settings=settings, wait_selector=DETAIL_WAIT_SELECTOR)
        if pairs
        else []
    )
    return MetadataNetworkInputs(tuple(pages), tuple(batch_results))


def backfill_missing_game_metadata(
    session: Session,
    *,
    settings: Settings | None = None,
    ignored_game_numbers: set[str] | frozenset[str] = KNOWN_METADATA_MISSING_GAME_NUMBERS,
    max_detail_pages: int | None = None,
    collect_raw_snapshot_fn: CollectRawSnapshot = collect_raw_snapshot,
    collect_pages_batch_fn: CollectPagesBatch = collect_pages_batch,
    progress: ProgressCallback | None = None,
    now: datetime | None = None,
    force: bool = False,
    full_refresh: bool = False,
    network_inputs: MetadataNetworkInputs | None = None,
) -> MetadataBackfillResult:
    """Persist a catalog and fetch only due, uniquely matched detail candidates.

    ``full_refresh`` is the separate weekly mode.  Normal nightly calls target
    incomplete games only.  The caller owns commit/rollback.
    """
    settings = settings or get_settings()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    ignored = ignored_missing_metadata_game_numbers(
        session, ignored_game_numbers=ignored_game_numbers
    )
    missing = find_missing_metadata_games(
        session, ignored_game_numbers=ignored_game_numbers
    )
    missing_before = len(missing) + len(ignored)
    if full_refresh:
        targets = [
            MissingMetadataGame(*row)
            for row in session.execute(
                select(
                    Game.id,
                    Game.game_number,
                    Game.name,
                    Game.ticket_price,
                    Game.source_url,
                )
                .where(Game.is_active.is_(True))
                .order_by(Game.game_number)
            ).all()
        ]
    else:
        targets = missing
    if not targets:
        return _empty_result(missing_before, ignored)

    latest = _latest_attempts(session)
    due = [game for game in targets if _is_due(latest.get(game.id), now, force=force)]
    not_due = tuple(game.game_number for game in targets if game not in due)
    if not due:
        result = _empty_result(missing_before, ignored)
        return MetadataBackfillResult(**{**result.__dict__, "not_due_games": not_due,
                                         "still_missing": tuple(g.game_number for g in missing)})

    if network_inputs is None and session.bind is not None:
        if session.bind.dialect.name == "postgresql":
            raise RuntimeError(
                "PostgreSQL metadata backfill requires precollected network inputs"
            )
    pages = (
        list(network_inputs.catalog_pages)
        if network_inputs is not None
        else collect_catalog_pages(
            settings=settings,
            collect_raw_snapshot_fn=collect_raw_snapshot_fn,
            progress=progress,
        )
    )
    catalog_result = persist_catalog_run(session, pages)
    discovered_urls = _unique_detail_urls(pages)
    by_url, by_name_price = _candidate_map(pages)

    selected: list[tuple[MissingMetadataGame, str]] = []
    ambiguous: list[str] = []
    for game in due:
        candidate = by_url.get(game.source_url.rstrip("/")) if game.source_url else None
        candidates: list[object]
        if candidate is not None:
            candidates = [candidate]
        elif game.ticket_price is not None:
            candidates = by_name_price.get(
                (normalize_catalog_name(game.name), Decimal(game.ticket_price)), []
            )
        else:
            candidates = []
        if len(candidates) == 1:
            selected.append((game, candidates[0].detail_url))
        elif len(candidates) > 1:
            ambiguous.append(game.game_number)
            _write_attempt(
                session,
                game=game,
                now=now,
                previous=latest.get(game.id),
                outcome="ambiguous",
                error=f"{len(candidates)} catalog candidates matched normalized name and price",
            )
        else:
            _write_attempt(
                session,
                game=game,
                now=now,
                previous=latest.get(game.id),
                outcome="no_candidate",
                error="no catalog candidate matched normalized name and price",
            )

    if max_detail_pages is not None:
        selected = selected[:max_detail_pages]
    pairs = [(url, f"instant-ticket-detail-{_slug_from_url(url)}") for _, url in selected]
    if network_inputs is not None:
        batch_results = list(network_inputs.batch_results)
    else:
        if progress:
            progress(f"Fetching {len(pairs)} targeted detail pages")
        batch_results = (
            collect_pages_batch_fn(
                pairs, settings=settings, wait_selector=DETAIL_WAIT_SELECTOR
            )
            if pairs
            else []
        )

    parsed_details: list[ParsedInstantTicketDetail] = []
    parser_errors: list[str] = []
    parsed_count = 0
    by_result_url = {result.url: result for result in batch_results}
    for game, url in selected:
        result = by_result_url.get(url)
        if result is None or not result.success:
            _write_attempt(
                session,
                game=game,
                now=now,
                previous=latest.get(game.id),
                outcome="fetch_failed",
                candidate_url=url,
                error=result.error if result else "collector returned no result",
            )
            continue
        assert result.file_path is not None
        try:
            detail = parse_instant_ticket_detail_html(Path(result.file_path), source_url=url)
            parsed_count += 1
        except Exception as exc:  # noqa: BLE001
            parser_errors.append(f"{url}: {exc}")
            _write_attempt(
                session,
                game=game,
                now=now,
                previous=latest.get(game.id),
                outcome="parse_failed",
                candidate_url=url,
                error=str(exc),
            )
            continue
        if detail.game_number != game.game_number:
            error = f"candidate parsed as game {detail.game_number}, expected {game.game_number}"
            parser_errors.append(f"{url}: {error}")
            _write_attempt(
                session,
                game=game,
                now=now,
                previous=latest.get(game.id),
                outcome="parse_failed",
                candidate_url=url,
                error=error,
            )
            continue
        parsed_details.append(detail)
        _write_attempt(
            session,
            game=game,
            now=now,
            previous=latest.get(game.id),
            outcome="success",
            candidate_url=url,
        )

    import_result = import_instant_ticket_detail_metadata(session, parsed_details)
    session.flush()
    reconcile_catalog_run_mappings(session, catalog_result.scrape_run_id)
    still_missing = tuple(
        game.game_number
        for game in find_missing_metadata_games(
            session, ignored_game_numbers=ignored_game_numbers
        )
    )
    import_issues = tuple(
        f"game_number={issue.game_number!r} game={issue.game_name!r}: {issue.message}"
        for issue in import_result.issues
    )
    return MetadataBackfillResult(
        missing_before=missing_before,
        ignored_known_missing=ignored,
        attempted_games=tuple(game.game_number for game in due),
        detail_urls_discovered=len(discovered_urls),
        detail_pages_fetched=sum(result.success for result in batch_results),
        detail_pages_failed=sum(not result.success for result in batch_results),
        detail_pages_parsed=parsed_count,
        matching_details=len(parsed_details),
        games_created=import_result.games_created,
        games_updated=import_result.games_updated,
        details_skipped=import_result.details_skipped,
        ambiguous_games=tuple(ambiguous),
        not_due_games=not_due,
        parser_warnings=tuple(import_result.parser_warnings + parser_errors),
        import_issues=import_issues,
        still_missing=still_missing,
    )


def _empty_result(
    missing_before: int, ignored: tuple[str, ...]
) -> MetadataBackfillResult:
    return MetadataBackfillResult(
        missing_before=missing_before,
        ignored_known_missing=ignored,
        attempted_games=(),
        detail_urls_discovered=0,
        detail_pages_fetched=0,
        detail_pages_failed=0,
        detail_pages_parsed=0,
        matching_details=0,
        games_created=0,
        games_updated=0,
        details_skipped=0,
    )


def render_metadata_backfill_result(result: MetadataBackfillResult) -> str:
    lines = [
        "Metadata backfill:",
        f"  Missing before:              {result.missing_before}",
        f"  Attempted games:             {len(result.attempted_games)}",
        f"  Not due:                    {len(result.not_due_games)}",
        f"  Ambiguous:                  {len(result.ambiguous_games)}",
        f"  Detail URLs discovered:      {result.detail_urls_discovered}",
        f"  Detail pages fetched:        {result.detail_pages_fetched}",
        f"  Detail pages failed:         {result.detail_pages_failed}",
        f"  Matching details parsed:     {result.matching_details}",
        f"  Games updated:               {result.games_updated}",
        f"  Still missing:               {len(result.still_missing)}",
    ]
    return "\n".join(lines) + "\n"


def stderr_progress(message: str) -> None:
    print(message, file=sys.stderr)


def _slug_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or "unknown"
