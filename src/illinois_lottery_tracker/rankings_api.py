"""Read-only API projection for the cutoff-strict ranking views."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection, RowMapping

RankingReasonCode = Literal[
    "AVAILABLE",
    "ANALYTICS_MODEL_UNAVAILABLE",
    "SOURCE_UNAVAILABLE",
    "CATALOG_UNAVAILABLE",
    "SOURCE_STALE",
    "CATALOG_STALE",
    "ANALYTICS_UNAVAILABLE",
]
StrategyKey = Literal[
    "money_back_exact",
    "profit_ex_top",
    "value_full",
    "value_ex_top",
    "moderate_5x",
    "moderate_10x",
    "jackpot_top_odds",
    "large_1000",
    "large_100000",
]
ConfidenceLabel = Literal["lumpy", "low", "moderate", "high"]


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class _ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        allow_inf_nan=False,
        populate_by_name=True,
    )


class RankingStatusResponse(_ApiModel):
    available: bool
    reason_code: RankingReasonCode
    source_observed_at: datetime | None
    catalog_observed_at: datetime | None
    model_version: str | None
    source_run_id: int | None
    catalog_run_id: int | None
    analytics_run_id: int | None


class RankingRecordResponse(_ApiModel):
    analytics_run_id: int
    game_id: int
    game_number: str
    game_name: str
    ticket_price: float
    strategy_key: StrategyKey
    metric_value: float
    one_in_value: float | None
    launch_metric_value: float | None
    relative_to_launch: float | None
    target_tier_count: int
    target_count_coverage: float
    target_value_coverage: float
    metric_status: Literal["complete"]
    lowest_confidence: ConfidenceLabel
    contains_lumpy_tier: bool
    source_observed_at: datetime
    catalog_observed_at: datetime
    model_version: str
    rank_overall: int
    rank_within_ticket_price: int
    estimated_ev_full: float | None
    estimated_ev_ex_top: float | None
    top_prize_amount: float | None
    top_prizes_original: int | None
    top_prizes_remaining: int | None
    weeks_in_market: int | None


class RankingDatasetResponse(_ApiModel):
    generated_at: datetime
    mode: Literal["live"] = "live"
    status: RankingStatusResponse
    rankings: list[RankingRecordResponse]


class RankingReadError(RuntimeError):
    """The canonical views could not produce a self-consistent API document."""


STATUS_QUERY = text(
    """
    SELECT
      source_run_id,
      source_observed_at,
      catalog_run_id,
      catalog_observed_at,
      semantic_version,
      analytics_run_id,
      available,
      reason_code
    FROM current_strategy_ranking_status_v
    """
)

RANKINGS_QUERY = text(
    """
    SELECT
      ranking.analytics_run_id,
      ranking.game_id,
      ranking.game_number,
      game.name AS game_name,
      ranking.ticket_price,
      ranking.strategy_key,
      ranking.metric_value,
      ranking.one_in_value,
      ranking.launch_metric_value,
      ranking.relative_to_launch,
      ranking.target_tier_count,
      ranking.target_count_coverage,
      ranking.target_value_coverage,
      ranking.metric_status,
      ranking.lowest_confidence,
      ranking.contains_lumpy_tier,
      ranking.source_observed_at,
      ranking.catalog_observed_at,
      ranking.model_version,
      ranking.rank_overall,
      ranking.rank_within_ticket_price,
      metrics.estimated_ev_full,
      metrics.estimated_ev_ex_top,
      metrics.top_prize_amount,
      metrics.top_prizes_original_reported AS top_prizes_original,
      metrics.top_prizes_remaining_reported AS top_prizes_remaining,
      snapshot.weeks_in_market
    FROM current_strategy_rankings_v ranking
    JOIN games game
      ON game.id = ranking.game_id
    JOIN current_strategy_metrics_v metrics
      ON metrics.analytics_run_id = ranking.analytics_run_id
     AND metrics.game_id = ranking.game_id
    JOIN current_game_snapshots_v snapshot
      ON snapshot.game_id = ranking.game_id
    ORDER BY ranking.strategy_key, ranking.rank_overall, ranking.game_number
    """
)


def read_current_rankings(
    engine: Engine,
    *,
    generated_at: datetime | None = None,
) -> RankingDatasetResponse:
    """Read status and rows from one repeatable, read-only PostgreSQL snapshot."""
    options = {
        "isolation_level": "REPEATABLE READ",
        "postgresql_readonly": True,
    }
    with engine.connect().execution_options(**options) as connection:
        with connection.begin():
            return read_current_rankings_from_connection(
                connection,
                generated_at=generated_at,
            )


def read_current_rankings_from_connection(
    connection: Connection,
    *,
    generated_at: datetime | None = None,
) -> RankingDatasetResponse:
    """Build the response from an already-open, snapshot-consistent connection."""
    try:
        status_row = connection.execute(STATUS_QUERY).mappings().one()
        status = _status_response(status_row)
        _validate_status(status)

        rankings: list[RankingRecordResponse] = []
        if status.available:
            rows = connection.execute(RANKINGS_QUERY).mappings()
            rankings = [_ranking_response(row) for row in rows]
            for record in rankings:
                _validate_row_cutoff(record, status)

        generated_at = generated_at or datetime.now(UTC)
        if generated_at.tzinfo is None:
            raise RankingReadError("generated_at must include a timezone")
        return RankingDatasetResponse(
            generated_at=generated_at,
            status=status,
            rankings=rankings,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise RankingReadError("Ranking views returned an invalid API document") from exc


def _status_response(row: RowMapping) -> RankingStatusResponse:
    return RankingStatusResponse(
        available=row["available"],
        reason_code=row["reason_code"],
        source_observed_at=row["source_observed_at"],
        catalog_observed_at=row["catalog_observed_at"],
        model_version=row["semantic_version"],
        source_run_id=row["source_run_id"],
        catalog_run_id=row["catalog_run_id"],
        analytics_run_id=row["analytics_run_id"],
    )


def _ranking_response(row: RowMapping) -> RankingRecordResponse:
    return RankingRecordResponse(
        analytics_run_id=row["analytics_run_id"],
        game_id=row["game_id"],
        game_number=row["game_number"],
        game_name=row["game_name"],
        ticket_price=float(row["ticket_price"]),
        strategy_key=row["strategy_key"],
        metric_value=float(row["metric_value"]),
        one_in_value=_optional_float(row["one_in_value"]),
        launch_metric_value=_optional_float(row["launch_metric_value"]),
        relative_to_launch=_optional_float(row["relative_to_launch"]),
        target_tier_count=row["target_tier_count"],
        target_count_coverage=float(row["target_count_coverage"]),
        target_value_coverage=float(row["target_value_coverage"]),
        metric_status=row["metric_status"],
        lowest_confidence=row["lowest_confidence"],
        contains_lumpy_tier=row["contains_lumpy_tier"],
        source_observed_at=row["source_observed_at"],
        catalog_observed_at=row["catalog_observed_at"],
        model_version=row["model_version"],
        rank_overall=row["rank_overall"],
        rank_within_ticket_price=row["rank_within_ticket_price"],
        estimated_ev_full=_optional_float(row["estimated_ev_full"]),
        estimated_ev_ex_top=_optional_float(row["estimated_ev_ex_top"]),
        top_prize_amount=_optional_float(row["top_prize_amount"]),
        top_prizes_original=row["top_prizes_original"],
        top_prizes_remaining=row["top_prizes_remaining"],
        weeks_in_market=row["weeks_in_market"],
    )


def _validate_status(status: RankingStatusResponse) -> None:
    if status.available != (status.reason_code == "AVAILABLE"):
        raise RankingReadError("Ranking availability and reason code disagree")
    if not status.available:
        return

    evidence = (
        status.source_observed_at,
        status.catalog_observed_at,
        status.model_version,
        status.source_run_id,
        status.catalog_run_id,
        status.analytics_run_id,
    )
    if any(value is None for value in evidence):
        raise RankingReadError("Available rankings are missing publication evidence")


def _validate_row_cutoff(
    record: RankingRecordResponse,
    status: RankingStatusResponse,
) -> None:
    if (
        record.analytics_run_id != status.analytics_run_id
        or record.source_observed_at != status.source_observed_at
        or record.catalog_observed_at != status.catalog_observed_at
        or record.model_version != status.model_version
    ):
        raise RankingReadError("A ranking row does not match the published cutoff")


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
