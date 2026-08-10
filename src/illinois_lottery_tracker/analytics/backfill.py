"""Cutoff-ordered, one-transaction-per-cutoff analytics backfill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..analytics_models import AnalyticsRun
from ..models import ScrapeRun
from .persistence import (
    MODEL_NAME,
    MODEL_VERSION,
    acquire_analytics_run,
    get_model_version,
    mark_analytics_run_failed,
)
from .service import (
    calibrate_claim_lag,
    compute_regular_analytics,
    finalize_high_tier_analytics,
)


@dataclass(frozen=True)
class BackfillSummary:
    requested: int
    attempted: int
    succeeded: int
    failed: int
    skipped: int
    failed_cutoffs: tuple[int, ...]


def backfill_analytics(
    session_factory: sessionmaker[Session],
    *,
    model_name: str = MODEL_NAME,
    semantic_version: str = MODEL_VERSION,
    from_source_date: date | None = None,
    to_source_date: date | None = None,
    resume: bool = False,
    force: bool = False,
    dry_run: bool = False,
    compute_cutoff_fn=None,
) -> BackfillSummary:
    """Process complete source cutoffs in source order and commit individually."""
    with session_factory() as discovery:
        statement = (
            select(ScrapeRun.id)
            .where(
                ScrapeRun.workflow == "unpaid_prizes",
                ScrapeRun.status == "success",
                ScrapeRun.is_complete.is_(True),
            )
            .order_by(ScrapeRun.source_observed_at, ScrapeRun.id)
        )
        if from_source_date is not None:
            statement = statement.where(ScrapeRun.source_date >= from_source_date)
        if to_source_date is not None:
            statement = statement.where(ScrapeRun.source_date <= to_source_date)
        cutoff_ids = list(discovery.scalars(statement).all())
        model_id = get_model_version(
            discovery, model_name=model_name, semantic_version=semantic_version
        ).id

    attempted = succeeded = failed = skipped = 0
    failed_cutoffs: list[int] = []
    for cutoff_id in cutoff_ids:
        with session_factory(expire_on_commit=False) as session:
            existing = session.scalar(
                select(AnalyticsRun).where(
                    AnalyticsRun.model_version_id == model_id,
                    AnalyticsRun.as_of_scrape_run_id == cutoff_id,
                )
            )
            if existing is not None and existing.status == "success":
                skipped += 1
                continue
            if existing is not None and existing.status == "failed" and not (resume or force):
                skipped += 1
                continue
            attempted += 1
            try:
                if compute_cutoff_fn is None:
                    compute_regular_analytics(
                        session,
                        scrape_run_id=cutoff_id,
                        model_name=model_name,
                        semantic_version=semantic_version,
                    )
                    calibrate_claim_lag(
                        session,
                        scrape_run_id=cutoff_id,
                        model_name=model_name,
                        semantic_version=semantic_version,
                    )
                    finalize_high_tier_analytics(
                        session,
                        scrape_run_id=cutoff_id,
                        model_name=model_name,
                        semantic_version=semantic_version,
                    )
                else:
                    compute_cutoff_fn(session, cutoff_id)
                if dry_run:
                    session.rollback()
                else:
                    session.commit()
                succeeded += 1
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                failed += 1
                failed_cutoffs.append(cutoff_id)
                if not dry_run:
                    failure = acquire_analytics_run(
                        session,
                        as_of_scrape_run_id=cutoff_id,
                        model_name=model_name,
                        semantic_version=semantic_version,
                    ).run
                    mark_analytics_run_failed(session, failure, error_message=str(exc))
                    session.commit()
    return BackfillSummary(
        requested=len(cutoff_ids),
        attempted=attempted,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        failed_cutoffs=tuple(failed_cutoffs),
    )
