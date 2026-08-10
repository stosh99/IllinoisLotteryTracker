"""Cutoff-scoped baseline and regular-tier analytics computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..analytics_models import (
    AnalyticsGameMetric,
    AnalyticsLagCalibration,
    AnalyticsLagGameEstimate,
    AnalyticsQualityIssue,
    AnalyticsStrategyMetric,
    AnalyticsTierMetric,
)
from ..models import GameSnapshot
from .confidence import (
    classify_confidence,
    classify_evidence,
    compute_lag_sensitivity,
    information_count,
    wilson_availability_interval,
)
from .lag import (
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    EXPLORATORY_ORIGINAL_TARGET,
    INTERNAL_QUANTILES,
    MAX_INTERPOLATION_GAP_DAYS,
    MIN_OVERLAP,
    MIN_SNAPSHOTS,
    MIN_SPAN_DAYS,
    PRIMARY_ORIGINAL_TARGET,
    aggregate_global_lag,
    fit_game_lag,
    interpolate_curve_at_time,
    leave_one_game_out_lag,
    subtract_decimal_days,
)
from .persistence import (
    MODEL_NAME,
    MODEL_VERSION,
    acquire_analytics_run,
    add_quality_issue_once,
    analytics_child_counts,
    clear_retryable_run_children,
    mark_analytics_run_success,
    model_is_approved,
    publish_staged_analytics_run,
)
from .progress import compute_game_progress, estimated_original_ticket_count
from .queries import (
    current_catalog_observed_at,
    load_current_memberships,
    load_cutoff_game_snapshots,
    load_game_baseline_curve,
    load_lag_game_histories,
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
    high_pending_count: int
    issue_count: int
    reused_successful_run: bool
    publishable: bool


@dataclass(frozen=True)
class LagCalibrationResult:
    analytics_run_id: int
    calibration_id: int
    candidate_game_count: int
    primary_qualified_game_count: int
    exploratory_game_count: int
    positive_game_count: int
    median_lag_days: Decimal | None
    q1_lag_days: Decimal | None
    q3_lag_days: Decimal | None
    bootstrap_lower_lag_days: Decimal | None
    bootstrap_upper_lag_days: Decimal | None
    status: str
    reason_code: str | None
    reused: bool


@dataclass(frozen=True)
class HighTierFinalizeResult:
    analytics_run_id: int
    game_count: int
    high_tier_count: int
    high_scored_count: int
    high_unavailable_count: int
    strategy_count: int
    publishable: bool


def compute_regular_analytics(
    session: Session,
    *,
    scrape_run_id: int | None = None,
    source_date: date | None = None,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
    force: bool = False,
    started_at: datetime | None = None,
) -> AnalyticsComputeResult:
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
        counts = analytics_child_counts(session, run.id)
        return AnalyticsComputeResult(
            analytics_run_id=run.id,
            source_run_id=cutoff.id,
            source_observed_at=cutoff.source_observed_at,
            game_count=counts.games,
            tier_count=counts.tiers,
            regular_scored_count=session.scalar(
                select(func.count())
                .select_from(AnalyticsTierMetric)
                .where(
                    AnalyticsTierMetric.analytics_run_id == run.id,
                    AnalyticsTierMetric.process_group != "high",
                )
            )
            or 0,
            high_pending_count=session.scalar(
                select(func.count())
                .select_from(AnalyticsTierMetric)
                .where(
                    AnalyticsTierMetric.analytics_run_id == run.id,
                    AnalyticsTierMetric.exclusion_reason == "LAG_NOT_AVAILABLE",
                )
            )
            or 0,
            issue_count=counts.issues,
            reused_successful_run=True,
            publishable=run.publishable,
        )
    if acquisition.retrying_failed:
        clear_retryable_run_children(session, run)

    snapshots = load_cutoff_game_snapshots(session, cutoff)
    memberships = load_current_memberships(session)
    catalog_observed_at = current_catalog_observed_at(session)
    regular_count = 0
    high_count = 0
    for snapshot in snapshots:
        regular, high = _compute_game(
            session,
            run_id=run.id,
            snapshot=snapshot,
            memberships=memberships,
            catalog_observed_at=catalog_observed_at,
        )
        regular_count += regular
        high_count += high
    mark_analytics_run_success(session, run, publishable=False)
    counts = analytics_child_counts(session, run.id)
    return AnalyticsComputeResult(
        analytics_run_id=run.id,
        source_run_id=cutoff.id,
        source_observed_at=cutoff.source_observed_at,
        game_count=counts.games,
        tier_count=counts.tiers,
        regular_scored_count=regular_count,
        high_pending_count=high_count,
        issue_count=counts.issues,
        reused_successful_run=False,
        publishable=False,
    )


def calibrate_claim_lag(
    session: Session,
    *,
    scrape_run_id: int | None = None,
    source_date: date | None = None,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
) -> LagCalibrationResult:
    cutoff = resolve_source_cutoff(
        session, scrape_run_id=scrape_run_id, source_date=source_date
    )
    acquisition = acquire_analytics_run(
        session,
        as_of_scrape_run_id=cutoff.id,
        model_name=model_name,
        semantic_version=semantic_version,
    )
    run = acquisition.run
    existing = session.scalar(
        select(AnalyticsLagCalibration).where(
            AnalyticsLagCalibration.analytics_run_id == run.id
        )
    )
    if existing is not None:
        return _lag_result(existing, reused=True)
    histories = load_lag_game_histories(session, cutoff)
    primary_lags: list[Decimal] = []
    exploratory_count = 0
    positive_count = 0
    game_rows: list[AnalyticsLagGameEstimate] = []
    for history in histories:
        primary_result = (
            fit_game_lag(list(history.primary_observations))
            if history.primary_band.eligible and history.prefit_exclusion_code is None
            else None
        )
        exploratory_result = (
            fit_game_lag(list(history.exploratory_observations))
            if history.exploratory_band.eligible
            and history.prefit_exclusion_code is None
            else None
        )
        primary_eligible = (
            primary_result is not None
            and primary_result.status == "available"
            and primary_result.median_lag_days is not None
        )
        exploratory_eligible = (
            exploratory_result is not None
            and exploratory_result.status == "available"
            and exploratory_result.median_lag_days is not None
        )
        if primary_eligible:
            assert primary_result is not None
            assert primary_result.median_lag_days is not None
            primary_lags.append(primary_result.median_lag_days)
            positive_count += primary_result.median_lag_days > 0
        if exploratory_eligible:
            exploratory_count += 1
        effective_result = primary_result or exploratory_result
        selected_band = (
            history.primary_band if primary_result is not None else history.exploratory_band
        )
        exclusion = history.prefit_exclusion_code
        if exclusion is None and not primary_eligible:
            exclusion = (
                primary_result.exclusion_reason
                if primary_result is not None
                else history.primary_band.exclusion_reason
            )
        game_rows.append(
            AnalyticsLagGameEstimate(
                analytics_run_id=run.id,
                game_id=history.game_id,
                eligible_primary=primary_eligible,
                eligible_exploratory=exploratory_eligible,
                exclusion_code=exclusion,
                top_prize_amount=history.top_prize_amount,
                adaptive_high_band_ceiling=selected_band.ceiling,
                selected_high_band_original_count=selected_band.original_count,
                snapshot_count=(effective_result.snapshot_count if effective_result else 0),
                history_span_days=(
                    effective_result.history_span_days if effective_result else Decimal(0)
                ),
                common_progress_lower=(
                    effective_result.common_progress_lower if effective_result else None
                ),
                common_progress_upper=(
                    effective_result.common_progress_upper if effective_result else None
                ),
                common_progress_width=(
                    effective_result.common_progress_width if effective_result else None
                ),
                valid_quantile_count=(
                    effective_result.valid_quantile_count if effective_result else 0
                ),
                median_lag_days=(
                    effective_result.median_lag_days if effective_result else None
                ),
                q1_lag_days=(effective_result.q1_lag_days if effective_result else None),
                q3_lag_days=(effective_result.q3_lag_days if effective_result else None),
                used_in_global=primary_eligible,
            )
        )
    global_result = aggregate_global_lag(
        primary_lags,
        candidate_game_count=len(histories),
        bootstrap_samples=BOOTSTRAP_SAMPLES,
        bootstrap_seed=BOOTSTRAP_SEED,
    )
    calibration = AnalyticsLagCalibration(
        analytics_run_id=run.id,
        method="adaptive_horizontal_shift_v1",
        primary_original_count=PRIMARY_ORIGINAL_TARGET,
        exploratory_original_count=EXPLORATORY_ORIGINAL_TARGET,
        minimum_snapshots=MIN_SNAPSHOTS,
        minimum_span_days=int(MIN_SPAN_DAYS),
        minimum_overlap_fraction=MIN_OVERLAP,
        internal_quantile_count=INTERNAL_QUANTILES,
        maximum_interpolation_gap_days=int(MAX_INTERPOLATION_GAP_DAYS),
        candidate_game_count=len(histories),
        primary_qualified_game_count=len(primary_lags),
        exploratory_game_count=exploratory_count,
        positive_game_count=positive_count,
        excluded_game_count=len(histories) - len(primary_lags),
        global_median_lag_days=global_result.median_lag_days,
        global_q1_lag_days=global_result.q1_lag_days,
        global_q3_lag_days=global_result.q3_lag_days,
        bootstrap_lower_lag_days=global_result.bootstrap_lower_lag_days,
        bootstrap_upper_lag_days=global_result.bootstrap_upper_lag_days,
        status=global_result.status,
        reason_code=global_result.reason_code,
    )
    session.add_all([calibration, *game_rows])
    session.flush()
    return _lag_result(calibration, reused=False)


def _lag_result(
    calibration: AnalyticsLagCalibration, *, reused: bool
) -> LagCalibrationResult:
    return LagCalibrationResult(
        analytics_run_id=calibration.analytics_run_id,
        calibration_id=calibration.id,
        candidate_game_count=calibration.candidate_game_count,
        primary_qualified_game_count=calibration.primary_qualified_game_count,
        exploratory_game_count=calibration.exploratory_game_count,
        positive_game_count=calibration.positive_game_count,
        median_lag_days=calibration.global_median_lag_days,
        q1_lag_days=calibration.global_q1_lag_days,
        q3_lag_days=calibration.global_q3_lag_days,
        bootstrap_lower_lag_days=calibration.bootstrap_lower_lag_days,
        bootstrap_upper_lag_days=calibration.bootstrap_upper_lag_days,
        status=calibration.status,
        reason_code=calibration.reason_code,
        reused=reused,
    )


def finalize_high_tier_analytics(
    session: Session,
    *,
    scrape_run_id: int | None = None,
    source_date: date | None = None,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
) -> HighTierFinalizeResult:
    cutoff = resolve_source_cutoff(
        session, scrape_run_id=scrape_run_id, source_date=source_date
    )
    acquisition = acquire_analytics_run(
        session,
        as_of_scrape_run_id=cutoff.id,
        model_name=model_name,
        semantic_version=semantic_version,
    )
    run = acquisition.run
    if run.publishable:
        currently_publishable = model_is_approved(session, run.model_version_id)
        counts = analytics_child_counts(session, run.id)
        high_total, high_scored = _stored_high_counts(session, run.id)
        return HighTierFinalizeResult(
            analytics_run_id=run.id,
            game_count=counts.games,
            high_tier_count=high_total,
            high_scored_count=high_scored,
            high_unavailable_count=high_total - high_scored,
            strategy_count=counts.strategies,
            publishable=currently_publishable,
        )
    calibration = session.scalar(
        select(AnalyticsLagCalibration).where(
            AnalyticsLagCalibration.analytics_run_id == run.id
        )
    )
    if calibration is None:
        raise ValueError("lag calibration step has not run")
    if calibration.status != "available":
        game_metrics = session.scalars(
            select(AnalyticsGameMetric)
            .where(AnalyticsGameMetric.analytics_run_id == run.id)
            .order_by(AnalyticsGameMetric.game_id)
        ).all()
        high_total = 0
        for game_metric in game_metrics:
            snapshot = session.get(GameSnapshot, game_metric.game_snapshot_id)
            assert snapshot is not None
            _ = snapshot.game, snapshot.prize_tiers
            source_by_id = {tier.id: tier for tier in snapshot.prize_tiers}
            metrics = session.scalars(
                select(AnalyticsTierMetric).where(
                    AnalyticsTierMetric.analytics_run_id == run.id,
                    AnalyticsTierMetric.game_id == game_metric.game_id,
                )
            ).all()
            high_total += sum(metric.process_group == "high" for metric in metrics)
            _refresh_game_coverage(game_metric, metrics, source_by_id)
            _persist_strategy_metric(session, run.id, game_metric)
        add_quality_issue_once(
            session,
            analytics_run_id=run.id,
            code="LAG_CALIBRATION_UNAVAILABLE",
            severity="warning",
            entity_type="run",
            message="High-tier metrics remain unavailable at this historical cutoff.",
            details={
                "calibration_status": calibration.status,
                "reason_code": calibration.reason_code,
            },
        )
        publishable = publish_staged_analytics_run(
            session, run, publication_gates_passed=False
        )
        counts = analytics_child_counts(session, run.id)
        return HighTierFinalizeResult(
            analytics_run_id=run.id,
            game_count=counts.games,
            high_tier_count=high_total,
            high_scored_count=0,
            high_unavailable_count=high_total,
            strategy_count=counts.strategies,
            publishable=publishable,
        )
    lag_audit_rows = session.scalars(
        select(AnalyticsLagGameEstimate).where(
            AnalyticsLagGameEstimate.analytics_run_id == run.id
        )
    ).all()
    lag_rows = [
        row
        for row in lag_audit_rows
        if row.used_in_global and row.median_lag_days is not None
    ]
    game_lags = {row.game_id: row.median_lag_days for row in lag_rows}
    assert all(value is not None for value in game_lags.values())
    game_lags = {key: value for key, value in game_lags.items() if value is not None}
    invalid_history = {
        row.game_id: row.exclusion_code
        for row in lag_audit_rows
        if row.exclusion_code in {"STRUCTURE_CHANGED", "PROGRESS_REVERSAL"}
    }
    game_metrics = session.scalars(
        select(AnalyticsGameMetric)
        .where(AnalyticsGameMetric.analytics_run_id == run.id)
        .order_by(AnalyticsGameMetric.game_id)
    ).all()
    high_total = 0
    high_scored = 0
    for game_metric in game_metrics:
        total, scored = _finalize_game_high_tiers(
            session,
            run_id=run.id,
            cutoff=cutoff,
            game_metric=game_metric,
            calibration=calibration,
            game_lags=game_lags,
            history_exclusion=invalid_history.get(game_metric.game_id),
        )
        high_total += total
        high_scored += scored
    session.flush()
    for game_metric in game_metrics:
        _persist_strategy_metric(session, run.id, game_metric)
    publishable = publish_staged_analytics_run(session, run)
    counts = analytics_child_counts(session, run.id)
    return HighTierFinalizeResult(
        analytics_run_id=run.id,
        game_count=counts.games,
        high_tier_count=high_total,
        high_scored_count=high_scored,
        high_unavailable_count=high_total - high_scored,
        strategy_count=counts.strategies,
        publishable=publishable,
    )


def _finalize_game_high_tiers(
    session: Session,
    *,
    run_id: int,
    cutoff,
    game_metric: AnalyticsGameMetric,
    calibration: AnalyticsLagCalibration,
    game_lags: dict[int, Decimal],
    history_exclusion: str | None,
) -> tuple[int, int]:
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
    high_metrics = [metric for metric in metrics if metric.process_group == "high"]
    if not high_metrics:
        return 0, 0
    if history_exclusion is not None:
        total_original_winners = sum(tier.original_count for tier in snapshot.prize_tiers)
        for metric in high_metrics:
            source = source_by_id[metric.prize_tier_snapshot_id]
            score = score_high_tier(
                TierInput(
                    prize_amount=source.prize_amount,
                    original_count=source.original_count,
                    remaining_count=source.remaining_count,
                    is_top_prize=metric.is_top_prize,
                ),
                lagged_baseline_remaining_fraction=None,
                current_baseline_remaining_fraction=game_metric.baseline_remaining_fraction,
                total_original_winners=total_original_winners,
                overall_odds_one_in=snapshot.game.overall_odds_one_in,
                lag_unavailable_reason=history_exclusion,
            )
            _apply_high_score(
                metric,
                score=score,
                sensitivity_scores=[],
                lag_days=None,
                includes_game=False,
                reference_observed_at=None,
            )
        _refresh_game_coverage(game_metric, metrics, source_by_id)
        session.execute(
            delete(AnalyticsQualityIssue).where(
                AnalyticsQualityIssue.analytics_run_id == run_id,
                AnalyticsQualityIssue.game_id == game_metric.game_id,
                AnalyticsQualityIssue.code == "LAG_NOT_AVAILABLE",
            )
        )
        add_quality_issue_once(
            session,
            analytics_run_id=run_id,
            code=history_exclusion,
            severity="warning",
            entity_type="game",
            game_id=game_metric.game_id,
            game_snapshot_id=game_metric.game_snapshot_id,
            message="High-tier scoring excluded because the baseline history is not stable.",
        )
        return len(high_metrics), 0
    lag_days, includes_game = leave_one_game_out_lag(game_lags, game_metric.game_id)
    curve = load_game_baseline_curve(
        session, game_id=game_metric.game_id, cutoff=cutoff
    )
    total_original_winners = sum(tier.original_count for tier in snapshot.prize_tiers)
    sensitivity_lags = [
        calibration.global_q1_lag_days,
        lag_days,
        calibration.global_q3_lag_days,
    ]
    scored_count = 0
    for metric in high_metrics:
        source = source_by_id[metric.prize_tier_snapshot_id]
        tier_input = TierInput(
            prize_amount=source.prize_amount,
            original_count=source.original_count,
            remaining_count=source.remaining_count,
            is_top_prize=metric.is_top_prize,
        )
        reference = _lagged_reference(curve, cutoff.source_observed_at, lag_days)
        score = score_high_tier(
            tier_input,
            lagged_baseline_remaining_fraction=reference,
            current_baseline_remaining_fraction=game_metric.baseline_remaining_fraction,
            total_original_winners=total_original_winners,
            overall_odds_one_in=snapshot.game.overall_odds_one_in,
            lag_unavailable_reason=(
                "LAG_NOT_AVAILABLE" if lag_days is None else "LAG_REFERENCE_NOT_AVAILABLE"
            ),
        )
        sensitivity_scores = []
        for sensitivity_lag in sensitivity_lags:
            sensitivity_reference = _lagged_reference(
                curve, cutoff.source_observed_at, sensitivity_lag
            )
            sensitivity_scores.append(
                score_high_tier(
                    tier_input,
                    lagged_baseline_remaining_fraction=sensitivity_reference,
                    current_baseline_remaining_fraction=game_metric.baseline_remaining_fraction,
                    total_original_winners=total_original_winners,
                    overall_odds_one_in=snapshot.game.overall_odds_one_in,
                    lag_unavailable_reason="LAG_REFERENCE_NOT_AVAILABLE",
                )
            )
        _apply_high_score(
            metric,
            score=score,
            sensitivity_scores=sensitivity_scores,
            lag_days=lag_days,
            includes_game=includes_game,
            reference_observed_at=(
                subtract_decimal_days(cutoff.source_observed_at, lag_days)
                if lag_days is not None
                else None
            ),
        )
        if score.current_probability is not None:
            scored_count += 1
    _refresh_game_coverage(game_metric, metrics, source_by_id)
    session.execute(
        delete(AnalyticsQualityIssue).where(
            AnalyticsQualityIssue.analytics_run_id == run_id,
            AnalyticsQualityIssue.game_id == game_metric.game_id,
            AnalyticsQualityIssue.code == "LAG_NOT_AVAILABLE",
        )
    )
    if scored_count < len(high_metrics):
        add_quality_issue_once(
            session,
            analytics_run_id=run_id,
            code="HIGH_TIER_PARTIAL",
            severity="warning",
            entity_type="game",
            game_id=game_metric.game_id,
            game_snapshot_id=game_metric.game_snapshot_id,
            message=f"{len(high_metrics) - scored_count} high tiers lack a lagged reference.",
        )
    return len(high_metrics), scored_count


def _lagged_reference(curve, observed_at, lag_days):
    if lag_days is None:
        return None
    target = subtract_decimal_days(observed_at, lag_days)
    return interpolate_curve_at_time(curve, target)


def _apply_high_score(
    metric: AnalyticsTierMetric,
    *,
    score: TierScore,
    sensitivity_scores: list[TierScore],
    lag_days: Decimal | None,
    includes_game: bool,
    reference_observed_at,
) -> None:
    interval = (
        wilson_availability_interval(
            claimed_count=score.original_count - score.remaining_count,
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
    sensitivity_pairs = [
        (item.availability_index, item.current_one_in)
        for item in sensitivity_scores
        if item.availability_index is not None
    ]
    sensitivity_availability = [item[0] for item in sensitivity_pairs]
    sensitivity_odds = [item[1] for item in sensitivity_pairs]
    sensitivity = (
        compute_lag_sensitivity(
            availabilities=sensitivity_availability,
            one_in_values=sensitivity_odds,
            point_index=min(1, len(sensitivity_availability) - 1),
        )
        if sensitivity_availability
        else None
    )
    evidence = classify_evidence(
        interval=interval,
        sensitivity_availabilities=(
            sensitivity_availability if len(sensitivity_availability) == 3 else []
        ),
        confidence=confidence,
    )
    metric.reference_method = score.reference_kind
    metric.reference_observed_at = reference_observed_at
    metric.lag_days_used = lag_days
    metric.lag_includes_scored_game = includes_game
    metric.reference_remaining_fraction = score.reference_remaining_fraction
    metric.observed_survival_fraction = score.reported_survival
    metric.expected_reported_remaining = score.expected_reported_remaining
    metric.availability_index = score.availability_index
    metric.availability_wilson_lower = interval.availability_lower if interval else None
    metric.availability_wilson_upper = interval.availability_upper if interval else None
    metric.availability_sensitivity_min = (
        sensitivity.minimum_availability if sensitivity else None
    )
    metric.availability_sensitivity_max = (
        sensitivity.maximum_availability if sensitivity else None
    )
    metric.one_in_sensitivity_min = sensitivity.minimum_one_in if sensitivity else None
    metric.one_in_sensitivity_max = sensitivity.maximum_one_in if sensitivity else None
    metric.lag_sensitivity_direction_changes = (
        sensitivity.direction_changes if sensitivity else None
    )
    metric.launch_probability = score.launch_probability
    metric.launch_one_in = score.launch_one_in
    metric.current_probability = score.current_probability
    metric.current_one_in = score.current_one_in
    metric.equivalent_current_remaining = score.equivalent_current_remaining
    metric.confidence_label = confidence
    metric.information_count = (
        information_count(score.original_count, score.reference_remaining_fraction)
        if score.reference_remaining_fraction is not None
        else None
    )
    metric.evidence_classification = evidence
    metric.status = score.status
    metric.exclusion_reason = score.unavailable_reason or score.absolute_unavailable_reason


def _refresh_game_coverage(game_metric, metrics, source_by_id) -> None:
    all_count = sum(
        source_by_id[metric.prize_tier_snapshot_id].original_count
        for metric in metrics
    )
    all_value = sum(
        (
            source_by_id[metric.prize_tier_snapshot_id].prize_amount
            * Decimal(source_by_id[metric.prize_tier_snapshot_id].original_count)
            for metric in metrics
        ),
        start=Decimal(0),
    )
    high = [metric for metric in metrics if metric.process_group == "high"]
    high_count = sum(source_by_id[metric.prize_tier_snapshot_id].original_count for metric in high)
    high_value = sum(
        (
            source_by_id[metric.prize_tier_snapshot_id].prize_amount
            * Decimal(source_by_id[metric.prize_tier_snapshot_id].original_count)
            for metric in high
        ),
        start=Decimal(0),
    )
    valid = [metric for metric in metrics if metric.current_probability is not None]
    valid_high = [metric for metric in high if metric.current_probability is not None]
    valid_count = sum(
        source_by_id[metric.prize_tier_snapshot_id].original_count for metric in valid
    )
    valid_value = sum(
        (
            source_by_id[metric.prize_tier_snapshot_id].prize_amount
            * Decimal(source_by_id[metric.prize_tier_snapshot_id].original_count)
            for metric in valid
        ),
        start=Decimal(0),
    )
    valid_high_count = sum(
        source_by_id[metric.prize_tier_snapshot_id].original_count for metric in valid_high
    )
    valid_high_value = sum(
        (
            source_by_id[metric.prize_tier_snapshot_id].prize_amount
            * Decimal(source_by_id[metric.prize_tier_snapshot_id].original_count)
            for metric in valid_high
        ),
        start=Decimal(0),
    )
    game_metric.full_score_count_coverage = Decimal(valid_count) / Decimal(all_count)
    game_metric.full_score_value_coverage = valid_value / all_value
    game_metric.high_score_count_coverage = (
        Decimal(valid_high_count) / Decimal(high_count) if high_count else Decimal(1)
    )
    game_metric.high_score_value_coverage = (
        valid_high_value / high_value if high_value else Decimal(1)
    )
    if not valid:
        game_metric.data_status = "unavailable"
    elif len(valid) == len(metrics):
        game_metric.data_status = "complete"
    else:
        game_metric.data_status = "partial"
    game_metric.publishable = game_metric.data_status == "complete"


def _persist_strategy_metric(
    session: Session, run_id: int, game_metric: AnalyticsGameMetric
) -> None:
    existing = session.scalar(
        select(AnalyticsStrategyMetric).where(
            AnalyticsStrategyMetric.analytics_run_id == run_id,
            AnalyticsStrategyMetric.game_id == game_metric.game_id,
        )
    )
    if existing is not None:
        return
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
    aggregates = {
        "any": aggregate_tiers(scores, lambda score: True),
        "break_exact": aggregate_tiers(scores, lambda score: score.prize_amount == price),
        "break_better": aggregate_tiers(scores, lambda score: score.prize_amount >= price),
        "2x": aggregate_tiers(scores, lambda score: score.prize_amount >= price * 2),
        "profit": aggregate_tiers(scores, lambda score: score.prize_amount > price),
        "profit_ex": aggregate_tiers(
            scores, lambda score: score.prize_amount > price and not score.is_top_prize
        ),
        "5x": aggregate_tiers(
            scores, lambda score: score.prize_amount >= price * 5 and not score.is_top_prize
        ),
        "10x": aggregate_tiers(
            scores, lambda score: score.prize_amount >= price * 10 and not score.is_top_prize
        ),
        "20x": aggregate_tiers(
            scores, lambda score: score.prize_amount >= price * 20 and not score.is_top_prize
        ),
        "50x": aggregate_tiers(
            scores, lambda score: score.prize_amount >= price * 50 and not score.is_top_prize
        ),
        "100_1000": aggregate_tiers(
            scores, lambda score: 100 <= score.prize_amount <= 1000 and not score.is_top_prize
        ),
        "top": aggregate_tiers(scores, lambda score: score.is_top_prize),
        "1000": aggregate_tiers(scores, lambda score: score.prize_amount >= 1000),
        "10000": aggregate_tiers(scores, lambda score: score.prize_amount >= 10000),
        "100000": aggregate_tiers(scores, lambda score: score.prize_amount >= 100000),
        "1000000": aggregate_tiers(scores, lambda score: score.prize_amount >= 1000000),
        "ex_top": aggregate_tiers(scores, lambda score: not score.is_top_prize),
    }
    full = aggregates["any"]
    ex_top = aggregates["ex_top"]
    top_amount = max(tier.prize_amount for tier in snapshot.prize_tiers)
    top_source = next(
        source for source in snapshot.prize_tiers if source.prize_amount == top_amount
    )
    top_metric = next(metric for metric in metrics if metric.is_top_prize)
    confidence_order = {"lumpy": 0, "low": 1, "moderate": 2, "high": 3}
    confidence_labels = [metric.confidence_label for metric in metrics if metric.confidence_label]
    lowest = min(confidence_labels, key=confidence_order.get) if confidence_labels else None
    strategy_specs = {
        "money_back_exact": (
            aggregates["break_exact"],
            lambda score: score.prize_amount == price,
            aggregates["break_exact"].launch_probability,
        ),
        "profit_ex_top": (
            aggregates["profit_ex"],
            lambda score: score.prize_amount > price and not score.is_top_prize,
            aggregates["profit_ex"].launch_probability,
        ),
        "value_full": (
            full,
            lambda score: True,
            _ratio(full.launch_expected_value, price),
        ),
        "value_ex_top": (
            ex_top,
            lambda score: not score.is_top_prize,
            _ratio(ex_top.launch_expected_value, price),
        ),
        "moderate_5x": (
            aggregates["5x"],
            lambda score: score.prize_amount >= price * 5 and not score.is_top_prize,
            aggregates["5x"].launch_probability,
        ),
        "moderate_10x": (
            aggregates["10x"],
            lambda score: score.prize_amount >= price * 10 and not score.is_top_prize,
            aggregates["10x"].launch_probability,
        ),
        "jackpot_top_odds": (
            aggregates["top"],
            lambda score: score.is_top_prize,
            aggregates["top"].launch_probability,
        ),
        "large_1000": (
            aggregates["1000"],
            lambda score: score.prize_amount >= 1000,
            aggregates["1000"].launch_probability,
        ),
        "large_100000": (
            aggregates["100000"],
            lambda score: score.prize_amount >= 100000,
            aggregates["100000"].launch_probability,
        ),
    }
    statuses = {key: aggregate.status for key, (aggregate, _, _) in strategy_specs.items()}
    metric_details = {
        key: _strategy_metric_detail(
            aggregate,
            scores=scores,
            metrics=metrics,
            predicate=predicate,
            launch_metric_value=launch_metric_value,
        )
        for key, (aggregate, predicate, launch_metric_value) in strategy_specs.items()
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
            one_in_any_win=full.current_one_in,
            one_in_break_even_exact=aggregates["break_exact"].current_one_in,
            one_in_strict_profit_ex_top=aggregates["profit_ex"].current_one_in,
            profit_probability_vs_launch=_ratio(
                aggregates["profit_ex"].current_probability,
                aggregates["profit_ex"].launch_probability,
            ),
            p_5x_or_better_ex_top=aggregates["5x"].current_probability,
            p_10x_or_better_ex_top=aggregates["10x"].current_probability,
            p_20x_or_better_ex_top=aggregates["20x"].current_probability,
            p_50x_or_better_ex_top=aggregates["50x"].current_probability,
            p_100_to_1000_ex_top=aggregates["100_1000"].current_probability,
            one_in_5x_or_better_ex_top=aggregates["5x"].current_one_in,
            one_in_10x_or_better_ex_top=aggregates["10x"].current_one_in,
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
            p_top_prize_estimated=aggregates["top"].current_probability,
            one_in_top_prize_estimated=aggregates["top"].current_one_in,
            top_prize_amount=top_source.prize_amount,
            top_prizes_original_reported=top_source.original_count,
            top_prizes_remaining_reported=top_source.remaining_count,
            top_availability_index=top_metric.availability_index,
            top_confidence=top_metric.confidence_label,
            p_1000_or_better=aggregates["1000"].current_probability,
            p_10000_or_better=aggregates["10000"].current_probability,
            p_100000_or_better=aggregates["100000"].current_probability,
            p_1000000_or_better=aggregates["1000000"].current_probability,
            one_in_1000_or_better=aggregates["1000"].current_one_in,
            one_in_10000_or_better=aggregates["10000"].current_one_in,
            one_in_100000_or_better=aggregates["100000"].current_one_in,
            full_count_coverage=full.count_coverage,
            full_value_coverage=full.value_coverage,
            ex_top_count_coverage=ex_top.count_coverage,
            ex_top_value_coverage=ex_top.value_coverage,
            metric_statuses=statuses,
            metric_details=metric_details,
            lowest_confidence=lowest,
            contains_lumpy_tier="lumpy" in confidence_labels,
        )
    )


def _metric_as_score(metric, source) -> TierScore:
    return TierScore(
        prize_amount=source.prize_amount,
        original_count=source.original_count,
        remaining_count=source.remaining_count,
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
        expected_reported_remaining=metric.expected_reported_remaining,
        equivalent_current_remaining=metric.equivalent_current_remaining,
    )


def _strategy_metric_detail(
    aggregate,
    *,
    scores,
    metrics,
    predicate,
    launch_metric_value,
) -> dict:
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


def _stored_high_counts(session: Session, run_id: int) -> tuple[int, int]:
    total = session.scalar(
        select(func.count()).select_from(AnalyticsTierMetric).where(
            AnalyticsTierMetric.analytics_run_id == run_id,
            AnalyticsTierMetric.process_group == "high",
        )
    ) or 0
    scored = session.scalar(
        select(func.count()).select_from(AnalyticsTierMetric).where(
            AnalyticsTierMetric.analytics_run_id == run_id,
            AnalyticsTierMetric.process_group == "high",
            AnalyticsTierMetric.current_probability.is_not(None),
        )
    ) or 0
    return total, scored


def _compute_game(
    session: Session,
    *,
    run_id: int,
    snapshot: GameSnapshot,
    memberships,
    catalog_observed_at,
) -> tuple[int, int]:
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
            message="Game baseline progress is unavailable.",
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
    valid_original_count = 0
    valid_original_value = Decimal(0)
    regular_count = 0
    high_count = 0
    for source_tier, tier_input in zip(ordered, inputs, strict=True):
        group = classify_prize_group(tier_input.prize_amount)
        if group == "high":
            score = None
            high_count += 1
            metric = AnalyticsTierMetric(
                analytics_run_id=run_id,
                game_id=game.id,
                game_snapshot_id=snapshot.id,
                prize_tier_snapshot_id=source_tier.id,
                is_top_prize=tier_input.is_top_prize,
                process_group="high",
                reference_method="unavailable",
                current_baseline_remaining_fraction=baseline.remaining_fraction,
                status="unavailable",
                exclusion_reason="LAG_NOT_AVAILABLE",
                evidence_classification="unavailable",
            )
        else:
            score = score_regular_tier(
                tier_input,
                baseline=baseline,
                total_original_winners=total_original_winners,
                overall_odds_one_in=game.overall_odds_one_in,
            )
            regular_count += 1
            metric = _tier_metric_from_score(
                run_id=run_id,
                snapshot=snapshot,
                source_tier_id=source_tier.id,
                score=score,
                current_baseline=baseline.remaining_fraction,
            )
            if score.current_probability is not None:
                valid_original_count += tier_input.original_count
                valid_original_value += (
                    tier_input.prize_amount * Decimal(tier_input.original_count)
                )
        session.add(metric)
    total_original_value = sum(
        (tier.prize_amount * Decimal(tier.original_count) for tier in inputs),
        start=Decimal(0),
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
    session.add(
        AnalyticsGameMetric(
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
            full_score_count_coverage=(
                Decimal(valid_original_count) / Decimal(total_original_winners)
                if total_original_winners
                else None
            ),
            full_score_value_coverage=(
                valid_original_value / total_original_value
                if total_original_value
                else None
            ),
            high_score_count_coverage=Decimal(0),
            high_score_value_coverage=Decimal(0),
            prize_source_current=prize_current,
            catalog_current=catalog_current,
            recommendation_current=recommendation_current,
            catalog_observed_at=catalog_observed_at,
            data_status=data_status,
            publishable=False,
        )
    )
    if high_count:
        add_quality_issue_once(
            session,
            analytics_run_id=run_id,
            code="LAG_NOT_AVAILABLE",
            severity="info",
            entity_type="game",
            game_id=game.id,
            game_snapshot_id=snapshot.id,
            message=f"{high_count} high tiers await lag calibration.",
        )
    session.flush()
    return regular_count, high_count


def _tier_metric_from_score(
    *,
    run_id: int,
    snapshot: GameSnapshot,
    source_tier_id: int,
    score: TierScore,
    current_baseline: Decimal | None,
) -> AnalyticsTierMetric:
    interval = (
        wilson_availability_interval(
            claimed_count=score.original_count - score.remaining_count,
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
    reference_method = {
        "leave_one_tier_out": "leave_one_tier_out",
        "current_full_baseline": "current_baseline",
        "unavailable": "unavailable",
    }[score.reference_kind]
    return AnalyticsTierMetric(
        analytics_run_id=run_id,
        game_id=snapshot.game_id,
        game_snapshot_id=snapshot.id,
        prize_tier_snapshot_id=source_tier_id,
        is_top_prize=score.is_top_prize,
        process_group=score.prize_group,
        reference_method=reference_method,
        reference_observed_at=snapshot.captured_at,
        current_baseline_remaining_fraction=current_baseline,
        reference_remaining_fraction=score.reference_remaining_fraction,
        observed_survival_fraction=score.reported_survival,
        availability_index=score.availability_index,
        availability_wilson_lower=(interval.availability_lower if interval else None),
        availability_wilson_upper=(interval.availability_upper if interval else None),
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
