"""One-pass, cutoff-scoped lottery analytics computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics_models import (
    AnalyticsGameMetric,
    AnalyticsStrategyMetric,
    AnalyticsTierMetric,
)
from ..models import GameSnapshot
from .confidence import (
    classify_confidence,
    classify_evidence,
    information_count,
    wilson_availability_interval,
)
from .high_prize_adjustment import (
    HighPrizeAdjustment,
    adjust_high_prize_tier,
    lagged_target,
    progress_at,
)
from .persistence import (
    MODEL_NAME,
    MODEL_VERSION,
    acquire_analytics_run,
    add_quality_issue_once,
    analytics_child_counts,
    clear_retryable_run_children,
    mark_analytics_run_success,
)
from .progress import compute_game_progress, estimated_original_ticket_count
from .queries import (
    current_catalog_observed_at,
    load_current_memberships,
    load_cutoff_game_snapshots,
    load_game_progress_curve,
    resolve_source_cutoff,
)
from .strategies import aggregate_tiers
from .tiers import classify_prize_group, score_high_tier, score_regular_tier
from .types import TierInput, TierScore


@dataclass(frozen=True)
class AnalyticsComputeResult:
    analytics_run_id: int
    source_run_id: int
    source_observed_at: datetime
    game_count: int
    tier_count: int
    regular_scored_count: int
    high_tier_count: int
    high_adjusted_count: int
    high_reported_only_count: int
    issue_count: int
    reused_successful_run: bool


def compute_analytics(
    session: Session,
    *,
    scrape_run_id: int | None = None,
    source_date: date | None = None,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
    force: bool = False,
    started_at: datetime | None = None,
) -> AnalyticsComputeResult:
    """Compute regular, high-tier, and strategy metrics in a single run."""
    cutoff = resolve_source_cutoff(
        session, scrape_run_id=scrape_run_id, source_date=source_date
    )
    acquisition = acquire_analytics_run(
        session,
        as_of_scrape_run_id=cutoff.id,
        model_name=model_name,
        semantic_version=semantic_version,
        started_at=started_at,
    )
    run = acquisition.run
    if run.status == "success":
        if force:
            raise ValueError(
                "successful analytics runs are immutable; create a new model version"
            )
        return _stored_result(session, run.id, cutoff, reused=True)
    if acquisition.retrying_failed:
        clear_retryable_run_children(session, run)

    memberships = load_current_memberships(session)
    catalog_observed_at = current_catalog_observed_at(session)
    for snapshot in load_cutoff_game_snapshots(session, cutoff):
        _compute_game(
            session,
            run_id=run.id,
            cutoff=cutoff,
            snapshot=snapshot,
            memberships=memberships,
            catalog_observed_at=catalog_observed_at,
        )
    session.flush()
    game_metrics = session.scalars(
        select(AnalyticsGameMetric)
        .where(AnalyticsGameMetric.analytics_run_id == run.id)
        .order_by(AnalyticsGameMetric.game_id)
    ).all()
    for game_metric in game_metrics:
        _persist_strategy_metric(session, run.id, game_metric)
    mark_analytics_run_success(session, run)
    return _stored_result(session, run.id, cutoff, reused=False)


def _stored_result(session: Session, run_id: int, cutoff, *, reused: bool):
    counts = analytics_child_counts(session, run_id)

    def tier_count(*conditions) -> int:
        return session.scalar(
            select(func.count()).select_from(AnalyticsTierMetric).where(
                AnalyticsTierMetric.analytics_run_id == run_id, *conditions
            )
        ) or 0

    high_total = tier_count(AnalyticsTierMetric.process_group == "high")
    high_adjusted = tier_count(AnalyticsTierMetric.adjustment_status == "applied")
    return AnalyticsComputeResult(
        analytics_run_id=run_id,
        source_run_id=cutoff.id,
        source_observed_at=cutoff.source_observed_at,
        game_count=counts.games,
        tier_count=counts.tiers,
        regular_scored_count=tier_count(
            AnalyticsTierMetric.process_group == "baseline",
            AnalyticsTierMetric.current_probability.is_not(None),
        ),
        high_tier_count=high_total,
        high_adjusted_count=high_adjusted,
        high_reported_only_count=high_total - high_adjusted,
        issue_count=counts.issues,
        reused_successful_run=reused,
    )


def _compute_game(
    session: Session,
    *,
    run_id: int,
    cutoff,
    snapshot: GameSnapshot,
    memberships,
    catalog_observed_at,
) -> None:
    game = snapshot.game
    ordered = sorted(snapshot.prize_tiers, key=lambda tier: tier.prize_amount)
    top_amount = max(tier.prize_amount for tier in ordered)
    inputs = [
        TierInput(
            prize_amount=tier.prize_amount,
            original_count=tier.original_count,
            remaining_count=tier.remaining_count,
            is_top_prize=tier.prize_amount == top_amount,
        )
        for tier in ordered
    ]
    baseline = compute_game_progress(inputs)
    total_original_winners = sum(tier.original_count for tier in inputs)
    ticket_total, odds_reason = estimated_original_ticket_count(
        inputs, game.overall_odds_one_in
    )
    curve = load_game_progress_curve(session, game_id=game.id, cutoff=cutoff)
    target = lagged_target(cutoff.source_observed_at)
    game_started_at = (
        datetime.combine(
            game.launch_date,
            time.min,
            tzinfo=ZoneInfo("America/Chicago"),
        )
        if game.launch_date is not None
        else None
    )
    historical_progress = progress_at(
        curve,
        target,
        game_started_at=game_started_at,
    )

    metrics: list[AnalyticsTierMetric] = []
    for source_tier, tier_input in zip(ordered, inputs, strict=True):
        if classify_prize_group(tier_input.prize_amount) == "high":
            adjustment = adjust_high_prize_tier(
                tier_input,
                current_progress_fraction=baseline.progress_fraction,
                lagged_progress_fraction=historical_progress,
            )
            score = score_high_tier(
                tier_input,
                effective_remaining_count=adjustment.adjusted_remaining_count,
                current_baseline_remaining_fraction=baseline.remaining_fraction,
                total_original_winners=total_original_winners,
                overall_odds_one_in=game.overall_odds_one_in,
            )
            reference_at = target if adjustment.status == "applied" else None
        else:
            adjustment = adjust_high_prize_tier(
                tier_input,
                current_progress_fraction=baseline.progress_fraction,
                lagged_progress_fraction=historical_progress,
            )
            score = score_regular_tier(
                tier_input,
                baseline=baseline,
                total_original_winners=total_original_winners,
                overall_odds_one_in=game.overall_odds_one_in,
            )
            reference_at = snapshot.captured_at
        metric = _tier_metric_from_score(
            run_id=run_id,
            snapshot=snapshot,
            source_tier_id=source_tier.id,
            score=score,
            adjustment=adjustment,
            current_baseline=baseline.remaining_fraction,
            reference_observed_at=reference_at,
        )
        metrics.append(metric)
        session.add(metric)

    membership = memberships.get(game.id)
    prize_current = membership.prize_source_current if membership else True
    catalog_current = membership.catalog_current if membership else False
    recommendation_current = membership.recommendation_current if membership else False
    data_status = "complete"
    if baseline.status != "available":
        data_status = "unavailable"
        add_quality_issue_once(
            session,
            analytics_run_id=run_id,
            code=baseline.unavailable_reason or "BASELINE_NOT_AVAILABLE",
            severity="error",
            entity_type="game",
            game_id=game.id,
            game_snapshot_id=snapshot.id,
            message="Ordinary-tier game progress is unavailable.",
        )
    elif odds_reason:
        data_status = "partial"
        add_quality_issue_once(
            session,
            analytics_run_id=run_id,
            code=odds_reason,
            severity="warning",
            entity_type="game",
            game_id=game.id,
            game_snapshot_id=snapshot.id,
            message="Published overall odds are unavailable; absolute metrics are null.",
        )
    estimated_remaining = (
        ticket_total * baseline.remaining_fraction
        if ticket_total is not None and baseline.remaining_fraction is not None
        else None
    )
    estimated_sold = (
        ticket_total * baseline.progress_fraction
        if ticket_total is not None and baseline.progress_fraction is not None
        else None
    )
    game_metric = AnalyticsGameMetric(
        analytics_run_id=run_id,
        game_id=game.id,
        game_snapshot_id=snapshot.id,
        structure_fingerprint=snapshot.structure_fingerprint,
        source_observed_at=snapshot.captured_at,
        baseline_tier_count=baseline.tier_count,
        baseline_original_count=baseline.original_count,
        baseline_remaining_count=baseline.remaining_count,
        baseline_claimed_count=baseline.original_count - baseline.remaining_count,
        baseline_remaining_fraction=baseline.remaining_fraction,
        progress_fraction=baseline.progress_fraction,
        estimated_original_tickets=ticket_total,
        estimated_sold_tickets=estimated_sold,
        estimated_remaining_tickets=estimated_remaining,
        published_overall_odds_one_in=game.overall_odds_one_in,
        prize_source_current=prize_current,
        catalog_current=catalog_current,
        recommendation_current=recommendation_current,
        catalog_observed_at=catalog_observed_at,
        data_status=data_status,
    )
    source_by_id = {tier.id: tier for tier in ordered}
    _refresh_game_coverage(game_metric, metrics, source_by_id)
    session.add(game_metric)


def _tier_metric_from_score(
    *,
    run_id: int,
    snapshot: GameSnapshot,
    source_tier_id: int,
    score: TierScore,
    adjustment: HighPrizeAdjustment,
    current_baseline: Decimal | None,
    reference_observed_at: datetime | None,
) -> AnalyticsTierMetric:
    interval = (
        wilson_availability_interval(
            claimed_count=Decimal(score.original_count)
            - score.effective_remaining_count,
            original_count=score.original_count,
            reference_remaining_fraction=score.reference_remaining_fraction,
        )
        if score.reference_remaining_fraction is not None
        else None
    )
    confidence = (
        classify_confidence(score.original_count, score.reference_remaining_fraction)
        if score.reference_remaining_fraction is not None
        else None
    )
    evidence = classify_evidence(
        interval=interval,
        sensitivity_availabilities=(
            [score.availability_index] if score.availability_index is not None else []
        ),
        confidence=confidence,
    )
    return AnalyticsTierMetric(
        analytics_run_id=run_id,
        game_id=snapshot.game_id,
        game_snapshot_id=snapshot.id,
        prize_tier_snapshot_id=source_tier_id,
        is_top_prize=score.is_top_prize,
        process_group=score.prize_group,
        reference_method=(
            "current_baseline"
            if score.reference_kind == "current_full_baseline"
            else score.reference_kind
        ),
        reference_observed_at=reference_observed_at,
        adjustment_eligible=adjustment.eligible,
        adjustment_status=adjustment.status,
        lag_days_used=adjustment.lag_days_used,
        current_baseline_remaining_fraction=current_baseline,
        reference_remaining_fraction=score.reference_remaining_fraction,
        observed_survival_fraction=score.reported_survival,
        reported_remaining_count=adjustment.reported_remaining_count,
        estimated_pending_count=adjustment.estimated_pending_count,
        adjusted_remaining_count=adjustment.adjusted_remaining_count,
        availability_index=score.availability_index,
        availability_wilson_lower=interval.availability_lower if interval else None,
        availability_wilson_upper=interval.availability_upper if interval else None,
        launch_probability=score.launch_probability,
        launch_one_in=score.launch_one_in,
        current_probability=score.current_probability,
        current_one_in=score.current_one_in,
        confidence_label=confidence,
        information_count=(
            information_count(score.original_count, score.reference_remaining_fraction)
            if score.reference_remaining_fraction is not None
            else None
        ),
        evidence_classification=evidence,
        status=score.status,
        exclusion_reason=score.unavailable_reason or score.absolute_unavailable_reason,
    )


def _refresh_game_coverage(game_metric, metrics, source_by_id) -> None:
    all_count = sum(source_by_id[m.prize_tier_snapshot_id].original_count for m in metrics)
    all_value = sum(
        (
            source_by_id[m.prize_tier_snapshot_id].prize_amount
            * Decimal(source_by_id[m.prize_tier_snapshot_id].original_count)
            for m in metrics
        ),
        start=Decimal(0),
    )
    high = [m for m in metrics if m.process_group == "high"]
    valid = [m for m in metrics if m.current_probability is not None]
    valid_high = [m for m in high if m.current_probability is not None]

    def originals(rows):
        return sum(source_by_id[m.prize_tier_snapshot_id].original_count for m in rows)

    def value(rows):
        return sum(
            (
                source_by_id[m.prize_tier_snapshot_id].prize_amount
                * Decimal(source_by_id[m.prize_tier_snapshot_id].original_count)
                for m in rows
            ),
            start=Decimal(0),
        )

    high_count, high_value = originals(high), value(high)
    game_metric.full_score_count_coverage = (
        Decimal(originals(valid)) / Decimal(all_count) if all_count else None
    )
    game_metric.full_score_value_coverage = value(valid) / all_value if all_value else None
    game_metric.high_score_count_coverage = (
        Decimal(originals(valid_high)) / Decimal(high_count)
        if high_count
        else Decimal(1)
    )
    game_metric.high_score_value_coverage = (
        value(valid_high) / high_value if high_value else Decimal(1)
    )
    if not valid:
        game_metric.data_status = "unavailable"
    elif len(valid) < len(metrics) and game_metric.data_status == "complete":
        game_metric.data_status = "partial"


def _persist_strategy_metric(
    session: Session, run_id: int, game_metric: AnalyticsGameMetric
) -> None:
    snapshot = session.get(GameSnapshot, game_metric.game_snapshot_id)
    assert snapshot is not None
    _ = snapshot.game, snapshot.prize_tiers
    source_by_id = {tier.id: tier for tier in snapshot.prize_tiers}
    metrics = session.scalars(
        select(AnalyticsTierMetric).where(
            AnalyticsTierMetric.analytics_run_id == run_id,
            AnalyticsTierMetric.game_id == game_metric.game_id,
        )
    ).all()
    scores = [
        _metric_as_score(metric, source_by_id[metric.prize_tier_snapshot_id])
        for metric in metrics
    ]
    price = snapshot.game.ticket_price
    assert price is not None
    predicates = {
        "any": lambda s: True,
        "break_exact": lambda s: s.prize_amount == price,
        "break_better": lambda s: s.prize_amount >= price,
        "2x": lambda s: s.prize_amount >= price * 2,
        "profit": lambda s: s.prize_amount > price,
        "profit_ex": lambda s: s.prize_amount > price and not s.is_top_prize,
        "5x": lambda s: s.prize_amount >= price * 5 and not s.is_top_prize,
        "10x": lambda s: s.prize_amount >= price * 10 and not s.is_top_prize,
        "20x": lambda s: s.prize_amount >= price * 20 and not s.is_top_prize,
        "50x": lambda s: s.prize_amount >= price * 50 and not s.is_top_prize,
        "100_1000": lambda s: Decimal(100)
        <= s.prize_amount
        <= Decimal(1000)
        and not s.is_top_prize,
        "top": lambda s: s.is_top_prize,
        "1000": lambda s: s.prize_amount >= 1000,
        "10000": lambda s: s.prize_amount >= 10000,
        "100000": lambda s: s.prize_amount >= 100000,
        "1000000": lambda s: s.prize_amount >= 1000000,
        "ex_top": lambda s: not s.is_top_prize,
    }
    aggregates = {key: aggregate_tiers(scores, predicate) for key, predicate in predicates.items()}
    full, ex_top = aggregates["any"], aggregates["ex_top"]
    top_source = max(snapshot.prize_tiers, key=lambda tier: tier.prize_amount)
    top_metric = next(metric for metric in metrics if metric.is_top_prize)
    confidence_order = {"lumpy": 0, "low": 1, "moderate": 2, "high": 3}
    labels = [metric.confidence_label for metric in metrics if metric.confidence_label]
    lowest = min(labels, key=confidence_order.get) if labels else None
    strategy_specs = {
        "money_back_exact": ("break_exact", aggregates["break_exact"].launch_probability),
        "profit_ex_top": ("profit_ex", aggregates["profit_ex"].launch_probability),
        "value_full": ("any", _ratio(full.launch_expected_value, price)),
        "value_ex_top": ("ex_top", _ratio(ex_top.launch_expected_value, price)),
        "moderate_5x": ("5x", aggregates["5x"].launch_probability),
        "moderate_10x": ("10x", aggregates["10x"].launch_probability),
        "jackpot_top_odds": ("top", aggregates["top"].launch_probability),
        "large_1000": ("1000", aggregates["1000"].launch_probability),
        "large_100000": ("100000", aggregates["100000"].launch_probability),
    }
    statuses = {name: aggregates[key].status for name, (key, _) in strategy_specs.items()}
    details = {
        name: _strategy_metric_detail(
            aggregates[key],
            scores=scores,
            metrics=metrics,
            predicate=predicates[key],
            launch_metric_value=launch,
        )
        for name, (key, launch) in strategy_specs.items()
    }
    session.add(
        AnalyticsStrategyMetric(
            analytics_run_id=run_id,
            game_id=game_metric.game_id,
            ticket_price=price,
            p_any_win=full.current_probability,
            p_break_even_exact=aggregates["break_exact"].current_probability,
            p_break_even_or_better=aggregates["break_better"].current_probability,
            p_2x_or_better=aggregates["2x"].current_probability,
            p_strict_profit=aggregates["profit"].current_probability,
            p_strict_profit_ex_top=aggregates["profit_ex"].current_probability,
            profit_probability_vs_launch=_ratio(
                aggregates["profit_ex"].current_probability,
                aggregates["profit_ex"].launch_probability,
            ),
            p_5x_or_better_ex_top=aggregates["5x"].current_probability,
            p_10x_or_better_ex_top=aggregates["10x"].current_probability,
            p_20x_or_better_ex_top=aggregates["20x"].current_probability,
            p_50x_or_better_ex_top=aggregates["50x"].current_probability,
            p_100_to_1000_ex_top=aggregates["100_1000"].current_probability,
            p_top_prize_estimated=aggregates["top"].current_probability,
            p_1000_or_better=aggregates["1000"].current_probability,
            p_10000_or_better=aggregates["10000"].current_probability,
            p_100000_or_better=aggregates["100000"].current_probability,
            p_1000000_or_better=aggregates["1000000"].current_probability,
            one_in_any_win=full.current_one_in,
            one_in_break_even_exact=aggregates["break_exact"].current_one_in,
            one_in_strict_profit_ex_top=aggregates["profit_ex"].current_one_in,
            one_in_5x_or_better_ex_top=aggregates["5x"].current_one_in,
            one_in_10x_or_better_ex_top=aggregates["10x"].current_one_in,
            one_in_top_prize_estimated=aggregates["top"].current_one_in,
            one_in_1000_or_better=aggregates["1000"].current_one_in,
            one_in_10000_or_better=aggregates["10000"].current_one_in,
            one_in_100000_or_better=aggregates["100000"].current_one_in,
            ev_5x_or_better_ex_top=aggregates["5x"].current_expected_value,
            ev_10x_or_better_ex_top=aggregates["10x"].current_expected_value,
            estimated_ev_full=full.current_expected_value,
            estimated_ev_ex_top=ex_top.current_expected_value,
            launch_ev_full=full.launch_expected_value,
            launch_ev_ex_top=ex_top.launch_expected_value,
            estimated_payout_ratio_full=_ratio(full.current_expected_value, price),
            estimated_payout_ratio_ex_top=_ratio(ex_top.current_expected_value, price),
            estimated_house_edge_full=_house_edge(full.current_expected_value, price),
            estimated_house_edge_ex_top=_house_edge(ex_top.current_expected_value, price),
            ev_full_vs_launch=_ratio(full.current_expected_value, full.launch_expected_value),
            ev_ex_top_vs_launch=_ratio(ex_top.current_expected_value, ex_top.launch_expected_value),
            top_availability_index=top_metric.availability_index,
            full_count_coverage=full.count_coverage,
            full_value_coverage=full.value_coverage,
            ex_top_count_coverage=ex_top.count_coverage,
            ex_top_value_coverage=ex_top.value_coverage,
            top_prize_amount=top_source.prize_amount,
            top_prizes_original_reported=top_source.original_count,
            top_prizes_remaining_reported=top_source.remaining_count,
            top_confidence=top_metric.confidence_label,
            metric_statuses=statuses,
            metric_details=details,
            lowest_confidence=lowest,
            contains_lumpy_tier="lumpy" in labels,
        )
    )


def _metric_as_score(metric, source) -> TierScore:
    return TierScore(
        prize_amount=source.prize_amount,
        original_count=source.original_count,
        remaining_count=source.remaining_count,
        effective_remaining_count=metric.adjusted_remaining_count,
        is_top_prize=metric.is_top_prize,
        prize_group=metric.process_group,
        reference_kind=(
            "current_full_baseline"
            if metric.reference_method == "current_baseline"
            else metric.reference_method
        ),
        status=metric.status,
        unavailable_reason=metric.exclusion_reason,
        absolute_unavailable_reason=metric.exclusion_reason,
        reference_remaining_fraction=metric.reference_remaining_fraction,
        reported_survival=metric.observed_survival_fraction,
        availability_index=metric.availability_index,
        launch_probability=metric.launch_probability,
        current_probability=metric.current_probability,
        launch_one_in=metric.launch_one_in,
        current_one_in=metric.current_one_in,
    )


def _strategy_metric_detail(aggregate, *, scores, metrics, predicate, launch_metric_value) -> dict:
    labels = [
        metric.confidence_label
        for score, metric in zip(scores, metrics, strict=True)
        if predicate(score)
        and metric.current_probability is not None
        and metric.confidence_label is not None
    ]
    confidence_order = {"lumpy": 0, "low": 1, "moderate": 2, "high": 3}
    lowest = min(labels, key=confidence_order.get) if labels else None
    return {
        "target_tier_count": aggregate.target_tier_count,
        "valid_tier_count": aggregate.valid_tier_count,
        "count_coverage": _json_decimal(aggregate.count_coverage),
        "value_coverage": _json_decimal(aggregate.value_coverage),
        "launch_metric_value": _json_decimal(launch_metric_value),
        "lowest_confidence": lowest,
        "contains_lumpy_tier": "lumpy" in labels,
    }


def _json_decimal(value):
    return str(value) if value is not None else None


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _house_edge(ev, price):
    ratio = _ratio(ev, price)
    return Decimal(1) - ratio if ratio is not None else None
