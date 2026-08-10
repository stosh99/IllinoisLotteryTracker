"""Rank only complete metrics in the current source/catalog intersection."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text


def _approve_model(connection, observed: datetime, suffix: str) -> int:
    model_id = connection.execute(
        text("SELECT id FROM analytics_model_versions")
    ).scalar_one()
    backtest_id = connection.execute(
        text(
            """
            INSERT INTO analytics_backtest_runs (
              model_version_id, horizons, parameters, parameters_sha256,
              started_at, finished_at, status, aggregate_results,
              promotion_status, promotion_report
            ) VALUES (
              :model, '[7, 14, 30]'::jsonb, '{}'::jsonb, :sha,
              :at, :at, 'success', '{}'::jsonb, 'passed',
              '{"passed": true}'::jsonb
            ) RETURNING id
            """
        ),
        {"model": model_id, "sha": suffix * 64, "at": observed},
    ).scalar_one()
    connection.execute(
        text(
            """
            UPDATE analytics_model_versions
            SET approval_status='approved', approval_backtest_run_id=:backtest,
                approval_decided_at=:at, approval_reason='integration-test approval'
            WHERE id=:model
            """
        ),
        {"backtest": backtest_id, "at": observed, "model": model_id},
    )
    return model_id


def test_partial_and_source_only_strategy_rows_receive_no_rank():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    with engine.connect() as connection:
        transaction = connection.begin()
        observed = datetime.now(UTC)
        source_run = connection.execute(
            text(
                """
                INSERT INTO scrape_runs (
                  started_at, finished_at, status, workflow, source_observed_at,
                  source_date, source_sha256, is_complete, parsed_game_count,
                  parsed_prize_tier_count, pipeline_version
                ) VALUES (
                  :at, :at, 'success', 'unpaid_prizes', :at,
                  (:at AT TIME ZONE 'America/Chicago')::date,
                  :sha, true, 4, 4, 'test'
                ) RETURNING id
                """
            ),
            {"at": observed, "sha": "6" * 64},
        ).scalar_one()
        game_ids = {}
        for number in ("rank-a", "rank-b-partial", "rank-c-source", "rank-d"):
            game_id = connection.execute(
                text(
                    "INSERT INTO games (game_number, name, ticket_price, is_active) "
                    "VALUES (:number, :name, 5, true) RETURNING id"
                ),
                {"number": number, "name": number},
            ).scalar_one()
            snapshot = connection.execute(
                text(
                    "INSERT INTO game_snapshots "
                    "(game_id, scrape_run_id, captured_at) "
                    "VALUES (:game, :run, :at) RETURNING id"
                ),
                {"game": game_id, "run": source_run, "at": observed},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO prize_tier_snapshots "
                    "(game_snapshot_id, prize_amount, original_count, "
                    "remaining_count, claimed_count) VALUES (:snapshot, 5, 100, 50, 50)"
                ),
                {"snapshot": snapshot},
            )
            game_ids[number] = game_id
        catalog_run = connection.execute(
            text(
                """
                INSERT INTO scrape_runs (
                  started_at, finished_at, status, workflow, source_observed_at,
                  source_date, source_sha256, is_complete, parsed_game_count,
                  parsed_prize_tier_count, pipeline_version
                ) VALUES (
                  :at, :at, 'success', 'instant_ticket_catalog', :at,
                  (:at AT TIME ZONE 'America/Chicago')::date,
                  :sha, true, 3, 0, 'test'
                ) RETURNING id
                """
            ),
            {"at": observed, "sha": "5" * 64},
        ).scalar_one()
        for position, number in enumerate(("rank-a", "rank-b-partial", "rank-d")):
            connection.execute(
                text(
                    """
                    INSERT INTO game_catalog_snapshots (
                      scrape_run_id, game_id, detail_url, display_name, ticket_price,
                      page_number, card_position
                    ) VALUES (:run, :game, :url, :name, 5, 1, :position)
                    """
                ),
                {
                    "run": catalog_run,
                    "game": game_ids[number],
                    "url": f"https://example.test/{number}",
                    "name": number,
                    "position": position,
                },
            )
        model_id = _approve_model(connection, observed, "a")
        analytics_run = connection.execute(
            text(
                """
                INSERT INTO analytics_runs (
                  model_version_id, as_of_scrape_run_id, as_of_observed_at,
                  started_at, finished_at, status, publishable
                ) VALUES (:model, :source, :at, :at, :at, 'success', true)
                RETURNING id
                """
            ),
            {"model": model_id, "source": source_run, "at": observed},
        ).scalar_one()
        values = {
            "rank-a": ("0.2", "complete"),
            "rank-b-partial": ("0.9", "partial"),
            "rank-c-source": ("0.8", "complete"),
            "rank-d": ("0.1", "complete"),
        }
        for number, (metric, status) in values.items():
            connection.execute(
                text(
                    """
                    INSERT INTO analytics_strategy_metrics (
                      analytics_run_id, game_id, ticket_price, p_break_even_exact,
                      one_in_break_even_exact, full_count_coverage, metric_statuses,
                      metric_details, lowest_confidence, contains_lumpy_tier
                    ) VALUES (
                      :run, :game, 5, CAST(:metric AS numeric),
                      1 / CAST(:metric AS numeric), 1,
                      jsonb_build_object(
                        'money_back_exact', CAST(:status AS text)
                      ), jsonb_build_object('money_back_exact', jsonb_build_object(
                        'target_tier_count', 1, 'count_coverage', '1',
                        'value_coverage', '1', 'launch_metric_value', '0.1',
                        'lowest_confidence', 'moderate',
                        'contains_lumpy_tier', false
                      )), 'moderate', false
                    )
                    """
                ),
                {
                    "run": analytics_run,
                    "game": game_ids[number],
                    "metric": metric,
                    "status": status,
                },
            )

        rows = connection.execute(
            text(
                "SELECT game_number, rank_overall, rank_within_ticket_price "
                "FROM current_strategy_rankings_v "
                "WHERE strategy_key='money_back_exact' ORDER BY rank_overall"
            )
        ).all()
        assert rows == [("rank-a", 1, 1), ("rank-d", 2, 2)]
        detail = connection.execute(
            text(
                "SELECT one_in_value, launch_metric_value, target_tier_count, "
                "target_count_coverage, target_value_coverage, relative_to_launch, "
                "eligible_all_confidence, eligible_moderate_or_high, "
                "contains_lumpy_tier, source_observed_at, catalog_observed_at, model_version "
                "FROM current_strategy_rankings_v "
                "WHERE game_number='rank-a' AND strategy_key='money_back_exact'"
            )
        ).one()
        assert detail.one_in_value == 5
        assert detail.launch_metric_value == Decimal("0.1")
        assert detail.target_tier_count == 1
        assert detail.target_count_coverage == 1
        assert detail.target_value_coverage == 1
        assert detail.relative_to_launch == 2
        assert detail.eligible_all_confidence is True
        assert detail.eligible_moderate_or_high is True
        assert detail.contains_lumpy_tier is False
        assert detail.source_observed_at == observed
        assert detail.catalog_observed_at == observed
        assert detail.model_version == "1.0.0"
        transaction.rollback()
    engine.dispose()


def test_stale_source_makes_rankings_explicitly_unavailable():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    with engine.connect() as connection:
        transaction = connection.begin()
        observed = datetime.now(UTC) - timedelta(days=100)
        connection.execute(
            text(
                "UPDATE scrape_runs SET source_observed_at=:at, "
                "source_date=(:at AT TIME ZONE 'America/Chicago')::date "
                "WHERE workflow IN ('unpaid_prizes', 'instant_ticket_catalog')"
            ),
            {"at": observed},
        )
        for workflow, suffix in (("unpaid_prizes", "c"), ("instant_ticket_catalog", "d")):
            connection.execute(
                text(
                    """
                    INSERT INTO scrape_runs (
                      started_at, finished_at, status, workflow, source_observed_at,
                      source_date, source_sha256, is_complete, parsed_game_count,
                      parsed_prize_tier_count, pipeline_version
                    ) VALUES (
                      :at, :at, 'success', :workflow, :at,
                      (:at AT TIME ZONE 'America/Chicago')::date,
                      :sha, true, 40, 40, 'test'
                    )
                    """
                ),
                {"at": observed, "workflow": workflow, "sha": suffix * 64},
            )
        _approve_model(connection, observed, "e")
        status = connection.execute(
            text("SELECT available, reason_code FROM current_strategy_ranking_status_v")
        ).one()
        assert status == (False, "SOURCE_STALE")
        assert connection.execute(
            text("SELECT count(*) FROM current_strategy_rankings_v")
        ).scalar_one() == 0
        transaction.rollback()
    engine.dispose()
