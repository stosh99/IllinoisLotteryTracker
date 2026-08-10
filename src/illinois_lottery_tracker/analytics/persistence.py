"""Idempotent persistence scaffolding for versioned analytics executions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..analytics_models import (
    AnalyticsBacktestRun,
    AnalyticsGameMetric,
    AnalyticsLagCalibration,
    AnalyticsLagGameEstimate,
    AnalyticsModelVersion,
    AnalyticsQualityIssue,
    AnalyticsRun,
    AnalyticsStrategyMetric,
    AnalyticsTierMetric,
)
from ..models import ScrapeRun

MODEL_NAME = "core_ticket_model"
MODEL_VERSION = "1.0.0"
MODEL_PARAMETERS = {
    "baseline_max_prize": 500,
    "bootstrap_samples": 10000,
    "bootstrap_seed": 20260808,
    "confidence_information_high_boundary": 25,
    "confidence_information_low_boundary": 5,
    "confidence_information_moderate_boundary": 10,
    "confidence_min_tier_n": 20,
    "high_prize_strictly_greater_than": 600,
    "lag_exploratory_original_count": 250,
    "lag_internal_quantiles": 9,
    "lag_max_interpolation_gap_days": 3,
    "lag_min_global_games": 8,
    "lag_min_overlap_fraction": 0.075,
    "lag_min_snapshots": 30,
    "lag_min_span_days": 30,
    "lag_primary_original_count": 500,
    "reference_min_original_count": 10000,
    "source_fresh_hours": 36,
    "source_stale_error_hours": 72,
    "wilson_z": 1.959963984540054,
}


@dataclass(frozen=True)
class AnalyticsRunAcquisition:
    run: AnalyticsRun
    created: bool
    retrying_failed: bool


@dataclass(frozen=True)
class AnalyticsChildCounts:
    games: int
    tiers: int
    strategies: int
    issues: int


def canonical_model_parameters_json() -> str:
    return json.dumps(MODEL_PARAMETERS, sort_keys=True, separators=(",", ":"))


def model_parameters_sha256() -> str:
    return hashlib.sha256(canonical_model_parameters_json().encode()).hexdigest()


def get_model_version(
    session: Session,
    *,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
) -> AnalyticsModelVersion:
    version = session.scalar(
        select(AnalyticsModelVersion).where(
            AnalyticsModelVersion.model_name == model_name,
            AnalyticsModelVersion.semantic_version == semantic_version,
        )
    )
    if version is None:
        raise LookupError(f"analytics model version not found: {model_name} {semantic_version}")
    if model_name == MODEL_NAME and semantic_version == MODEL_VERSION:
        if version.parameters_sha256 != model_parameters_sha256():
            raise RuntimeError("seeded model parameter hash does not match application model")
    return version


def model_is_approved(session: Session, model_version_id: int) -> bool:
    return bool(
        session.scalar(
            select(AnalyticsModelVersion.approval_status).where(
                AnalyticsModelVersion.id == model_version_id
            )
        )
        == "approved"
    )


def approve_model_version(
    session: Session,
    *,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
    reason: str,
    backtest_run_id: int | None = None,
    decided_at: datetime | None = None,
) -> AnalyticsModelVersion:
    """Approve one model only with a persisted successful promotion backtest."""
    if not reason.strip():
        raise ValueError("model approval requires a nonempty reason")
    model = get_model_version(
        session, model_name=model_name, semantic_version=semantic_version
    )
    statement = select(AnalyticsBacktestRun).where(
        AnalyticsBacktestRun.model_version_id == model.id,
        AnalyticsBacktestRun.status == "success",
        AnalyticsBacktestRun.promotion_status == "passed",
    )
    if backtest_run_id is not None:
        statement = statement.where(AnalyticsBacktestRun.id == backtest_run_id)
    backtest = session.scalar(
        statement.order_by(
            AnalyticsBacktestRun.finished_at.desc(), AnalyticsBacktestRun.id.desc()
        )
    )
    if backtest is None:
        raise ValueError("model approval requires a successful passed promotion backtest")
    model.approval_status = "approved"
    model.approval_backtest_run_id = backtest.id
    model.approval_decided_at = (decided_at or datetime.now(UTC)).astimezone(UTC)
    model.approval_reason = reason.strip()
    session.flush()
    return model


def reject_model_version(
    session: Session,
    *,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
    reason: str,
    backtest_run_id: int | None = None,
    decided_at: datetime | None = None,
) -> AnalyticsModelVersion:
    if not reason.strip():
        raise ValueError("model rejection requires a nonempty reason")
    model = get_model_version(
        session, model_name=model_name, semantic_version=semantic_version
    )
    if backtest_run_id is not None:
        backtest = session.get(AnalyticsBacktestRun, backtest_run_id)
        if backtest is None or backtest.model_version_id != model.id:
            raise ValueError("rejection backtest does not belong to the model version")
    model.approval_status = "rejected"
    model.approval_backtest_run_id = backtest_run_id
    model.approval_decided_at = (decided_at or datetime.now(UTC)).astimezone(UTC)
    model.approval_reason = reason.strip()
    session.flush()
    return model


def acquire_analytics_run(
    session: Session,
    *,
    as_of_scrape_run_id: int,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
    started_at: datetime | None = None,
) -> AnalyticsRunAcquisition:
    """Create once, reuse running/success, and reset a failed run for retry."""
    model = get_model_version(
        session, model_name=model_name, semantic_version=semantic_version
    )
    source = session.get(ScrapeRun, as_of_scrape_run_id)
    if (
        source is None
        or source.workflow != "unpaid_prizes"
        or source.status != "success"
        or not source.is_complete
        or source.source_observed_at is None
    ):
        raise ValueError("analytics cutoff must be a complete successful unpaid-prizes run")
    existing = session.scalar(
        select(AnalyticsRun).where(
            AnalyticsRun.model_version_id == model.id,
            AnalyticsRun.as_of_scrape_run_id == source.id,
        )
    )
    now = (started_at or datetime.now(UTC)).astimezone(UTC)
    if existing is not None:
        if existing.status == "failed":
            existing.status = "running"
            existing.publishable = False
            existing.error_message = None
            existing.started_at = now
            existing.finished_at = None
            session.flush()
            return AnalyticsRunAcquisition(existing, created=False, retrying_failed=True)
        return AnalyticsRunAcquisition(existing, created=False, retrying_failed=False)
    run = AnalyticsRun(
        model_version_id=model.id,
        as_of_scrape_run_id=source.id,
        as_of_observed_at=source.source_observed_at,
        started_at=now,
        status="running",
        publishable=False,
    )
    session.add(run)
    session.flush()
    return AnalyticsRunAcquisition(run, created=True, retrying_failed=False)


def add_quality_issue_once(
    session: Session,
    *,
    analytics_run_id: int,
    code: str,
    severity: str,
    entity_type: str,
    message: str,
    details: dict | None = None,
    game_id: int | None = None,
    game_snapshot_id: int | None = None,
    prize_tier_snapshot_id: int | None = None,
) -> tuple[AnalyticsQualityIssue, bool]:
    existing = session.scalar(
        select(AnalyticsQualityIssue).where(
            AnalyticsQualityIssue.analytics_run_id == analytics_run_id,
            AnalyticsQualityIssue.code == code,
            AnalyticsQualityIssue.entity_type == entity_type,
            AnalyticsQualityIssue.game_id.is_(game_id)
            if game_id is None
            else AnalyticsQualityIssue.game_id == game_id,
            AnalyticsQualityIssue.game_snapshot_id.is_(game_snapshot_id)
            if game_snapshot_id is None
            else AnalyticsQualityIssue.game_snapshot_id == game_snapshot_id,
            AnalyticsQualityIssue.prize_tier_snapshot_id.is_(prize_tier_snapshot_id)
            if prize_tier_snapshot_id is None
            else AnalyticsQualityIssue.prize_tier_snapshot_id
            == prize_tier_snapshot_id,
        )
    )
    if existing is not None:
        return existing, False
    issue = AnalyticsQualityIssue(
        analytics_run_id=analytics_run_id,
        code=code,
        severity=severity,
        entity_type=entity_type,
        game_id=game_id,
        game_snapshot_id=game_snapshot_id,
        prize_tier_snapshot_id=prize_tier_snapshot_id,
        message=message,
        details=details or {},
    )
    session.add(issue)
    session.flush()
    return issue, True


def clear_retryable_run_children(session: Session, run: AnalyticsRun) -> None:
    if run.status == "success":
        raise ValueError("successful analytics runs are immutable")
    for model in (
        AnalyticsQualityIssue,
        AnalyticsStrategyMetric,
        AnalyticsTierMetric,
        AnalyticsGameMetric,
        AnalyticsLagGameEstimate,
        AnalyticsLagCalibration,
    ):
        session.execute(delete(model).where(model.analytics_run_id == run.id))
    session.flush()


def analytics_child_counts(session: Session, run_id: int) -> AnalyticsChildCounts:
    def count(model) -> int:
        return session.scalar(
            select(func.count()).select_from(model).where(model.analytics_run_id == run_id)
        ) or 0

    return AnalyticsChildCounts(
        games=count(AnalyticsGameMetric),
        tiers=count(AnalyticsTierMetric),
        strategies=count(AnalyticsStrategyMetric),
        issues=count(AnalyticsQualityIssue),
    )


def mark_analytics_run_success(
    session: Session,
    run: AnalyticsRun,
    *,
    publishable: bool,
    finished_at: datetime | None = None,
) -> None:
    if run.status == "success":
        if run.publishable != publishable:
            raise ValueError("successful analytics runs are immutable")
        return
    if run.status != "running":
        raise ValueError(f"cannot succeed analytics run in status {run.status}")
    run.status = "success"
    run.publishable = publishable
    run.finished_at = (finished_at or datetime.now(UTC)).astimezone(UTC)
    run.error_message = None
    session.flush()


def mark_analytics_run_failed(
    session: Session,
    run: AnalyticsRun,
    *,
    error_message: str,
    finished_at: datetime | None = None,
) -> None:
    if run.status == "success":
        raise ValueError("successful analytics runs are immutable")
    run.status = "failed"
    run.publishable = False
    run.error_message = error_message
    run.finished_at = (finished_at or datetime.now(UTC)).astimezone(UTC)
    session.flush()


def publish_staged_analytics_run(
    session: Session,
    run: AnalyticsRun,
    *,
    finished_at: datetime | None = None,
    publication_gates_passed: bool = True,
) -> bool:
    """Complete a staged run and publish only for an explicitly approved model."""
    approved = model_is_approved(session, run.model_version_id)
    publishable = approved and publication_gates_passed
    if run.status == "success" and run.publishable:
        return approved and publication_gates_passed
    if run.status not in {"running", "success"}:
        raise ValueError(f"cannot publish analytics run in status {run.status}")
    run.status = "success"
    run.publishable = publishable
    run.finished_at = (finished_at or datetime.now(UTC)).astimezone(UTC)
    run.error_message = None
    session.flush()
    return publishable
