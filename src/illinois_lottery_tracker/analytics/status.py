"""Read-only nightly source, catalog, analytics, and protection status."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session


def freshness(age_hours: float | None) -> str:
    if age_hours is None:
        return "unavailable"
    if age_hours <= 36:
        return "fresh"
    if age_hours <= 72:
        return "stale_warning"
    return "stale_error"


def build_nightly_status(
    session: Session,
    *,
    now: datetime | None = None,
    backup_dir: Path | None = None,
    raw_growth_limit_bytes: int | None = None,
    stage_durations_seconds: dict[str, float] | None = None,
) -> dict:
    if session.bind is None or session.bind.dialect.name != "postgresql":
        raise ValueError("nightly status requires PostgreSQL canonical views")
    observed_now = (now or datetime.now(UTC)).astimezone(UTC)
    source = session.execute(
        text(
            """
            WITH current_run AS (
                SELECT * FROM current_complete_scrape_run_v
            ), previous_run AS (
                SELECT sr.* FROM scrape_runs sr, current_run current
                WHERE sr.workflow='unpaid_prizes' AND sr.status='success'
                  AND sr.is_complete AND (sr.source_observed_at, sr.id)
                    < (current.source_observed_at, current.id)
                ORDER BY sr.source_observed_at DESC, sr.id DESC LIMIT 1
            )
            SELECT current.id, current.source_observed_at, current.source_date,
                   current.source_sha256, current.parsed_game_count,
                   current.parsed_prize_tier_count,
                   (SELECT parsed_game_count FROM previous_run)
                     previous_parsed_game_count,
                   (SELECT parsed_prize_tier_count FROM previous_run)
                     previous_parsed_prize_tier_count,
                   (SELECT count(*) FROM current_game_snapshots_v) current_games,
                   (SELECT count(*) FROM prize_tier_snapshots tier
                    JOIN current_game_snapshots_v snapshot
                      ON snapshot.id=tier.game_snapshot_id) current_tiers,
                   (SELECT count(*) FROM game_snapshots gs
                    WHERE gs.scrape_run_id=current.id AND NOT EXISTS (
                      SELECT 1 FROM game_snapshots prior
                      WHERE prior.scrape_run_id=(SELECT id FROM previous_run)
                        AND prior.game_id=gs.game_id)) additions,
                   (SELECT count(*) FROM game_snapshots prior
                    WHERE prior.scrape_run_id=(SELECT id FROM previous_run)
                      AND NOT EXISTS (SELECT 1 FROM game_snapshots gs
                        WHERE gs.scrape_run_id=current.id
                          AND gs.game_id=prior.game_id)) removals
            FROM current_run current
            """
        )
    ).mappings().one_or_none()
    catalog = session.execute(
        text(
            """
            SELECT run.id, run.source_observed_at, run.source_sha256,
                   count(c.id) entries,
                   count(c.id) FILTER (WHERE c.game_id IS NOT NULL) mapped,
                   count(c.id) FILTER (WHERE c.game_id IS NULL) unmapped,
                   (SELECT count(*) FROM catalog_quality_issues issue
                    WHERE issue.scrape_run_id=run.id AND issue.resolved_at IS NULL)
                     unresolved_quality_issues
            FROM current_complete_catalog_run_v run
            LEFT JOIN game_catalog_snapshots c ON c.scrape_run_id=run.id
            GROUP BY run.id, run.source_observed_at, run.source_sha256
            """
        )
    ).mappings().one_or_none()
    reconciliation = {
        row["membership_status"]: row["count"]
        for row in session.execute(
            text(
                "SELECT CASE "
                "WHEN prize_source_current AND catalog_current THEN 'source_and_catalog' "
                "WHEN prize_source_current THEN 'source_only' "
                "WHEN catalog_current THEN 'catalog_only' ELSE 'neither' END membership_status, "
                "count(*) count FROM current_game_source_reconciliation_v GROUP BY 1"
            )
        ).mappings()
    }
    analytics = session.execute(
        text(
            """
            SELECT ar.id, ar.status, ar.as_of_scrape_run_id,
                   ar.as_of_observed_at, mv.model_name, mv.semantic_version,
                   (SELECT count(*) FROM analytics_game_metrics gm
                    WHERE gm.analytics_run_id=ar.id AND gm.data_status='complete') games_scored,
                   (SELECT count(*) FROM analytics_game_metrics gm
                    WHERE gm.analytics_run_id=ar.id AND gm.data_status='partial') games_partial,
                   (SELECT count(*) FROM analytics_game_metrics gm
                    WHERE gm.analytics_run_id=ar.id AND gm.data_status='unavailable')
                    games_unavailable,
                   (SELECT count(*) FROM analytics_tier_metrics tm
                    WHERE tm.analytics_run_id=ar.id
                      AND tm.status IN ('available','depleted')) tiers_scored,
                   (SELECT count(*) FROM analytics_tier_metrics tm
                    WHERE tm.analytics_run_id=ar.id AND tm.status='unavailable') tiers_unavailable,
                   (SELECT count(*) FROM analytics_tier_metrics tm
                    WHERE tm.analytics_run_id=ar.id
                      AND tm.adjustment_status='applied') high_tiers_adjusted,
                   (SELECT count(*) FROM analytics_tier_metrics tm
                    WHERE tm.analytics_run_id=ar.id
                      AND tm.adjustment_status='reference_unavailable')
                    high_tiers_reference_unavailable
            FROM analytics_runs ar
            JOIN analytics_model_versions mv ON mv.id=ar.model_version_id
            WHERE ar.as_of_scrape_run_id=(SELECT id FROM current_complete_scrape_run_v)
            ORDER BY mv.created_at DESC, ar.id DESC LIMIT 1
            """
        )
    ).mappings().one_or_none()
    issue_rows = session.execute(
        text(
            """
            SELECT severity, code, count(*) count
            FROM analytics_quality_issues
            WHERE analytics_run_id=:run_id
            GROUP BY severity, code ORDER BY severity, code
            """
        ),
        {"run_id": analytics["id"] if analytics else -1},
    ).mappings()
    issues = [dict(row) for row in issue_rows]
    metadata_misses = session.execute(
        text(
            """
            SELECT count(*) FROM current_game_snapshots_v snapshot
            JOIN games game ON game.id=snapshot.game_id
            WHERE game.overall_odds_one_in IS NULL OR game.launch_date IS NULL
               OR game.category IS NULL OR game.source_url IS NULL
            """
        )
    ).scalar_one()
    invariant_failures = {
        "rollup_mismatches": session.execute(
            text(
                """
                WITH totals AS (
                  SELECT game_snapshot_id, sum(original_count) original_count,
                         sum(remaining_count) remaining_count,
                         sum(prize_amount * original_count) original_value,
                         sum(prize_amount * remaining_count) remaining_value
                  FROM prize_tier_snapshots GROUP BY game_snapshot_id
                )
                SELECT count(*) FROM game_snapshots snapshot
                JOIN totals ON totals.game_snapshot_id=snapshot.id
                WHERE snapshot.total_original_winning_tickets
                        IS DISTINCT FROM totals.original_count
                   OR snapshot.total_remaining_winning_tickets
                        IS DISTINCT FROM totals.remaining_count
                   OR snapshot.total_original_prize_value
                        IS DISTINCT FROM totals.original_value
                   OR snapshot.total_remaining_prize_value
                        IS DISTINCT FROM totals.remaining_value
                """
            )
        ).scalar_one(),
        "remaining_count_reversals": session.execute(
            text(
                """
                SELECT count(*) FROM (
                  SELECT tier.remaining_count,
                         lag(tier.remaining_count) OVER (
                           PARTITION BY snapshot.game_id, tier.prize_amount
                           ORDER BY run.source_observed_at, run.id
                         ) prior_remaining_count
                  FROM game_snapshots snapshot
                  JOIN scrape_runs run ON run.id=snapshot.scrape_run_id
                  JOIN prize_tier_snapshots tier ON tier.game_snapshot_id=snapshot.id
                  WHERE run.workflow='unpaid_prizes' AND run.status='success'
                    AND run.is_complete
                ) ordered
                WHERE remaining_count > prior_remaining_count
                """
            )
        ).scalar_one(),
    }
    ranking_status = _row_document(
        session.execute(text("SELECT * FROM current_strategy_ranking_status_v"))
        .mappings()
        .one()
    )
    source_document = _row_document(source)
    catalog_document = _row_document(catalog)
    source_age = _age_hours(observed_now, source["source_observed_at"] if source else None)
    catalog_age = _age_hours(
        observed_now, catalog["source_observed_at"] if catalog else None
    )
    protection = _protection_status(backup_dir, observed_now)
    raw_archive = _raw_archive_status(session, observed_now)
    return {
        "generated_at": observed_now.isoformat(),
        "source": {
            **source_document,
            "age_hours": source_age,
            "freshness": freshness(source_age),
        },
        "catalog": {
            **catalog_document,
            "age_hours": catalog_age,
            "freshness": freshness(catalog_age),
            "reconciliation": reconciliation,
        },
        "metadata_misses": metadata_misses,
        "analytics": _row_document(analytics),
        "quality_issues": issues,
        "invariant_failures": invariant_failures,
        "ranking_status": ranking_status,
        "raw_archive": raw_archive,
        "stage_durations_seconds": stage_durations_seconds or {},
        "protection": protection,
        "alerts": _alerts(
            source_age=source_age,
            catalog_age=catalog_age,
            source=source_document,
            analytics=_row_document(analytics),
            protection=protection,
            invariant_failures=invariant_failures,
            ranking_status=ranking_status,
            now=observed_now,
            raw_archive=raw_archive,
            raw_growth_limit_bytes=raw_growth_limit_bytes,
        ),
    }


def _row_document(row) -> dict:
    if row is None:
        return {}
    return {
        key: (
            value.isoformat()
            if hasattr(value, "isoformat")
            else float(value)
            if isinstance(value, Decimal)
            else value
        )
        for key, value in row.items()
    }


def _age_hours(now: datetime, observed_at: datetime | None) -> float | None:
    if observed_at is None:
        return None
    return (now - observed_at).total_seconds() / 3600


def _protection_status(backup_dir: Path | None, now: datetime) -> dict:
    if backup_dir is None or not backup_dir.is_dir():
        return {
            "backup_age_hours": None,
            "last_verified_restore_age_days": None,
        }
    backup_times = []
    restore_times = []
    for path in backup_dir.glob("*.manifest.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if "created_at" in document:
                backup_times.append(datetime.fromisoformat(document["created_at"]))
            if "verified_at" in document:
                restore_times.append(datetime.fromisoformat(document["verified_at"]))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    latest_backup = max(backup_times, default=None)
    latest_restore = max(restore_times, default=None)
    return {
        "backup_age_hours": _age_hours(now, latest_backup),
        "last_verified_restore_age_days": (
            (now - latest_restore).total_seconds() / 86_400 if latest_restore else None
        ),
    }


def _raw_archive_status(session: Session, now: datetime) -> dict:
    paths = session.scalars(
        text(
            "SELECT DISTINCT file_path FROM raw_source_snapshots "
            "WHERE captured_at >= :cutoff"
        ),
        {"cutoff": now - timedelta(days=30)},
    ).all()
    total = 0
    missing = 0
    for value in paths:
        try:
            total += Path(value).stat().st_size
        except OSError:
            missing += 1
    return {"new_unique_bytes_30d": total, "missing_files_30d": missing}


def _alerts(
    *,
    source_age,
    catalog_age,
    source,
    analytics,
    protection,
    invariant_failures,
    ranking_status,
    now,
    raw_archive,
    raw_growth_limit_bytes,
) -> list[str]:
    alerts = []
    if source_age is None or source_age > 36:
        alerts.append("SOURCE_NOT_FRESH")
    if catalog_age is None or catalog_age > 36:
        alerts.append("CATALOG_NOT_FRESH")
    if not analytics or analytics.get("as_of_scrape_run_id") != source.get("id"):
        alerts.append("ANALYTICS_CUTOFF_MISMATCH")
    if analytics and analytics.get("status") == "failed":
        alerts.append("ANALYTICS_FAILED")
    parsed_games = source.get("parsed_game_count")
    parsed_tiers = source.get("parsed_prize_tier_count")
    previous_games = source.get("previous_parsed_game_count")
    previous_tiers = source.get("previous_parsed_prize_tier_count")
    if parsed_games is not None and parsed_games < 40:
        alerts.append("SOURCE_GAME_COUNT_BELOW_GATE")
    if previous_games and parsed_games is not None and parsed_games < previous_games * 0.8:
        alerts.append("SOURCE_GAME_COUNT_REVERSAL")
    if previous_tiers and parsed_tiers is not None and parsed_tiers < previous_tiers * 0.8:
        alerts.append("SOURCE_TIER_COUNT_REVERSAL")
    if any(invariant_failures.values()):
        alerts.append("SOURCE_INVARIANT_FAILURE")
    local_now = now.astimezone(ZoneInfo("America/Chicago"))
    source_date = date.fromisoformat(source["source_date"]) if source.get("source_date") else None
    if local_now.hour >= 8 and source_date != local_now.date():
        alerts.append("NO_FRESH_SOURCE_BY_0800_CHICAGO")
    if not ranking_status.get("available"):
        reason = ranking_status.get("reason_code", "RANKINGS_UNAVAILABLE")
        if reason not in alerts:
            alerts.append(reason)
    if (
        raw_growth_limit_bytes is not None
        and raw_archive["new_unique_bytes_30d"] > raw_growth_limit_bytes
    ):
        alerts.append("RAW_ARCHIVE_MONTHLY_GROWTH_EXCEEDED")
    backup_age = protection["backup_age_hours"]
    if backup_age is None or backup_age > 36:
        alerts.append("BACKUP_STALE_OR_UNKNOWN")
    restore_age = protection["last_verified_restore_age_days"]
    if restore_age is None or restore_age > 35:
        alerts.append("RESTORE_VERIFICATION_STALE_OR_UNKNOWN")
    return alerts
