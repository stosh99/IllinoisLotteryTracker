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
    "any_win",
    "profit_full",
    "value_full",
    "value_ex_top",
    "moderate_10x_full",
    "jackpot_top_odds",
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
    profit_ex_top_probability: float | None
    one_in_profit_ex_top: float | None
    ten_x_ex_top_probability: float | None
    one_in_ten_x_ex_top: float | None


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
    WITH expanded AS (
      SELECT
        metrics.analytics_run_id,
        metrics.game_id,
        game.game_number,
        game.name AS game_name,
        metrics.ticket_price,
        strategy.strategy_key,
        strategy.metric_value,
        strategy.one_in_value,
        strategy.launch_metric_value,
        CASE
          WHEN strategy.launch_metric_value IS NOT NULL
            AND strategy.launch_metric_value <> 0
          THEN strategy.metric_value / strategy.launch_metric_value
        END AS relative_to_launch,
        strategy.target_tier_count,
        strategy.target_count_coverage,
        strategy.target_value_coverage,
        'complete'::text AS metric_status,
        CASE strategy.strategy_key
          WHEN 'value_ex_top' THEN COALESCE(
            metrics.metric_details -> 'value_ex_top' ->> 'lowest_confidence',
            metrics.lowest_confidence
          )
          WHEN 'value_full' THEN COALESCE(
            metrics.metric_details -> 'value_full' ->> 'lowest_confidence',
            metrics.lowest_confidence
          )
          WHEN 'any_win' THEN COALESCE(
            metrics.metric_details -> 'value_full' ->> 'lowest_confidence',
            metrics.lowest_confidence
          )
          WHEN 'jackpot_top_odds' THEN COALESCE(
            metrics.metric_details -> 'jackpot_top_odds' ->> 'lowest_confidence',
            metrics.lowest_confidence
          )
          ELSE metrics.lowest_confidence
        END AS lowest_confidence,
        CASE strategy.strategy_key
          WHEN 'value_ex_top' THEN COALESCE(
            (metrics.metric_details -> 'value_ex_top'
              ->> 'contains_lumpy_tier')::boolean,
            metrics.contains_lumpy_tier
          )
          WHEN 'value_full' THEN COALESCE(
            (metrics.metric_details -> 'value_full'
              ->> 'contains_lumpy_tier')::boolean,
            metrics.contains_lumpy_tier
          )
          WHEN 'any_win' THEN COALESCE(
            (metrics.metric_details -> 'value_full'
              ->> 'contains_lumpy_tier')::boolean,
            metrics.contains_lumpy_tier
          )
          WHEN 'jackpot_top_odds' THEN COALESCE(
            (metrics.metric_details -> 'jackpot_top_odds'
              ->> 'contains_lumpy_tier')::boolean,
            metrics.contains_lumpy_tier
          )
          ELSE metrics.contains_lumpy_tier
        END AS contains_lumpy_tier,
        current_run.as_of_observed_at AS source_observed_at,
        catalog.source_observed_at AS catalog_observed_at,
        model.semantic_version AS model_version,
        metrics.estimated_ev_full,
        metrics.estimated_ev_ex_top,
        metrics.top_prize_amount,
        metrics.top_prizes_original_reported AS top_prizes_original,
        metrics.top_prizes_remaining_reported AS top_prizes_remaining,
        snapshot.weeks_in_market,
        metrics.p_strict_profit_ex_top AS profit_ex_top_probability,
        metrics.one_in_strict_profit_ex_top AS one_in_profit_ex_top,
        metrics.p_10x_or_better_ex_top AS ten_x_ex_top_probability,
        metrics.one_in_10x_or_better_ex_top AS one_in_ten_x_ex_top
      FROM current_strategy_metrics_v metrics
      JOIN current_analytics_run_v current_run
        ON current_run.id = metrics.analytics_run_id
      JOIN analytics_model_versions model
        ON model.id = current_run.model_version_id
      JOIN current_game_metrics_v game_metrics
        ON game_metrics.analytics_run_id = metrics.analytics_run_id
       AND game_metrics.game_id = metrics.game_id
      JOIN current_game_snapshots_v snapshot
        ON snapshot.game_id = metrics.game_id
      JOIN games game
        ON game.id = metrics.game_id
      JOIN recommendation_current_games_v recommended
        ON recommended.id = metrics.game_id
      JOIN current_complete_catalog_run_v catalog ON true
      JOIN current_strategy_ranking_status_v ranking_status
        ON ranking_status.available
      CROSS JOIN LATERAL (
        VALUES
          (
            'value_ex_top',
            metrics.estimated_payout_ratio_ex_top,
            NULL::numeric,
            (metrics.metric_details -> 'value_ex_top' ->> 'launch_metric_value')::numeric,
            (metrics.metric_details -> 'value_ex_top' ->> 'target_tier_count')::integer,
            metrics.ex_top_count_coverage,
            metrics.ex_top_value_coverage,
            metrics.metric_statuses ->> 'value_ex_top'
          ),
          (
            'value_full',
            metrics.estimated_payout_ratio_full,
            NULL::numeric,
            (metrics.metric_details -> 'value_full' ->> 'launch_metric_value')::numeric,
            (metrics.metric_details -> 'value_full' ->> 'target_tier_count')::integer,
            metrics.full_count_coverage,
            metrics.full_value_coverage,
            metrics.metric_statuses ->> 'value_full'
          ),
          (
            'any_win',
            metrics.p_any_win,
            metrics.one_in_any_win,
            CASE WHEN game_metrics.published_overall_odds_one_in > 0
              THEN 1 / game_metrics.published_overall_odds_one_in END,
            (metrics.metric_details -> 'value_full' ->> 'target_tier_count')::integer,
            metrics.full_count_coverage,
            metrics.full_value_coverage,
            metrics.metric_statuses ->> 'value_full'
          ),
          (
            'profit_full',
            metrics.p_strict_profit,
            CASE WHEN metrics.p_strict_profit > 0
              THEN 1 / metrics.p_strict_profit END,
            (metrics.metric_details -> 'profit_ex_top' ->> 'launch_metric_value')::numeric
              + (metrics.metric_details -> 'jackpot_top_odds' ->> 'launch_metric_value')::numeric,
            COALESCE(
              (metrics.metric_details -> 'profit_ex_top' ->> 'target_tier_count')::integer,
              0
            ) + 1,
            metrics.full_count_coverage,
            metrics.full_value_coverage,
            metrics.metric_statuses ->> 'value_full'
          ),
          (
            'moderate_10x_full',
            COALESCE(metrics.p_10x_or_better_ex_top, 0)
              + CASE WHEN metrics.top_prize_amount >= metrics.ticket_price * 10
                  THEN COALESCE(metrics.p_top_prize_estimated, 0)
                  ELSE 0 END,
            CASE
              WHEN COALESCE(metrics.p_10x_or_better_ex_top, 0)
                + CASE WHEN metrics.top_prize_amount >= metrics.ticket_price * 10
                    THEN COALESCE(metrics.p_top_prize_estimated, 0)
                    ELSE 0 END > 0
              THEN 1 / (
                COALESCE(metrics.p_10x_or_better_ex_top, 0)
                + CASE WHEN metrics.top_prize_amount >= metrics.ticket_price * 10
                    THEN COALESCE(metrics.p_top_prize_estimated, 0)
                    ELSE 0 END
              )
            END,
            COALESCE(
              (metrics.metric_details -> 'moderate_10x' ->> 'launch_metric_value')::numeric,
              0
            ) + CASE WHEN metrics.top_prize_amount >= metrics.ticket_price * 10
                THEN COALESCE(
                  (metrics.metric_details -> 'jackpot_top_odds'
                    ->> 'launch_metric_value')::numeric,
                  0
                ) ELSE 0 END,
            COALESCE(
              (metrics.metric_details -> 'moderate_10x' ->> 'target_tier_count')::integer,
              0
            ) + CASE WHEN metrics.top_prize_amount >= metrics.ticket_price * 10
                THEN 1 ELSE 0 END,
            metrics.full_count_coverage,
            metrics.full_value_coverage,
            metrics.metric_statuses ->> 'value_full'
          ),
          (
            'jackpot_top_odds',
            metrics.p_top_prize_estimated,
            metrics.one_in_top_prize_estimated,
            (metrics.metric_details -> 'jackpot_top_odds'
              ->> 'launch_metric_value')::numeric,
            (metrics.metric_details -> 'jackpot_top_odds'
              ->> 'target_tier_count')::integer,
            metrics.full_count_coverage,
            metrics.full_value_coverage,
            metrics.metric_statuses ->> 'jackpot_top_odds'
          )
      ) AS strategy(
        strategy_key,
        metric_value,
        one_in_value,
        launch_metric_value,
        target_tier_count,
        target_count_coverage,
        target_value_coverage,
        metric_status
      )
      WHERE strategy.metric_status = 'complete'
        AND strategy.metric_value IS NOT NULL
    ), ranked AS (
      SELECT expanded.*,
        dense_rank() OVER (
          PARTITION BY strategy_key ORDER BY metric_value DESC
        ) AS rank_overall,
        dense_rank() OVER (
          PARTITION BY strategy_key, ticket_price ORDER BY metric_value DESC
        ) AS rank_within_ticket_price
      FROM expanded
    )
    SELECT * FROM ranked
    ORDER BY strategy_key, rank_overall, game_number
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
        profit_ex_top_probability=_optional_float(row["profit_ex_top_probability"]),
        one_in_profit_ex_top=_optional_float(row["one_in_profit_ex_top"]),
        ten_x_ex_top_probability=_optional_float(row["ten_x_ex_top_probability"]),
        one_in_ten_x_ex_top=_optional_float(row["one_in_ten_x_ex_top"]),
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
