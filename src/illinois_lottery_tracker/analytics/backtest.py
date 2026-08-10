"""Cutoff-strict walk-forward validation and model-promotion reporting."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, selectinload

from ..analytics_models import (
    AnalyticsBacktestPrediction,
    AnalyticsBacktestRun,
    AnalyticsBacktestSummary,
)
from ..models import GameSnapshot, PrizeTierSnapshot, ScrapeRun
from .confidence import classify_confidence, classify_evidence, wilson_availability_interval
from .lag import (
    PRIMARY_ORIGINAL_TARGET,
    ProgressObservation,
    aggregate_global_lag,
    fit_game_lag,
    interpolate_curve_at_time,
    leave_one_game_out_lag,
    select_adaptive_band,
    subtract_decimal_days,
)
from .persistence import (
    MODEL_NAME,
    MODEL_VERSION,
    get_model_version,
    reject_model_version,
)
from .tiers import classify_prize_group
from .types import TierInput

HORIZONS = (7, 14, 30)
MINIMUM_PRIOR_DAYS = 30
TARGET_TOLERANCE_DAYS = 1
BACKTEST_METHOD_VERSION = "walk_forward_v1_paired_comparison"
Variant = Literal["aligned", "no_lag", "legacy"]


@dataclass(frozen=True)
class FrozenFeature:
    cutoff_scrape_run_id: int
    game_id: int
    cutoff_game_snapshot_id: int
    cutoff_structure_fingerprint: str | None
    prize_amount: Decimal
    original_count: int
    cutoff_remaining_count: int
    process_group: str
    model_variant: Variant
    cutoff_reference_fraction: Decimal | None
    lag_days: Decimal | None
    confidence_label: str | None
    evidence_cohort: str
    ticket_price_group: str
    cutoff_inputs: dict
    exclusion_code: str | None = None


@dataclass(frozen=True)
class PredictionResult:
    predicted_count: Decimal | None
    predicted_fraction: Decimal | None
    lower_count: Decimal | None
    upper_count: Decimal | None
    observed_count: int | None
    observed_fraction: Decimal | None
    signed_count_error: Decimal | None
    absolute_count_error: Decimal | None
    signed_fraction_error: Decimal | None
    absolute_fraction_error: Decimal | None
    standardized_error: Decimal | None
    interval_contains_observed: bool | None
    eligibility_code: str


@dataclass(frozen=True)
class BacktestResult:
    backtest_run_id: int
    cutoff_count: int
    prediction_count: int
    eligible_prediction_count: int
    excluded_prediction_count: int
    summary_count: int
    promotion_status: str
    reused: bool


def assert_no_lookahead(cutoff: datetime, feature_observed_times: list[datetime]) -> None:
    """Fail closed if any calibration/feature observation is after its cutoff."""
    future = [value for value in feature_observed_times if value > cutoff]
    if future:
        raise ValueError(
            "NO_LOOKAHEAD_VIOLATION: feature/calibration observation after cutoff "
            f"({min(future).isoformat()} > {cutoff.isoformat()})"
        )


def conditional_depletion_prediction(
    *,
    cutoff_remaining_count: int,
    original_count: int,
    cutoff_reference_fraction: Decimal,
    target_reference_fraction: Decimal,
) -> PredictionResult:
    """Apply ``R(t) * b(u) / b(t)`` and a transparent binomial interval."""
    if original_count <= 0 or not 0 <= cutoff_remaining_count <= original_count:
        return _excluded_result("INVALID_TIER_COUNTS")
    if not Decimal(0) < cutoff_reference_fraction <= Decimal(1):
        return _excluded_result("CUTOFF_REFERENCE_UNAVAILABLE")
    if not Decimal(0) <= target_reference_fraction <= Decimal(1):
        return _excluded_result("TARGET_REFERENCE_UNAVAILABLE")
    if target_reference_fraction > cutoff_reference_fraction:
        return _excluded_result("REFERENCE_REVERSAL")
    with localcontext() as context:
        context.prec = 50
        predicted = (
            Decimal(cutoff_remaining_count)
            * target_reference_fraction
            / cutoff_reference_fraction
        )
        predicted_fraction = predicted / Decimal(original_count)
        variance = (
            Decimal(original_count)
            * predicted_fraction
            * (Decimal(1) - predicted_fraction)
        )
        deviation = variance.sqrt() if variance > 0 else Decimal(0)
        radius = Decimal("1.959963984540054") * deviation
        lower = max(Decimal(0), predicted - radius)
        upper = min(Decimal(cutoff_remaining_count), predicted + radius)
    return PredictionResult(
        predicted_count=predicted,
        predicted_fraction=predicted_fraction,
        lower_count=lower,
        upper_count=upper,
        observed_count=None,
        observed_fraction=None,
        signed_count_error=None,
        absolute_count_error=None,
        signed_fraction_error=None,
        absolute_fraction_error=None,
        standardized_error=None,
        interval_contains_observed=None,
        eligibility_code="ELIGIBLE",
    )


def score_observation(
    prediction: PredictionResult, observed_count: int, *, original_count: int
) -> PredictionResult:
    if prediction.eligibility_code != "ELIGIBLE" or prediction.predicted_count is None:
        return prediction
    if prediction.predicted_fraction is None or prediction.lower_count is None:
        return prediction
    if prediction.upper_count is None or observed_count < 0:
        return _excluded_result("INVALID_TARGET_COUNT")
    if original_count <= 0:
        return _excluded_result("INVALID_TIER_COUNTS")
    original = Decimal(original_count)
    observed_fraction = Decimal(observed_count) / original
    signed_count = prediction.predicted_count - Decimal(observed_count)
    signed_fraction = prediction.predicted_fraction - observed_fraction
    variance = (
        original
        * prediction.predicted_fraction
        * (Decimal(1) - prediction.predicted_fraction)
    )
    deviation = max(Decimal(1), variance.sqrt() if variance > 0 else Decimal(0))
    return PredictionResult(
        predicted_count=prediction.predicted_count,
        predicted_fraction=prediction.predicted_fraction,
        lower_count=prediction.lower_count,
        upper_count=prediction.upper_count,
        observed_count=observed_count,
        observed_fraction=observed_fraction,
        signed_count_error=signed_count,
        absolute_count_error=abs(signed_count),
        signed_fraction_error=signed_fraction,
        absolute_fraction_error=abs(signed_fraction),
        standardized_error=signed_count / deviation,
        interval_contains_observed=(
            prediction.lower_count <= Decimal(observed_count) <= prediction.upper_count
        ),
        eligibility_code="ELIGIBLE",
    )


def choose_target_run(
    cutoff: ScrapeRun, runs: list[ScrapeRun], horizon_days: int
) -> ScrapeRun | None:
    desired = cutoff.source_observed_at + timedelta(days=horizon_days)
    candidates = [
        run
        for run in runs
        if run.source_observed_at > cutoff.source_observed_at
        and abs((run.source_observed_at - desired).total_seconds())
        <= TARGET_TOLERANCE_DAYS * 86_400
    ]
    return min(
        candidates,
        key=lambda run: (
            abs((run.source_observed_at - desired).total_seconds()),
            run.source_observed_at,
            run.id,
        ),
        default=None,
    )


def run_walk_forward_backtest(
    session: Session,
    *,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
    horizons: tuple[int, ...] = HORIZONS,
    cutoff_start: datetime | None = None,
    cutoff_end: datetime | None = None,
) -> BacktestResult:
    if tuple(sorted(set(horizons))) != HORIZONS:
        raise ValueError("canonical backtest horizons must be exactly 7, 14, and 30 days")
    model = get_model_version(
        session, model_name=model_name, semantic_version=semantic_version
    )
    runs = list(
        session.scalars(
            select(ScrapeRun)
            .where(
                ScrapeRun.workflow == "unpaid_prizes",
                ScrapeRun.status == "success",
                ScrapeRun.is_complete.is_(True),
            )
            .order_by(ScrapeRun.source_observed_at, ScrapeRun.id)
        ).all()
    )
    if not runs:
        raise LookupError("no complete source history available for backtesting")
    snapshots_by_run, snapshots_by_game, baseline_curves = _load_snapshot_history(session)
    first_at = runs[0].source_observed_at
    cutoffs = [
        run
        for run in runs
        if (run.source_observed_at - first_at).total_seconds() >= MINIMUM_PRIOR_DAYS * 86_400
        and (cutoff_start is None or run.source_observed_at >= cutoff_start)
        and (cutoff_end is None or run.source_observed_at <= cutoff_end)
    ]
    parameters = {
        "method_version": BACKTEST_METHOD_VERSION,
        "horizons": list(horizons),
        "minimum_prior_calendar_days": MINIMUM_PRIOR_DAYS,
        "target_tolerance_days": TARGET_TOLERANCE_DAYS,
        "source_first_run_id": runs[0].id,
        "source_last_run_id": runs[-1].id,
        "cutoff_start": cutoff_start.isoformat() if cutoff_start else None,
        "cutoff_end": cutoff_end.isoformat() if cutoff_end else None,
    }
    digest = _json_hash(parameters)
    existing = session.scalar(
        select(AnalyticsBacktestRun).where(
            AnalyticsBacktestRun.model_version_id == model.id,
            AnalyticsBacktestRun.parameters_sha256 == digest,
        )
    )
    if existing is not None and existing.status == "success":
        _reject_model_after_failed_promotion(
            session,
            model_name=model_name,
            semantic_version=semantic_version,
            backtest=existing,
        )
        return _result_for_existing(session, existing)
    now = datetime.now(UTC)
    if existing is None:
        backtest = AnalyticsBacktestRun(
            model_version_id=model.id,
            cutoff_start_at=cutoffs[0].source_observed_at if cutoffs else None,
            cutoff_end_at=cutoffs[-1].source_observed_at if cutoffs else None,
            horizons=list(horizons),
            parameters=parameters,
            parameters_sha256=digest,
            started_at=now,
            status="running",
            aggregate_results={},
            promotion_status="pending",
            promotion_report={},
        )
        session.add(backtest)
        session.flush()
    else:
        backtest = existing
        session.execute(
            delete(AnalyticsBacktestSummary).where(
                AnalyticsBacktestSummary.backtest_run_id == backtest.id
            )
        )
        session.execute(
            delete(AnalyticsBacktestPrediction).where(
                AnalyticsBacktestPrediction.backtest_run_id == backtest.id
            )
        )
        backtest.started_at = now
        backtest.finished_at = None
        backtest.status = "running"
        backtest.error_message = None
        backtest.aggregate_results = {}
        backtest.promotion_status = "pending"
        backtest.promotion_report = {}
    session.flush()

    prediction_rows: list[dict] = []
    latest_lag_audit: dict = {}
    for cutoff in cutoffs:
        cutoff_snapshots = snapshots_by_run.get(cutoff.id, {})
        lag_by_game, lag_audit = _fit_cutoff_lags(
            cutoff, cutoff_snapshots, snapshots_by_game
        )
        latest_lag_audit = lag_audit
        feature_times = [
            observed_at
            for snapshot in cutoff_snapshots.values()
            for observed_at in [snapshot.scrape_run.source_observed_at]
        ]
        feature_times.extend(lag_audit["observation_times"])
        assert_no_lookahead(cutoff.source_observed_at, feature_times)
        frozen = _freeze_cutoff_features(
            cutoff, cutoff_snapshots, lag_by_game, baseline_curves
        )
        for horizon in horizons:
            target = choose_target_run(cutoff, runs, horizon)
            target_snapshots = snapshots_by_run.get(target.id, {}) if target else {}
            for feature in frozen:
                scored, target_snapshot_id = _evaluate_feature(
                    feature,
                    cutoff=cutoff,
                    target=target,
                    target_snapshots=target_snapshots,
                    baseline_curves=baseline_curves,
                )
                prediction_rows.append(
                    _prediction_values(
                        backtest.id,
                        feature,
                        horizon,
                        target,
                        target_snapshot_id,
                        scored,
                    )
                )
        if len(prediction_rows) >= 10_000:
            _insert_prediction_rows(session, prediction_rows)
            session.flush()
            prediction_rows.clear()
    if prediction_rows:
        _insert_prediction_rows(session, prediction_rows)
        session.flush()

    summaries = _build_summaries(session, backtest.id)
    session.add_all(summaries)
    session.flush()
    promotion = _promotion_report(session, backtest.id, latest_lag_audit)
    eligible = session.scalar(
        select(AnalyticsBacktestPrediction.id).where(
            AnalyticsBacktestPrediction.backtest_run_id == backtest.id,
            AnalyticsBacktestPrediction.eligibility_code == "ELIGIBLE",
        ).limit(1)
    )
    prediction_count = session.query(AnalyticsBacktestPrediction).filter_by(
        backtest_run_id=backtest.id
    ).count()
    eligible_count = session.query(AnalyticsBacktestPrediction).filter_by(
        backtest_run_id=backtest.id, eligibility_code="ELIGIBLE"
    ).count()
    backtest.aggregate_results = {
        "cutoff_count": len(cutoffs),
        "prediction_count": prediction_count,
        "eligible_prediction_count": eligible_count,
        "excluded_prediction_count": prediction_count - eligible_count,
        "summary_count": len(summaries),
        "has_eligible_predictions": eligible is not None,
    }
    backtest.promotion_report = promotion
    backtest.promotion_status = "passed" if promotion["passed"] else "failed"
    backtest.status = "success"
    backtest.finished_at = datetime.now(UTC)
    session.flush()
    _reject_model_after_failed_promotion(
        session,
        model_name=model_name,
        semantic_version=semantic_version,
        backtest=backtest,
    )
    return BacktestResult(
        backtest_run_id=backtest.id,
        cutoff_count=len(cutoffs),
        prediction_count=prediction_count,
        eligible_prediction_count=eligible_count,
        excluded_prediction_count=prediction_count - eligible_count,
        summary_count=len(summaries),
        promotion_status=backtest.promotion_status,
        reused=False,
    )


def _reject_model_after_failed_promotion(
    session: Session,
    *,
    model_name: str,
    semantic_version: str,
    backtest: AnalyticsBacktestRun,
) -> None:
    """Fail closed if a newly completed or reused promotion report failed."""
    model = get_model_version(
        session, model_name=model_name, semantic_version=semantic_version
    )
    if backtest.promotion_status != "failed" or (
        model.approval_status == "rejected"
        and model.approval_backtest_run_id == backtest.id
    ):
        return
    reject_model_version(
        session,
        model_name=model_name,
        semantic_version=semantic_version,
        reason=f"Promotion backtest {backtest.id} failed; publication disabled.",
        backtest_run_id=backtest.id,
        decided_at=backtest.finished_at,
    )


def _load_snapshot_history(
    session: Session,
) -> tuple[
    dict[int, dict[int, GameSnapshot]],
    dict[int, list[GameSnapshot]],
    dict[int, list[tuple[datetime, Decimal]]],
]:
    snapshots = session.scalars(
        select(GameSnapshot)
        .join(ScrapeRun, ScrapeRun.id == GameSnapshot.scrape_run_id)
        .where(
            ScrapeRun.workflow == "unpaid_prizes",
            ScrapeRun.status == "success",
            ScrapeRun.is_complete.is_(True),
        )
        .options(
            selectinload(GameSnapshot.prize_tiers),
            selectinload(GameSnapshot.game),
            selectinload(GameSnapshot.scrape_run),
        )
        .order_by(ScrapeRun.source_observed_at, ScrapeRun.id, GameSnapshot.game_id)
    ).all()
    by_run: dict[int, dict[int, GameSnapshot]] = defaultdict(dict)
    by_game: dict[int, list[GameSnapshot]] = defaultdict(list)
    curves: dict[int, list[tuple[datetime, Decimal]]] = defaultdict(list)
    for snapshot in snapshots:
        by_run[snapshot.scrape_run_id][snapshot.game_id] = snapshot
        by_game[snapshot.game_id].append(snapshot)
        fraction = _fraction(snapshot.prize_tiers, maximum=Decimal("500"))
        if fraction is not None:
            curves[snapshot.game_id].append(
                (snapshot.scrape_run.source_observed_at, fraction)
            )
    return dict(by_run), dict(by_game), dict(curves)


def _fit_cutoff_lags(
    cutoff: ScrapeRun,
    cutoff_snapshots: dict[int, GameSnapshot],
    snapshots_by_game: dict[int, list[GameSnapshot]],
) -> tuple[dict[int, Decimal | None], dict]:
    fitted: dict[int, Decimal] = {}
    observation_times: list[datetime] = []
    for game_id, as_of in cutoff_snapshots.items():
        amounts = [tier.prize_amount for tier in as_of.prize_tiers]
        top = max(amounts)
        inputs = [
            TierInput(
                prize_amount=tier.prize_amount,
                original_count=tier.original_count,
                remaining_count=tier.remaining_count,
                is_top_prize=tier.prize_amount == top,
            )
            for tier in as_of.prize_tiers
        ]
        band = select_adaptive_band(
            inputs, target_original_count=PRIMARY_ORIGINAL_TARGET
        )
        if not band.eligible:
            continue
        history = [
            snapshot
            for snapshot in snapshots_by_game.get(game_id, [])
            if snapshot.scrape_run.source_observed_at <= cutoff.source_observed_at
        ]
        if any(
            snapshot.structure_fingerprint != as_of.structure_fingerprint
            for snapshot in history
        ):
            continue
        expected = {tier.prize_amount: tier.original_count for tier in as_of.prize_tiers}
        observations: list[ProgressObservation] = []
        valid = True
        for snapshot in history:
            tiers = _tiers_by_amount(snapshot)
            if set(tiers) != set(expected) or any(
                tiers[amount].original_count != original
                for amount, original in expected.items()
            ):
                valid = False
                break
            low_fraction = _fraction(tiers.values(), maximum=Decimal("500"))
            high_original = sum(tiers[amount].original_count for amount in band.prize_amounts)
            high_remaining = sum(
                tiers[amount].remaining_count for amount in band.prize_amounts
            )
            if low_fraction is None or high_original <= 0:
                valid = False
                break
            observations.append(
                ProgressObservation(
                    observed_at=snapshot.scrape_run.source_observed_at,
                    low_progress=Decimal(1) - low_fraction,
                    high_progress=Decimal(1)
                    - Decimal(high_remaining) / Decimal(high_original),
                )
            )
        if not valid:
            continue
        observation_times.extend(item.observed_at for item in observations)
        result = fit_game_lag(observations)
        if result.status == "available" and result.median_lag_days is not None:
            fitted[game_id] = result.median_lag_days
    global_result = aggregate_global_lag(
        list(fitted.values()), candidate_game_count=len(cutoff_snapshots)
    )
    selected: dict[int, Decimal | None] = {}
    includes_game: dict[int, bool] = {}
    for game_id in cutoff_snapshots:
        lag, includes = leave_one_game_out_lag(fitted, game_id)
        selected[game_id] = lag
        includes_game[game_id] = includes
    maximum_influence = None
    if global_result.median_lag_days is not None and fitted:
        influences = []
        for game_id in fitted:
            loo, _ = leave_one_game_out_lag(fitted, game_id, minimum_games=1)
            if loo is not None:
                influences.append(abs(loo - global_result.median_lag_days))
        maximum_influence = max(influences, default=Decimal(0))
    return selected, {
        "candidate_game_count": len(cutoff_snapshots),
        "primary_qualified_game_count": len(fitted),
        "positive_game_count": sum(value > 0 for value in fitted.values()),
        "global_median_lag_days": global_result.median_lag_days,
        "bootstrap_lower_lag_days": global_result.bootstrap_lower_lag_days,
        "bootstrap_upper_lag_days": global_result.bootstrap_upper_lag_days,
        "maximum_leave_one_out_influence_days": maximum_influence,
        "lag_includes_scored_game": includes_game,
        "observation_times": observation_times,
    }


def _freeze_cutoff_features(
    cutoff: ScrapeRun,
    snapshots: dict[int, GameSnapshot],
    lag_by_game: dict[int, Decimal | None],
    baseline_curves: dict[int, list[tuple[datetime, Decimal]]],
) -> list[FrozenFeature]:
    features: list[FrozenFeature] = []
    for game_id, snapshot in snapshots.items():
        tiers = _tiers_by_amount(snapshot)
        baseline = _fraction(tiers.values(), maximum=Decimal("500"))
        legacy = _fraction(tiers.values())
        lag = lag_by_game.get(game_id)
        lagged = None
        if lag is not None:
            curve = _curve_as_of(baseline_curves.get(game_id, []), cutoff.source_observed_at)
            lagged = interpolate_curve_at_time(
                curve, subtract_decimal_days(cutoff.source_observed_at, lag)
            )
        max_amount = max(tiers)
        for amount, tier in tiers.items():
            group = classify_prize_group(amount)
            aligned = _regular_reference(tiers, amount) if group == "baseline" else baseline
            if group == "high":
                aligned = lagged
            reference_for_label = aligned
            confidence = (
                classify_confidence(tier.original_count, reference_for_label)
                if reference_for_label is not None
                else None
            )
            cohort = _cohort(tier, reference_for_label, confidence)
            variants: tuple[Variant, ...] = (
                ("aligned", "no_lag", "legacy")
                if group == "high"
                else ("aligned", "legacy")
            )
            for variant in variants:
                reference = aligned
                if variant == "no_lag":
                    reference = baseline
                elif variant == "legacy":
                    reference = legacy
                exclusion = None if reference is not None else "CUTOFF_REFERENCE_UNAVAILABLE"
                features.append(
                    FrozenFeature(
                        cutoff_scrape_run_id=cutoff.id,
                        game_id=game_id,
                        cutoff_game_snapshot_id=snapshot.id,
                        cutoff_structure_fingerprint=snapshot.structure_fingerprint,
                        prize_amount=amount,
                        original_count=tier.original_count,
                        cutoff_remaining_count=tier.remaining_count,
                        process_group=group,
                        model_variant=variant,
                        cutoff_reference_fraction=reference,
                        lag_days=lag if variant == "aligned" and group == "high" else None,
                        confidence_label=confidence,
                        evidence_cohort=cohort,
                        ticket_price_group=_ticket_price_group(snapshot.game.ticket_price),
                        cutoff_inputs={
                            "cutoff_observed_at": cutoff.source_observed_at.isoformat(),
                            "cutoff_reference_fraction": _json_decimal(reference),
                            "lag_days": _json_decimal(lag),
                            "overall_odds_one_in": _json_decimal(
                                snapshot.game.overall_odds_one_in
                            ),
                            "is_top_prize": amount == max_amount,
                        },
                        exclusion_code=exclusion,
                    )
                )
    return features


def _evaluate_feature(
    feature: FrozenFeature,
    *,
    cutoff: ScrapeRun,
    target: ScrapeRun | None,
    target_snapshots: dict[int, GameSnapshot],
    baseline_curves: dict[int, list[tuple[datetime, Decimal]]],
) -> tuple[PredictionResult, int | None]:
    if feature.exclusion_code is not None:
        return _excluded_result(feature.exclusion_code), None
    if target is None:
        return _excluded_result("TARGET_DATE_MISSING"), None
    snapshot = target_snapshots.get(feature.game_id)
    if snapshot is None:
        return _excluded_result("TARGET_GAME_MISSING"), None
    if snapshot.structure_fingerprint != feature.cutoff_structure_fingerprint:
        return _excluded_result("STRUCTURE_CHANGED"), snapshot.id
    tiers = _tiers_by_amount(snapshot)
    target_tier = tiers.get(feature.prize_amount)
    if target_tier is None or target_tier.original_count != feature.original_count:
        return _excluded_result("TARGET_TIER_MISSING"), snapshot.id
    target_reference: Decimal | None
    if feature.model_variant == "legacy":
        target_reference = _fraction(tiers.values())
    elif feature.model_variant == "no_lag":
        target_reference = _fraction(tiers.values(), maximum=Decimal("500"))
    elif feature.process_group == "baseline":
        target_reference = _regular_reference(tiers, feature.prize_amount)
    elif feature.process_group == "retail_gap":
        target_reference = _fraction(tiers.values(), maximum=Decimal("500"))
    else:
        if feature.lag_days is None:
            return _excluded_result("LAG_NOT_AVAILABLE"), snapshot.id
        curve = _curve_as_of(
            baseline_curves.get(feature.game_id, []), target.source_observed_at
        )
        target_reference = interpolate_curve_at_time(
            curve, subtract_decimal_days(target.source_observed_at, feature.lag_days)
        )
    if target_reference is None or feature.cutoff_reference_fraction is None:
        return _excluded_result("TARGET_REFERENCE_UNAVAILABLE"), snapshot.id
    prediction = conditional_depletion_prediction(
        cutoff_remaining_count=feature.cutoff_remaining_count,
        original_count=feature.original_count,
        cutoff_reference_fraction=feature.cutoff_reference_fraction,
        target_reference_fraction=target_reference,
    )
    return (
        score_observation(
            prediction,
            target_tier.remaining_count,
            original_count=feature.original_count,
        ),
        snapshot.id,
    )


def _prediction_values(
    backtest_run_id: int,
    feature: FrozenFeature,
    horizon: int,
    target: ScrapeRun | None,
    target_snapshot_id: int | None,
    result: PredictionResult,
) -> dict:
    return {
        "backtest_run_id": backtest_run_id,
        "cutoff_scrape_run_id": feature.cutoff_scrape_run_id,
        "target_scrape_run_id": target.id if target else None,
        "game_id": feature.game_id,
        "cutoff_game_snapshot_id": feature.cutoff_game_snapshot_id,
        "target_game_snapshot_id": target_snapshot_id,
        "prize_amount": feature.prize_amount,
        "original_count": feature.original_count,
        "cutoff_remaining_count": feature.cutoff_remaining_count,
        "horizon_days": horizon,
        "model_variant": feature.model_variant,
        "process_group": feature.process_group,
        "confidence_label": feature.confidence_label,
        "ticket_price_group": feature.ticket_price_group,
        "evidence_cohort": feature.evidence_cohort,
        "cutoff_inputs": feature.cutoff_inputs,
        "predicted_remaining_count": result.predicted_count,
        "predicted_remaining_fraction": result.predicted_fraction,
        "prediction_lower_count": result.lower_count,
        "prediction_upper_count": result.upper_count,
        "observed_remaining_count": result.observed_count,
        "observed_remaining_fraction": result.observed_fraction,
        "signed_count_error": result.signed_count_error,
        "absolute_count_error": result.absolute_count_error,
        "signed_fraction_error": result.signed_fraction_error,
        "absolute_fraction_error": result.absolute_fraction_error,
        "standardized_error": result.standardized_error,
        "interval_contains_observed": result.interval_contains_observed,
        "eligibility_code": result.eligibility_code,
    }


def _insert_prediction_rows(session: Session, rows: list[dict]) -> None:
    """Use PostgreSQL COPY for the large immutable prediction fact set."""
    if not rows:
        return
    if session.bind is None or session.bind.dialect.name != "postgresql":
        session.execute(insert(AnalyticsBacktestPrediction), rows)
        return
    from psycopg.types.json import Jsonb

    columns = list(rows[0])
    statement = (
        "COPY analytics_backtest_predictions ("
        + ", ".join(columns)
        + ") FROM STDIN"
    )
    driver_connection = session.connection().connection.driver_connection
    with driver_connection.cursor().copy(statement) as copy:
        for row in rows:
            values = [
                Jsonb(row[column]) if column == "cutoff_inputs" else row[column]
                for column in columns
            ]
            copy.write_row(values)


def _build_summaries(
    session: Session, backtest_run_id: int
) -> list[AnalyticsBacktestSummary]:
    rows = list(
        session.scalars(
            select(AnalyticsBacktestPrediction).where(
                AnalyticsBacktestPrediction.backtest_run_id == backtest_run_id,
                AnalyticsBacktestPrediction.eligibility_code == "ELIGIBLE",
            )
        ).all()
    )
    grouped: dict[tuple[int, str, str, str], list[AnalyticsBacktestPrediction]] = (
        defaultdict(list)
    )
    for row in rows:
        dimensions = {
            "all": "all",
            "process_group": row.process_group,
            "confidence": row.confidence_label or "unavailable",
            "ticket_price": row.ticket_price_group,
            "evidence": row.evidence_cohort,
        }
        for dimension, value in dimensions.items():
            grouped[(row.horizon_days, row.model_variant, dimension, value)].append(row)
    no_lag_by_identity = {
        _prediction_identity(row): row
        for row in rows
        if row.model_variant == "no_lag"
    }
    summaries = []
    for (horizon, variant, dimension, value), members in sorted(grouped.items()):
        mae = _mean([member.absolute_count_error for member in members])
        paired_no_lag = [
            no_lag_by_identity[_prediction_identity(member)]
            for member in members
            if member.model_variant == "aligned"
            and _prediction_identity(member) in no_lag_by_identity
        ]
        baseline_mae = _mean(
            [member.absolute_count_error for member in paired_no_lag]
        )
        improvement = (
            (baseline_mae - mae) / baseline_mae
            if variant == "aligned" and baseline_mae not in (None, Decimal(0))
            else None
        )
        summaries.append(
            AnalyticsBacktestSummary(
                backtest_run_id=backtest_run_id,
                horizon_days=horizon,
                model_variant=variant,
                grouping_dimension=dimension,
                group_value=value,
                eligible_prediction_count=len(members),
                unique_game_count=len({member.game_id for member in members}),
                unique_tier_count=len(
                    {(member.game_id, member.prize_amount) for member in members}
                ),
                mean_absolute_count_error=mae,
                median_absolute_count_error=_median(
                    [member.absolute_count_error for member in members]
                ),
                median_bias_count=_median(
                    [member.signed_count_error for member in members]
                ),
                mean_absolute_fraction_error=_mean(
                    [member.absolute_fraction_error for member in members]
                ),
                median_absolute_fraction_error=_median(
                    [member.absolute_fraction_error for member in members]
                ),
                median_bias_fraction=_median(
                    [member.signed_fraction_error for member in members]
                ),
                median_absolute_standardized_error=_median(
                    [abs(member.standardized_error) for member in members]
                ),
                interval_coverage=(
                    Decimal(sum(bool(member.interval_contains_observed) for member in members))
                    / Decimal(len(members))
                ),
                improvement_vs_no_lag=improvement,
            )
        )
    return summaries


def _promotion_report(session: Session, backtest_run_id: int, lag: dict) -> dict:
    checks: list[dict] = []

    def add(code: str, passed: bool, value, requirement: str) -> None:
        checks.append(
            {
                "code": code,
                "passed": passed,
                "value": _json_decimal(value),
                "requirement": requirement,
            }
        )

    qualified = lag.get("primary_qualified_game_count", 0)
    positive = lag.get("positive_game_count", 0)
    add("LAG_PRIMARY_GAMES", qualified >= 8, qualified, ">= 8")
    positive_share = Decimal(positive) / Decimal(qualified) if qualified else Decimal(0)
    add("LAG_POSITIVE_SHARE", positive_share >= Decimal("0.8"), positive_share, ">= 0.8")
    bootstrap_lower = lag.get("bootstrap_lower_lag_days")
    add(
        "LAG_BOOTSTRAP_LOWER_POSITIVE",
        bootstrap_lower is not None and bootstrap_lower > 0,
        bootstrap_lower,
        "> 0 days",
    )
    influence = lag.get("maximum_leave_one_out_influence_days")
    add(
        "LAG_MAX_GAME_INFLUENCE",
        influence is not None and influence <= 7,
        influence,
        "<= 7 days",
    )
    high_rows = list(
        session.scalars(
            select(AnalyticsBacktestSummary).where(
                AnalyticsBacktestSummary.backtest_run_id == backtest_run_id,
                AnalyticsBacktestSummary.model_variant == "aligned",
                AnalyticsBacktestSummary.grouping_dimension == "process_group",
                AnalyticsBacktestSummary.group_value == "high",
            )
        ).all()
    )
    by_horizon = {row.horizon_days: row.improvement_vs_no_lag for row in high_rows}
    paired_predictions = list(
        session.scalars(
            select(AnalyticsBacktestPrediction).where(
                AnalyticsBacktestPrediction.backtest_run_id == backtest_run_id,
                AnalyticsBacktestPrediction.process_group == "high",
                AnalyticsBacktestPrediction.model_variant.in_(("aligned", "no_lag")),
                AnalyticsBacktestPrediction.eligibility_code == "ELIGIBLE",
            )
        ).all()
    )
    no_lag = {
        _prediction_identity(row): row
        for row in paired_predictions
        if row.model_variant == "no_lag"
    }
    aligned = [
        row
        for row in paired_predictions
        if row.model_variant == "aligned" and _prediction_identity(row) in no_lag
    ]
    aligned_median = _median([row.absolute_fraction_error for row in aligned])
    no_lag_median = _median(
        [no_lag[_prediction_identity(row)].absolute_fraction_error for row in aligned]
    )
    median_improvement = (
        (no_lag_median - aligned_median) / no_lag_median
        if aligned_median is not None and no_lag_median not in (None, Decimal(0))
        else None
    )
    add(
        "LAG_HELD_OUT_IMPROVEMENT",
        median_improvement is not None and median_improvement >= Decimal("0.1"),
        median_improvement,
        ">= 0.1 median MAE improvement",
    )
    for horizon in (14, 30):
        value = by_horizon.get(horizon)
        add(
            f"LAG_HORIZON_{horizon}_NONNEGATIVE",
            value is not None and value >= 0,
            value,
            ">= 0",
        )
    eligible_count = session.query(AnalyticsBacktestPrediction).filter_by(
        backtest_run_id=backtest_run_id, eligibility_code="ELIGIBLE"
    ).count()
    add("RESULT_TABLES_PERSISTED", eligible_count > 0, eligible_count, "> 0")
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "note": "Failure preserves experimental results; thresholds require a new model version.",
    }


def _tiers_by_amount(snapshot: GameSnapshot) -> dict[Decimal, PrizeTierSnapshot]:
    return {tier.prize_amount: tier for tier in snapshot.prize_tiers}


def _prediction_identity(row: AnalyticsBacktestPrediction) -> tuple:
    return (
        row.horizon_days,
        row.cutoff_scrape_run_id,
        row.game_id,
        row.prize_amount,
    )


def _curve_as_of(
    curve: list[tuple[datetime, Decimal]], observed_at: datetime
) -> list[tuple[datetime, Decimal]]:
    return [point for point in curve if point[0] <= observed_at]


def _fraction(
    tiers, *, maximum: Decimal | None = None, exclude: Decimal | None = None
) -> Decimal | None:
    selected = [
        tier
        for tier in tiers
        if (maximum is None or tier.prize_amount <= maximum)
        and (exclude is None or tier.prize_amount != exclude)
    ]
    original = sum(tier.original_count for tier in selected)
    if not selected or original <= 0:
        return None
    return Decimal(sum(tier.remaining_count for tier in selected)) / Decimal(original)


def _regular_reference(
    tiers: dict[Decimal, PrizeTierSnapshot], amount: Decimal
) -> Decimal | None:
    return _fraction(tiers.values(), maximum=Decimal("500"), exclude=amount)


def _cohort(
    tier: PrizeTierSnapshot, reference: Decimal | None, confidence: str | None
) -> str:
    if reference is None:
        return "unavailable"
    interval = wilson_availability_interval(
        claimed_count=tier.claimed_count,
        original_count=tier.original_count,
        reference_remaining_fraction=reference,
    )
    availability = (
        Decimal(tier.remaining_count) / Decimal(tier.original_count) / reference
    )
    return classify_evidence(
        interval=interval,
        sensitivity_availabilities=[availability],
        confidence=confidence,
    )


def _ticket_price_group(price: Decimal | None) -> str:
    if price is None:
        return "unknown"
    if price <= 2:
        return "$1-$2"
    if price <= 5:
        return "$3-$5"
    if price <= 10:
        return "$10"
    if price <= 20:
        return "$20"
    return "$30+"


def _excluded_result(code: str) -> PredictionResult:
    return PredictionResult(
        predicted_count=None,
        predicted_fraction=None,
        lower_count=None,
        upper_count=None,
        observed_count=None,
        observed_fraction=None,
        signed_count_error=None,
        absolute_count_error=None,
        signed_fraction_error=None,
        absolute_fraction_error=None,
        standardized_error=None,
        interval_contains_observed=None,
        eligibility_code=code,
    )


def _median(values) -> Decimal | None:
    valid = sorted(value for value in values if value is not None)
    if not valid:
        return None
    middle = len(valid) // 2
    if len(valid) % 2:
        return valid[middle]
    return (valid[middle - 1] + valid[middle]) / Decimal(2)


def _mean(values) -> Decimal | None:
    valid = [value for value in values if value is not None]
    return sum(valid, Decimal(0)) / Decimal(len(valid)) if valid else None


def _json_decimal(value):
    return str(value) if isinstance(value, Decimal) else value


def _json_hash(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _result_for_existing(
    session: Session, backtest: AnalyticsBacktestRun
) -> BacktestResult:
    aggregate = backtest.aggregate_results
    return BacktestResult(
        backtest_run_id=backtest.id,
        cutoff_count=aggregate.get("cutoff_count", 0),
        prediction_count=aggregate.get("prediction_count", 0),
        eligible_prediction_count=aggregate.get("eligible_prediction_count", 0),
        excluded_prediction_count=aggregate.get("excluded_prediction_count", 0),
        summary_count=session.query(AnalyticsBacktestSummary).filter_by(
            backtest_run_id=backtest.id
        ).count(),
        promotion_status=backtest.promotion_status,
        reused=True,
    )
