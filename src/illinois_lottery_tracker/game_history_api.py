"""Read-only historical series for one current published game."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection, RowMapping


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class _ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        allow_inf_nan=False,
        populate_by_name=True,
    )


class TicketSalesHistoryPoint(_ApiModel):
    observed_at: datetime
    estimated_original_tickets: float
    estimated_sold_tickets: float
    estimated_remaining_tickets: float
    segment: int


class TierClaimHistoryPoint(_ApiModel):
    observed_at: datetime
    original_count: int
    claimed_count: int
    remaining_count: int
    claimed_fraction: float | None
    segment: int


class TierClaimHistorySeries(_ApiModel):
    prize_amount: float
    points: list[TierClaimHistoryPoint]


class GameHistoryResponse(_ApiModel):
    generated_at: datetime
    source_observed_at: datetime
    model_version: str
    game_id: int
    game_number: str
    game_name: str
    sales_points: list[TicketSalesHistoryPoint]
    tier_series: list[TierClaimHistorySeries]


class GameHistoryReadError(RuntimeError):
    """Historical views could not produce a safe chart response."""


class GameHistoryUnavailableError(GameHistoryReadError):
    """Current publication gates do not permit historical chart data."""


STATUS_QUERY = text(
    """
    SELECT source_observed_at, semantic_version, available, reason_code
    FROM current_strategy_ranking_status_v
    """
)

GAME_QUERY = text(
    """
    SELECT id AS game_id, game_number, name AS game_name
    FROM recommendation_current_games_v
    WHERE id = :game_id
    """
)

SALES_QUERY = text(
    """
    WITH candidates AS (
      SELECT
        metric.source_observed_at AS observed_at,
        metric.structure_fingerprint,
        metric.estimated_original_tickets,
        metric.estimated_sold_tickets,
        metric.estimated_remaining_tickets,
        row_number() OVER (
          PARTITION BY run.as_of_scrape_run_id
          ORDER BY run.id DESC
        ) AS run_order
      FROM analytics_game_metrics metric
      JOIN analytics_runs run ON run.id = metric.analytics_run_id
      JOIN analytics_model_versions model ON model.id = run.model_version_id
      WHERE metric.game_id = :game_id
        AND run.status = 'success'
        AND model.model_name = 'core_ticket_model'
        AND model.semantic_version = :model_version
        AND metric.source_observed_at <= :source_cutoff
        AND metric.estimated_original_tickets IS NOT NULL
        AND metric.estimated_sold_tickets IS NOT NULL
        AND metric.estimated_remaining_tickets IS NOT NULL
    )
    SELECT * FROM candidates
    WHERE run_order = 1
    ORDER BY observed_at
    """
)

TIER_QUERY = text(
    """
    WITH source_runs AS (
      SELECT
        id,
        source_observed_at,
        row_number() OVER (
          PARTITION BY source_observed_at
          ORDER BY id DESC
        ) AS source_order
      FROM scrape_runs
      WHERE workflow = 'unpaid_prizes'
        AND status = 'success'
        AND is_complete
        AND source_observed_at <= :source_cutoff
    )
    SELECT
      snapshot.id AS game_snapshot_id,
      run.source_observed_at AS observed_at,
      snapshot.structure_fingerprint,
      tier.prize_amount,
      tier.original_count,
      tier.claimed_count,
      tier.remaining_count
    FROM scrape_runs run
    JOIN source_runs selected_run
      ON selected_run.id = run.id
     AND selected_run.source_order = 1
    JOIN game_snapshots snapshot ON snapshot.scrape_run_id = run.id
    JOIN prize_tier_snapshots tier ON tier.game_snapshot_id = snapshot.id
    WHERE snapshot.game_id = :game_id
    ORDER BY run.source_observed_at, run.id, tier.prize_amount DESC
    """
)


def read_current_game_history(
    engine: Engine,
    game_id: int,
    *,
    generated_at: datetime | None = None,
) -> GameHistoryResponse | None:
    """Read historical chart series within one repeatable database snapshot."""
    options = {
        "isolation_level": "REPEATABLE READ",
        "postgresql_readonly": True,
    }
    with engine.connect().execution_options(**options) as connection:
        with connection.begin():
            return read_current_game_history_from_connection(
                connection,
                game_id,
                generated_at=generated_at,
            )


def read_current_game_history_from_connection(
    connection: Connection,
    game_id: int,
    *,
    generated_at: datetime | None = None,
) -> GameHistoryResponse | None:
    """Build historical chart series from an existing read-only transaction."""
    if game_id <= 0:
        return None
    try:
        status = connection.execute(STATUS_QUERY).mappings().one()
        if not status["available"]:
            raise GameHistoryUnavailableError(
                f"Current game history is unavailable: {status['reason_code']}"
            )
        if status["source_observed_at"] is None or status["semantic_version"] is None:
            raise GameHistoryReadError("Available status is missing history evidence")
        game = connection.execute(GAME_QUERY, {"game_id": game_id}).mappings().one_or_none()
        if game is None:
            return None
        parameters = {
            "game_id": game_id,
            "source_cutoff": status["source_observed_at"],
            "model_version": status["semantic_version"],
        }
        sales_rows = connection.execute(SALES_QUERY, parameters).mappings()
        sales_points = _sales_points(sales_rows)
        tier_rows = connection.execute(TIER_QUERY, parameters).mappings()
        tier_series = _tier_series(tier_rows)
        if not tier_series:
            raise GameHistoryReadError("Published game history has no tier observations")

        generated_at = generated_at or datetime.now(UTC)
        if generated_at.tzinfo is None:
            raise GameHistoryReadError("generated_at must include a timezone")
        return GameHistoryResponse(
            generated_at=generated_at,
            source_observed_at=status["source_observed_at"],
            model_version=status["semantic_version"],
            game_id=game["game_id"],
            game_number=game["game_number"],
            game_name=game["game_name"],
            sales_points=sales_points,
            tier_series=tier_series,
        )
    except GameHistoryReadError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise GameHistoryReadError("Game-history views returned invalid data") from exc


def _sales_points(rows: Iterable[RowMapping]) -> list[TicketSalesHistoryPoint]:
    points: list[TicketSalesHistoryPoint] = []
    previous_fingerprint: object = object()
    segment = -1
    for row in rows:
        fingerprint = row["structure_fingerprint"]
        if fingerprint != previous_fingerprint:
            segment += 1
            previous_fingerprint = fingerprint
        points.append(
            TicketSalesHistoryPoint(
                observed_at=row["observed_at"],
                estimated_original_tickets=float(row["estimated_original_tickets"]),
                estimated_sold_tickets=float(row["estimated_sold_tickets"]),
                estimated_remaining_tickets=float(row["estimated_remaining_tickets"]),
                segment=segment,
            )
        )
    return points


def _tier_series(rows: Iterable[RowMapping]) -> list[TierClaimHistorySeries]:
    grouped: dict[float, list[TierClaimHistoryPoint]] = defaultdict(list)
    previous_snapshot_id: int | None = None
    previous_fingerprint: object = object()
    segment = -1
    for row in rows:
        snapshot_id = row["game_snapshot_id"]
        if snapshot_id != previous_snapshot_id:
            fingerprint = row["structure_fingerprint"]
            if fingerprint != previous_fingerprint:
                segment += 1
                previous_fingerprint = fingerprint
            previous_snapshot_id = snapshot_id
        original = row["original_count"]
        claimed = row["claimed_count"]
        remaining = row["remaining_count"]
        if claimed != original - remaining:
            raise GameHistoryReadError("Historical tier counts do not reconcile")
        claimed_fraction = None if original == 0 else float(claimed / original)
        grouped[float(row["prize_amount"])].append(
            TierClaimHistoryPoint(
                observed_at=row["observed_at"],
                original_count=original,
                claimed_count=claimed,
                remaining_count=remaining,
                claimed_fraction=claimed_fraction,
                segment=segment,
            )
        )
    return [
        TierClaimHistorySeries(prize_amount=amount, points=grouped[amount])
        for amount in sorted(grouped, reverse=True)
    ]
