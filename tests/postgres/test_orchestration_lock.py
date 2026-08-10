from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from illinois_lottery_tracker.analytics.status import build_nightly_status
from illinois_lottery_tracker.pipeline import orchestration_lock


def test_postgresql_advisory_lock_allows_one_worker_and_one_clean_skip():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")

    with orchestration_lock(engine) as first:
        with orchestration_lock(engine) as concurrent:
            assert first is True
            assert concurrent is False
    with orchestration_lock(engine) as after_release:
        assert after_release is True
    engine.dispose()


def test_nightly_status_exposes_required_operational_sections():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    with Session(engine) as session:
        document = build_nightly_status(session)

    assert set(document) == {
        "generated_at",
        "source",
        "catalog",
        "metadata_misses",
        "analytics",
        "quality_issues",
        "invariant_failures",
        "ranking_status",
        "raw_archive",
        "stage_durations_seconds",
        "protection",
        "alerts",
    }
    assert {"backup_age_hours", "last_verified_restore_age_days"} <= set(
        document["protection"]
    )
    engine.dispose()
