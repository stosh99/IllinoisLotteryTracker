"""Read-only game-detail projection for the current published cutoff."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection, RowMapping

ConfidenceLabel = Literal["lumpy", "low", "moderate", "high"]
AdjustmentStatus = Literal["applied", "reported_only", "reference_unavailable"]
TierStatus = Literal["available", "depleted", "unavailable"]
MetricStatus = Literal["complete", "partial", "unavailable", "not_applicable"]
OutcomeKey = Literal[
    "money_back_exact",
    "profit_ex_top",
    "moderate_5x",
    "moderate_10x",
    "jackpot_top_odds",
]


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class _ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        allow_inf_nan=False,
        populate_by_name=True,
    )


class GamePrizeTierResponse(_ApiModel):
    prize_amount: float
    is_top_prize: bool
    original_count: int
    claimed_count: int
    reported_remaining_count: int
    estimated_pending_count: float
    estimated_remaining_count: float
    adjustment_status: AdjustmentStatus
    lag_days_used: int | None
    launch_one_in: float | None
    current_one_in: float | None
    confidence_label: ConfidenceLabel | None
    status: TierStatus


class GameOutcomeResponse(_ApiModel):
    outcome_key: OutcomeKey
    probability: float | None
    one_in: float | None
    metric_status: MetricStatus


class GameDetailResponse(_ApiModel):
    generated_at: datetime
    source_observed_at: datetime
    catalog_observed_at: datetime
    analytics_run_id: int
    model_version: str
    game_id: int
    game_number: str
    game_name: str
    ticket_price: float
    launch_date: date | None
    weeks_in_market: int | None
    published_overall_odds_one_in: float | None
    estimated_original_tickets: float | None
    estimated_sold_tickets: float | None
    estimated_remaining_tickets: float | None
    estimated_ev_full: float | None
    estimated_ev_ex_top: float | None
    top_prize_amount: float | None
    top_prizes_original: int | None
    top_prizes_remaining: int | None
    outcomes: list[GameOutcomeResponse]
    tiers: list[GamePrizeTierResponse]


class GameDetailReadError(RuntimeError):
    """The canonical views could not produce a safe game-detail response."""


class GameDetailUnavailableError(GameDetailReadError):
    """Current publication gates do not permit a game-detail response."""


STATUS_QUERY = text(
    """
    SELECT
      source_observed_at,
      catalog_observed_at,
      semantic_version,
      analytics_run_id,
      available,
      reason_code
    FROM current_strategy_ranking_status_v
    """
)

GAME_QUERY = text(
    """
    SELECT
      game.id AS game_id,
      game.game_number,
      game.name AS game_name,
      strategy.ticket_price,
      game.launch_date,
      snapshot.weeks_in_market,
      metrics.published_overall_odds_one_in,
      metrics.estimated_original_tickets,
      metrics.estimated_sold_tickets,
      metrics.estimated_remaining_tickets,
      strategy.estimated_ev_full,
      strategy.estimated_ev_ex_top,
      strategy.top_prize_amount,
      strategy.top_prizes_original_reported AS top_prizes_original,
      strategy.top_prizes_remaining_reported AS top_prizes_remaining,
      strategy.p_break_even_exact,
      strategy.one_in_break_even_exact,
      strategy.p_strict_profit_ex_top,
      strategy.one_in_strict_profit_ex_top,
      strategy.p_5x_or_better_ex_top,
      strategy.one_in_5x_or_better_ex_top,
      strategy.p_10x_or_better_ex_top,
      strategy.one_in_10x_or_better_ex_top,
      strategy.p_top_prize_estimated,
      strategy.one_in_top_prize_estimated,
      strategy.metric_statuses
    FROM recommendation_current_games_v game
    JOIN current_game_snapshots_v snapshot
      ON snapshot.game_id = game.id
    JOIN current_game_metrics_v metrics
      ON metrics.game_id = game.id
     AND metrics.game_snapshot_id = snapshot.id
    JOIN current_strategy_metrics_v strategy
      ON strategy.game_id = game.id
     AND strategy.analytics_run_id = metrics.analytics_run_id
    WHERE game.id = :game_id
    """
)

TIERS_QUERY = text(
    """
    SELECT
      source.prize_amount,
      source.original_count,
      source.claimed_count,
      metric.is_top_prize,
      metric.reported_remaining_count,
      metric.estimated_pending_count,
      metric.adjusted_remaining_count AS estimated_remaining_count,
      metric.adjustment_status,
      metric.lag_days_used,
      metric.launch_one_in,
      metric.current_one_in,
      metric.confidence_label,
      metric.status
    FROM current_tier_metrics_v metric
    JOIN prize_tier_snapshots source
      ON source.id = metric.prize_tier_snapshot_id
    WHERE metric.analytics_run_id = :analytics_run_id
      AND metric.game_id = :game_id
    ORDER BY source.prize_amount DESC
    """
)


def read_current_game_detail(
    engine: Engine,
    game_id: int,
    *,
    generated_at: datetime | None = None,
) -> GameDetailResponse | None:
    """Read one game and all current prize tiers in one database snapshot."""
    options = {
        "isolation_level": "REPEATABLE READ",
        "postgresql_readonly": True,
    }
    with engine.connect().execution_options(**options) as connection:
        with connection.begin():
            return read_current_game_detail_from_connection(
                connection,
                game_id,
                generated_at=generated_at,
            )


def read_current_game_detail_from_connection(
    connection: Connection,
    game_id: int,
    *,
    generated_at: datetime | None = None,
) -> GameDetailResponse | None:
    """Build one detail response from an existing read-only transaction."""
    if game_id <= 0:
        return None
    try:
        status = connection.execute(STATUS_QUERY).mappings().one()
        if not status["available"]:
            raise GameDetailUnavailableError(
                f"Current game details are unavailable: {status['reason_code']}"
            )
        required_status = (
            status["source_observed_at"],
            status["catalog_observed_at"],
            status["semantic_version"],
            status["analytics_run_id"],
        )
        if any(value is None for value in required_status):
            raise GameDetailReadError("Available status is missing publication evidence")

        game = connection.execute(GAME_QUERY, {"game_id": game_id}).mappings().one_or_none()
        if game is None:
            return None

        tier_rows = connection.execute(
            TIERS_QUERY,
            {"analytics_run_id": status["analytics_run_id"], "game_id": game_id},
        ).mappings()
        tiers = [_tier_response(row) for row in tier_rows]
        if not tiers:
            raise GameDetailReadError("Published game detail has no prize tiers")

        generated_at = generated_at or datetime.now(UTC)
        if generated_at.tzinfo is None:
            raise GameDetailReadError("generated_at must include a timezone")
        return GameDetailResponse(
            generated_at=generated_at,
            source_observed_at=status["source_observed_at"],
            catalog_observed_at=status["catalog_observed_at"],
            analytics_run_id=status["analytics_run_id"],
            model_version=status["semantic_version"],
            game_id=game["game_id"],
            game_number=game["game_number"],
            game_name=game["game_name"],
            ticket_price=float(game["ticket_price"]),
            launch_date=game["launch_date"],
            weeks_in_market=game["weeks_in_market"],
            published_overall_odds_one_in=_optional_float(
                game["published_overall_odds_one_in"]
            ),
            estimated_original_tickets=_optional_float(
                game["estimated_original_tickets"]
            ),
            estimated_sold_tickets=_optional_float(game["estimated_sold_tickets"]),
            estimated_remaining_tickets=_optional_float(
                game["estimated_remaining_tickets"]
            ),
            estimated_ev_full=_optional_float(game["estimated_ev_full"]),
            estimated_ev_ex_top=_optional_float(game["estimated_ev_ex_top"]),
            top_prize_amount=_optional_float(game["top_prize_amount"]),
            top_prizes_original=game["top_prizes_original"],
            top_prizes_remaining=game["top_prizes_remaining"],
            outcomes=_outcome_responses(game),
            tiers=tiers,
        )
    except GameDetailReadError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise GameDetailReadError("Game-detail views returned invalid data") from exc


def _tier_response(row: RowMapping) -> GamePrizeTierResponse:
    original_count = row["original_count"]
    claimed_count = row["claimed_count"]
    reported_remaining = row["reported_remaining_count"]
    estimated_pending = float(row["estimated_pending_count"])
    estimated_remaining = float(row["estimated_remaining_count"])
    if claimed_count != original_count - reported_remaining:
        raise GameDetailReadError("Prize-tier claimed-count identity failed")
    if not 0 <= estimated_pending <= reported_remaining:
        raise GameDetailReadError("Prize-tier pending estimate is outside official counts")
    if not 0 <= estimated_remaining <= reported_remaining:
        raise GameDetailReadError("Prize-tier remaining estimate is outside official counts")
    return GamePrizeTierResponse(
        prize_amount=float(row["prize_amount"]),
        is_top_prize=row["is_top_prize"],
        original_count=original_count,
        claimed_count=claimed_count,
        reported_remaining_count=reported_remaining,
        estimated_pending_count=estimated_pending,
        estimated_remaining_count=estimated_remaining,
        adjustment_status=row["adjustment_status"],
        lag_days_used=row["lag_days_used"],
        launch_one_in=_optional_float(row["launch_one_in"]),
        current_one_in=_optional_float(row["current_one_in"]),
        confidence_label=row["confidence_label"],
        status=row["status"],
    )


_OUTCOME_FIELDS: tuple[tuple[OutcomeKey, str, str], ...] = (
    ("money_back_exact", "p_break_even_exact", "one_in_break_even_exact"),
    ("profit_ex_top", "p_strict_profit_ex_top", "one_in_strict_profit_ex_top"),
    ("moderate_5x", "p_5x_or_better_ex_top", "one_in_5x_or_better_ex_top"),
    ("moderate_10x", "p_10x_or_better_ex_top", "one_in_10x_or_better_ex_top"),
    ("jackpot_top_odds", "p_top_prize_estimated", "one_in_top_prize_estimated"),
)


def _outcome_responses(row: RowMapping) -> list[GameOutcomeResponse]:
    statuses = row["metric_statuses"]
    if not isinstance(statuses, dict):
        raise GameDetailReadError("Game outcome statuses are invalid")
    outcomes: list[GameOutcomeResponse] = []
    for outcome_key, probability_field, one_in_field in _OUTCOME_FIELDS:
        metric_status = statuses.get(outcome_key)
        outcomes.append(
            GameOutcomeResponse(
                outcome_key=outcome_key,
                probability=_optional_float(row[probability_field]),
                one_in=_optional_float(row[one_in_field]),
                metric_status=metric_status,
            )
        )
    return outcomes


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
