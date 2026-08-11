from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.analytics.backfill import backfill_analytics
from illinois_lottery_tracker.analytics.persistence import (
    MODEL_NAME,
    MODEL_PARAMETERS,
    MODEL_VERSION,
    acquire_analytics_run,
    mark_analytics_run_success,
    model_parameters_sha256,
)
from illinois_lottery_tracker.analytics_models import AnalyticsModelVersion
from illinois_lottery_tracker.models import Base, ScrapeRun


def test_backfill_resumes_only_failed_cutoff_and_commits_each_success(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'backfill.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        session.add(
            AnalyticsModelVersion(
                model_name=MODEL_NAME,
                semantic_version=MODEL_VERSION,
                parameters=MODEL_PARAMETERS,
                parameters_sha256=model_parameters_sha256(),
                code_version="test",
            )
        )
        start = datetime(2026, 1, 1, 12, tzinfo=UTC)
        for day in range(3):
            observed = start + timedelta(days=day)
            session.add(
                ScrapeRun(
                    started_at=observed,
                    finished_at=observed,
                    status="success",
                    workflow="unpaid_prizes",
                    source_observed_at=observed,
                    source_date=observed.date(),
                    source_sha256=f"{day + 1:064x}",
                    is_complete=True,
                    parsed_game_count=1,
                    parsed_prize_tier_count=1,
                    pipeline_version="test",
                )
            )
        session.commit()

    failed_once: set[int] = set()

    def injected(session: Session, cutoff_id: int) -> None:
        run = acquire_analytics_run(session, as_of_scrape_run_id=cutoff_id).run
        if cutoff_id == 2 and cutoff_id not in failed_once:
            failed_once.add(cutoff_id)
            raise RuntimeError("injected cutoff failure")
        mark_analytics_run_success(session, run)

    first = backfill_analytics(factory, compute_cutoff_fn=injected)
    resumed = backfill_analytics(factory, resume=True, compute_cutoff_fn=injected)

    assert first.requested == 3
    assert first.succeeded == 2
    assert first.failed_cutoffs == (2,)
    assert resumed.attempted == 1
    assert resumed.succeeded == 1
    assert resumed.failed == 0
    assert resumed.skipped == 2


def test_backfill_without_resume_skips_failed_cutoff(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'skip.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        session.add(
            AnalyticsModelVersion(
                model_name=MODEL_NAME,
                semantic_version=MODEL_VERSION,
                parameters=MODEL_PARAMETERS,
                parameters_sha256=model_parameters_sha256(),
                code_version="test",
            )
        )
        observed = datetime(2026, 1, 1, 12, tzinfo=UTC)
        session.add(
            ScrapeRun(
                started_at=observed,
                finished_at=observed,
                status="success",
                workflow="unpaid_prizes",
                source_observed_at=observed,
                source_date=observed.date(),
                source_sha256="e" * 64,
                is_complete=True,
                parsed_game_count=1,
                parsed_prize_tier_count=1,
                pipeline_version="test",
            )
        )
        session.commit()

    first = backfill_analytics(
        factory,
        compute_cutoff_fn=lambda _session, _cutoff: (_ for _ in ()).throw(
            RuntimeError("injected")
        ),
    )
    second = backfill_analytics(factory, compute_cutoff_fn=lambda *_args: None)

    assert first.failed == 1
    assert second.attempted == 0
    assert second.skipped == 1
