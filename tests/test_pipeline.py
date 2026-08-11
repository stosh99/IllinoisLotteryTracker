"""Tests for illinois_lottery_tracker.pipeline.

No live network calls are made. The raw HTML is either constructed inline or
written to a tmp file. All DB tests use in-memory SQLite.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from illinois_lottery_tracker.analytics.persistence import (
    MODEL_NAME,
    MODEL_PARAMETERS,
    MODEL_VERSION,
    model_parameters_sha256,
)
from illinois_lottery_tracker.analytics_models import AnalyticsModelVersion, AnalyticsRun
from illinois_lottery_tracker.lifecycle import current_complete_run_id
from illinois_lottery_tracker.models import (
    Base,
    Game,
    GameSnapshot,
    PrizeTierSnapshot,
    RawSourceSnapshot,
    ScrapeRun,
)
from illinois_lottery_tracker.pipeline import (
    DuplicateImportError,
    PipelineResult,
    SourceQuarantinedError,
    ValidationError,
    find_successful_snapshot_run_for_source_date,
    orchestration_lock,
    run_analytics_stage,
    run_from_file,
    validate_unpaid_prizes_html,
)


def test_orchestration_lock_allows_one_worker_and_clean_skip():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with orchestration_lock(engine) as first:
        with orchestration_lock(engine) as second:
            assert first is True
            assert second is False
    with orchestration_lock(engine) as after_release:
        assert after_release is True


def test_source_commit_survives_separate_analytics_failure(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'stages.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    observed = datetime(2026, 8, 8, 12, tzinfo=UTC)
    with factory() as db:
        db.add(
            AnalyticsModelVersion(
                model_name=MODEL_NAME,
                semantic_version=MODEL_VERSION,
                parameters=MODEL_PARAMETERS,
                parameters_sha256=model_parameters_sha256(),
                code_version="test",
            )
        )
        source = ScrapeRun(
            started_at=observed,
            finished_at=observed,
            status="success",
            workflow="unpaid_prizes",
            source_observed_at=observed,
            source_date=observed.date(),
            source_sha256="a" * 64,
            is_complete=True,
            parsed_game_count=1,
            parsed_prize_tier_count=1,
            pipeline_version="test",
        )
        db.add(source)
        db.commit()
        source_id = source.id

    def fail_analytics(*_args, **_kwargs):
        raise RuntimeError("injected analytics failure")

    result = run_analytics_stage(
        factory,
        source_run_id=source_id,
        compute_fn=fail_analytics,
    )

    with factory() as db:
        source = db.get(ScrapeRun, source_id)
        analytics = db.get(AnalyticsRun, result.analytics_run_id)
        assert source is not None and source.status == "success" and source.is_complete
        assert analytics is not None and analytics.status == "failed"
        assert analytics.as_of_scrape_run_id == source_id

# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

_TABLE_CLASS = "unclaimed-prizes-table__row"
_CELL_CLASS = "unclaimed-prizes-table__cell"


def _prizes_html(n_games: int = 3) -> bytes:
    """Minimal valid unpaid-prizes HTML with *n_games* parseable rows."""
    rows = []
    for i in range(n_games):
        game_num = 1001 + i
        rows.append(
            f'<tr class="{_TABLE_CLASS}">'
            f'<td class="{_CELL_CLASS}">TEST GAME {i} ($5)</td>'
            f'<td class="{_CELL_CLASS}">$5</td>'
            f'<td class="{_CELL_CLASS}">{game_num}<br>(4)</td>'
            f'<td class="{_CELL_CLASS}">$5<br>$100</td>'
            f'<td class="{_CELL_CLASS}">1,000<br>10</td>'
            f'<td class="{_CELL_CLASS}">800<br>8</td>'
            f"</tr>"
        )
    table = "<table>" + "".join(rows) + "</table>"
    return f"<html><body>{table}</body></html>".encode()


_CLOUDFLARE_HTML = (
    b"<html><head><title>Just a moment...</title></head>"
    b"<body><div id='challenge-form'></div></body></html>"
)

_WRONG_PAGE_HTML = b"<html><body><h1>Page Not Found</h1></body></html>"

_EMPTY_TABLE_HTML = (
    b"<html><body>"
    b'<table class="unclaimed-prizes-table">'
    b"<!-- unclaimed-prizes-table__row -->"  # marker present but no actual rows
    b"</table></body></html>"
)

_SOURCE_DATE = date(2026, 5, 15)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db:
        yield db


@pytest.fixture
def prizes_file(tmp_path: Path) -> Path:
    path = tmp_path / "unpaid-instant-games-prizes-20260509T120000Z.html"
    path.write_bytes(_prizes_html(n_games=3))
    return path


@pytest.fixture
def cf_file(tmp_path: Path) -> Path:
    path = tmp_path / "cloudflare.html"
    path.write_bytes(_CLOUDFLARE_HTML)
    return path


@pytest.fixture
def wrong_page_file(tmp_path: Path) -> Path:
    path = tmp_path / "wrong-page.html"
    path.write_bytes(_WRONG_PAGE_HTML)
    return path


def _scrape_run(
    session: Session,
    *,
    started_at: datetime = datetime(2026, 5, 15, 7, 0, tzinfo=UTC),
) -> ScrapeRun:
    run = ScrapeRun(
        started_at=started_at,
        finished_at=started_at,
        status="success",
        source_url="https://example.test/unpaid",
        raw_file_path="/tmp/test.html",
    )
    session.add(run)
    session.flush()
    return run


def _raw_source_snapshot(
    session: Session,
    run: ScrapeRun,
    *,
    captured_at: datetime,
) -> RawSourceSnapshot:
    snapshot = RawSourceSnapshot(
        scrape_run_id=run.id,
        source_url="https://example.test/unpaid",
        content_type="text/html",
        file_path="/tmp/test.html",
        sha256=f"sha-{run.id}-{captured_at.isoformat()}",
        captured_at=captured_at,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _seed_snapshot_set(
    session: Session,
    run: ScrapeRun,
    *,
    game_count: int,
    game_number_start: int = 1000,
    prize_tiers: bool = True,
) -> None:
    for i in range(game_count):
        game = Game(
            game_number=str(game_number_start + i),
            name=f"TEST GAME {i}",
            ticket_price=5,
        )
        session.add(game)
        session.flush()
        snapshot = GameSnapshot(
            game=game,
            scrape_run=run,
            total_original_prize_value=100,
            total_remaining_prize_value=90,
            total_original_winning_tickets=10,
            total_remaining_winning_tickets=9,
        )
        session.add(snapshot)
        session.flush()
        if prize_tiers:
            session.add(
                PrizeTierSnapshot(
                    game_snapshot=snapshot,
                    prize_amount=100,
                    original_count=10,
                    remaining_count=9,
                    claimed_count=1,
                )
            )
    session.flush()


# ---------------------------------------------------------------------------
# validate_unpaid_prizes_html — pure function tests
# ---------------------------------------------------------------------------


def test_validate_accepts_valid_content():
    validate_unpaid_prizes_html(_prizes_html(3))  # should not raise


def test_validate_rejects_cloudflare_just_a_moment():
    with pytest.raises(ValidationError, match="Cloudflare"):
        validate_unpaid_prizes_html(b"<html><title>Just a moment...</title></html>")


def test_validate_rejects_cloudflare_challenge_form():
    with pytest.raises(ValidationError, match="Cloudflare"):
        validate_unpaid_prizes_html(b"<html><div id='challenge-form'></div></html>")


def test_validate_rejects_cloudflare_cf_browser_verification():
    with pytest.raises(ValidationError, match="Cloudflare"):
        validate_unpaid_prizes_html(b"<html><div class='cf-browser-verification'></div></html>")


def test_validate_rejects_cloudflare_attention_required():
    with pytest.raises(ValidationError, match="Cloudflare"):
        validate_unpaid_prizes_html(b"<html><title>Attention Required! | Cloudflare</title></html>")


def test_validate_rejects_wrong_page_no_table_marker():
    with pytest.raises(ValidationError, match="not the prizes page"):
        validate_unpaid_prizes_html(_WRONG_PAGE_HTML)


def test_validate_accepts_marker_in_comment():
    # The marker appears in a comment — still passes content check.
    validate_unpaid_prizes_html(_EMPTY_TABLE_HTML)  # should not raise


# ---------------------------------------------------------------------------
# find_successful_snapshot_run_for_source_date
# ---------------------------------------------------------------------------


def test_successful_snapshot_guard_empty_db(session: Session):
    assert (
        find_successful_snapshot_run_for_source_date(
            session,
            source_date=_SOURCE_DATE,
            min_games=20,
        )
        is None
    )


def test_successful_snapshot_guard_ignores_raw_snapshot_without_game_snapshots(
    session: Session,
):
    run = _scrape_run(session)
    _raw_source_snapshot(session, run, captured_at=datetime(2026, 5, 15, 7, 0, tzinfo=UTC))

    assert (
        find_successful_snapshot_run_for_source_date(
            session,
            source_date=_SOURCE_DATE,
            min_games=20,
        )
        is None
    )


def test_successful_snapshot_guard_requires_minimum_game_snapshots(session: Session):
    run = _scrape_run(session)
    _raw_source_snapshot(session, run, captured_at=datetime(2026, 5, 15, 7, 0, tzinfo=UTC))
    _seed_snapshot_set(session, run, game_count=19)

    assert (
        find_successful_snapshot_run_for_source_date(
            session,
            source_date=_SOURCE_DATE,
            min_games=20,
        )
        is None
    )


def test_successful_snapshot_guard_requires_prize_tiers(session: Session):
    run = _scrape_run(session)
    _raw_source_snapshot(session, run, captured_at=datetime(2026, 5, 15, 7, 0, tzinfo=UTC))
    _seed_snapshot_set(session, run, game_count=20, prize_tiers=False)

    assert (
        find_successful_snapshot_run_for_source_date(
            session,
            source_date=_SOURCE_DATE,
            min_games=20,
        )
        is None
    )


def test_successful_snapshot_guard_returns_complete_run_for_source_date(
    session: Session,
):
    run = _scrape_run(session)
    _raw_source_snapshot(session, run, captured_at=datetime(2026, 5, 15, 7, 0, tzinfo=UTC))
    _seed_snapshot_set(session, run, game_count=20)

    assert (
        find_successful_snapshot_run_for_source_date(
            session,
            source_date=_SOURCE_DATE,
            min_games=20,
        )
        == run.id
    )


def test_successful_snapshot_guard_uses_source_date_not_import_date(
    session: Session,
):
    run = _scrape_run(session, started_at=datetime(2026, 5, 16, 1, 0, tzinfo=UTC))
    _raw_source_snapshot(session, run, captured_at=datetime(2026, 5, 15, 7, 0, tzinfo=UTC))
    _seed_snapshot_set(session, run, game_count=20)

    assert (
        find_successful_snapshot_run_for_source_date(
            session,
            source_date=_SOURCE_DATE,
            min_games=20,
        )
        == run.id
    )


def test_successful_snapshot_guard_ignores_other_source_dates(session: Session):
    run = _scrape_run(session)
    _raw_source_snapshot(session, run, captured_at=datetime(2026, 5, 14, 7, 0, tzinfo=UTC))
    _seed_snapshot_set(session, run, game_count=20)

    assert (
        find_successful_snapshot_run_for_source_date(
            session,
            source_date=_SOURCE_DATE,
            min_games=20,
        )
        is None
    )


def test_successful_snapshot_guard_returns_latest_complete_run_for_date(
    session: Session,
):
    older = _scrape_run(session)
    newer = _scrape_run(session)
    _raw_source_snapshot(
        session, older, captured_at=datetime(2026, 5, 15, 7, 0, tzinfo=UTC)
    )
    _raw_source_snapshot(
        session, newer, captured_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    )
    _seed_snapshot_set(session, older, game_count=20)
    _seed_snapshot_set(session, newer, game_count=20, game_number_start=2000)

    assert (
        find_successful_snapshot_run_for_source_date(
            session,
            source_date=_SOURCE_DATE,
            min_games=20,
        )
        == newer.id
    )


# ---------------------------------------------------------------------------
# run_from_file — validation failures
# ---------------------------------------------------------------------------


def test_run_rejects_cloudflare_file(session: Session, cf_file: Path):
    with pytest.raises(ValidationError, match="Cloudflare"):
        run_from_file(session, cf_file, min_games=1)


def test_run_rejects_wrong_page_file(session: Session, wrong_page_file: Path):
    with pytest.raises(ValidationError, match="not the prizes page"):
        run_from_file(session, wrong_page_file, min_games=1)


def test_run_rejects_zero_parsed_games(session: Session, tmp_path: Path):
    # Table marker present but no actual data rows → 0 games parsed.
    path = tmp_path / "empty.html"
    path.write_bytes(
        b"<html><body>"
        b'<table><tbody class="unclaimed-prizes-table__row"></tbody></table>'
        b"</body></html>"
    )
    with pytest.raises(SourceQuarantinedError, match="ABSOLUTE_GAME_COUNT"):
        run_from_file(session, path, min_games=1)


def test_run_rejects_too_few_games(session: Session, tmp_path: Path):
    path = tmp_path / "one-game.html"
    path.write_bytes(_prizes_html(n_games=1))
    with pytest.raises(SourceQuarantinedError, match="ABSOLUTE_GAME_COUNT"):
        run_from_file(session, path, min_games=5)


def test_run_validation_error_leaves_session_clean(session: Session, cf_file: Path):
    with pytest.raises(ValidationError):
        run_from_file(session, cf_file, min_games=1)
    # Session must have no pending writes.
    assert len(session.new) == 0
    assert len(session.dirty) == 0


# ---------------------------------------------------------------------------
# run_from_file — successful run
# ---------------------------------------------------------------------------


def test_run_returns_pipeline_result(session: Session, prizes_file: Path):
    result = run_from_file(session, prizes_file, min_games=1)
    assert isinstance(result, PipelineResult)


def test_run_parsed_game_count(session: Session, prizes_file: Path):
    result = run_from_file(session, prizes_file, min_games=1)
    assert result.parsed_game_count == 3


def test_run_snapshots_inserted(session: Session, prizes_file: Path):
    result = run_from_file(session, prizes_file, min_games=1)
    assert result.snapshots_inserted == 3


def test_run_prize_tiers_inserted(session: Session, prizes_file: Path):
    # Each test game has 2 prize tiers ($5 and $100).
    result = run_from_file(session, prizes_file, min_games=1)
    assert result.prize_tiers_inserted == 6


def test_run_creates_scrape_run(session: Session, prizes_file: Path):
    run_from_file(session, prizes_file, min_games=1)
    count = session.scalar(select(func.count()).select_from(ScrapeRun))
    assert count == 1


def test_run_creates_raw_source_snapshot(session: Session, prizes_file: Path):
    run_from_file(session, prizes_file, min_games=1)
    count = session.scalar(select(func.count()).select_from(RawSourceSnapshot))
    assert count == 1


def test_raw_snapshot_captured_at_uses_filename_timestamp(session: Session, prizes_file: Path):
    # prizes_file fixture: unpaid-instant-games-prizes-20260509T120000Z.html
    run_from_file(session, prizes_file, min_games=1)
    rss = session.scalar(select(RawSourceSnapshot))
    from datetime import datetime
    # SQLite returns naive datetimes; compare without tzinfo.
    expected = datetime(2026, 5, 9, 12, 0, 0)
    assert rss.captured_at.replace(tzinfo=None) == expected


def test_raw_snapshot_captured_at_falls_back_to_mtime(session: Session, tmp_path: Path):
    # File whose name has no embedded timestamp → mtime is used.
    path = tmp_path / "unpaid-prizes-no-timestamp.html"
    path.write_bytes(_prizes_html(n_games=3))
    from datetime import UTC, datetime
    # Record expected mtime before import so we can compare exactly.
    expected_mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(tzinfo=None)
    run_from_file(session, path, min_games=1)
    rss = session.scalar(select(RawSourceSnapshot))
    # SQLite returns naive datetimes; compare without tzinfo.
    assert rss.captured_at.replace(tzinfo=None) == expected_mtime


def test_raw_snapshot_captured_at_differs_from_scrape_run_started_at(
    session: Session, prizes_file: Path
):
    # The file is named with a timestamp in the past; started_at is now.
    run_from_file(session, prizes_file, min_games=1)
    rss = session.scalar(select(RawSourceSnapshot))
    sr = session.scalar(select(ScrapeRun))
    # File captured_at (from filename) should be earlier than pipeline started_at.
    assert rss.captured_at < sr.started_at


def test_run_total_games_in_result(session: Session, prizes_file: Path):
    result = run_from_file(session, prizes_file, min_games=1)
    assert result.total_games == 3


def test_run_total_snapshots_in_result(session: Session, prizes_file: Path):
    result = run_from_file(session, prizes_file, min_games=1)
    assert result.total_snapshots == 3


def test_run_total_prize_tiers_in_result(session: Session, prizes_file: Path):
    result = run_from_file(session, prizes_file, min_games=1)
    assert result.total_prize_tiers == 6


def test_run_propagates_fetch_method(session: Session, prizes_file: Path):
    result = run_from_file(session, prizes_file, min_games=1, fetch_method="playwright")
    assert result.fetch_method == "playwright"


def test_run_fetch_method_none_when_omitted(session: Session, prizes_file: Path):
    result = run_from_file(session, prizes_file, min_games=1)
    assert result.fetch_method is None


# ---------------------------------------------------------------------------
# run_from_file — metrics computed
# ---------------------------------------------------------------------------


def test_run_metrics_computed_for_games_with_odds(session: Session, prizes_file: Path):
    # Our test games have no overall_odds_one_in — importer leaves it null.
    # So metrics will be skipped (no odds). Verify the field is present.
    result = run_from_file(session, prizes_file, min_games=1)
    assert result.metrics_snapshots_computed == 0
    assert result.metrics_skipped_no_odds == 3


def test_run_does_not_write_legacy_ev_when_odds_available(
    session: Session, prizes_file: Path
):
    # Seed overall odds, then prove the import still leaves legacy estimates untouched.
    run_from_file(session, prizes_file, min_games=1)
    session.execute(
        __import__("sqlalchemy").text(
            "UPDATE games SET overall_odds_one_in = 4.0"
        )
    )
    session.flush()

    # Second file with different content (different sha256) — in production,
    # consecutive nightly captures differ as prizes are claimed.
    prizes_file2 = prizes_file.parent / "unpaid-instant-games-prizes-20260510T120000Z.html"
    prizes_file2.write_bytes(_prizes_html(n_games=4))  # 4 games → different sha256

    result2 = run_from_file(session, prizes_file2, min_games=1)

    assert result2.metrics_snapshots_computed == 0
    snaps = list(session.scalars(select(GameSnapshot)))
    ev_set = [s for s in snaps if s.estimated_ev is not None]
    assert ev_set == []
    assert all(s.remaining_winning_tickets_pct is not None for s in snaps)


# ---------------------------------------------------------------------------
# run_from_file — dry-run behaviour (caller-controlled rollback)
# ---------------------------------------------------------------------------


def test_run_rollback_leaves_db_empty(session: Session, prizes_file: Path):
    run_from_file(session, prizes_file, min_games=1)
    session.rollback()

    assert session.scalar(select(func.count()).select_from(Game)) == 0
    assert session.scalar(select(func.count()).select_from(GameSnapshot)) == 0
    assert session.scalar(select(func.count()).select_from(PrizeTierSnapshot)) == 0
    assert session.scalar(select(func.count()).select_from(ScrapeRun)) == 0


def test_run_commit_persists_data(session: Session, prizes_file: Path):
    run_from_file(session, prizes_file, min_games=1)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Game)) == 3
    assert session.scalar(select(func.count()).select_from(GameSnapshot)) == 3


# ---------------------------------------------------------------------------
# run_from_file — duplicate import guard
# ---------------------------------------------------------------------------


def test_duplicate_import_raises_on_second_run(session: Session, prizes_file: Path):
    run_from_file(session, prizes_file, min_games=1)
    session.commit()

    with pytest.raises(DuplicateImportError, match="already imported"):
        run_from_file(session, prizes_file, min_games=1)


def test_duplicate_import_error_is_subclass_of_validation_error(
    session: Session, prizes_file: Path
):
    run_from_file(session, prizes_file, min_games=1)
    session.commit()

    with pytest.raises(ValidationError):
        run_from_file(session, prizes_file, min_games=1)


def test_duplicate_import_force_does_not_duplicate_immutable_source(
    session: Session, prizes_file: Path
):
    run_from_file(session, prizes_file, min_games=1)
    session.commit()

    with pytest.raises(DuplicateImportError, match="cannot duplicate"):
        run_from_file(session, prizes_file, min_games=1, force=True)


def test_complete_import_populates_canonical_provenance(session: Session, prizes_file: Path):
    run_from_file(session, prizes_file, min_games=1)
    run = session.scalar(select(ScrapeRun))
    snapshots = session.scalars(select(GameSnapshot)).all()

    assert run.workflow == "unpaid_prizes"
    assert run.is_complete is True
    assert run.source_date.isoformat() == "2026-05-09"
    assert run.source_sha256 is not None and len(run.source_sha256) == 64
    assert run.parsed_game_count == 3
    assert run.parsed_prize_tier_count == 6
    assert run.pipeline_version == "unpaid-prizes-v2"
    assert run.parser_version == "unpaid-prizes-html-v1"
    assert all(
        snapshot.captured_at.replace(tzinfo=None)
        == run.source_observed_at.replace(tzinfo=None)
        for snapshot in snapshots
    )
    assert all(snapshot.structure_fingerprint for snapshot in snapshots)


def test_dry_run_does_not_mark_content_as_imported(session: Session, prizes_file: Path):
    # Simulate a dry-run: run then rollback.
    run_from_file(session, prizes_file, min_games=1)
    session.rollback()

    # The rollback removes the RawSourceSnapshot — a real run should now succeed.
    result = run_from_file(session, prizes_file, min_games=1)
    session.commit()

    assert result.snapshots_inserted == 3


def test_different_content_not_blocked(
    session: Session, prizes_file: Path, tmp_path: Path
):
    run_from_file(session, prizes_file, min_games=1)
    session.commit()

    # Different content → different sha256 → no duplicate.
    other_file = tmp_path / "other.html"
    other_file.write_bytes(_prizes_html(n_games=4))
    result = run_from_file(session, other_file, min_games=1)
    session.commit()

    assert result.snapshots_inserted == 4


def test_partial_newer_source_is_quarantined_and_does_not_replace_current(
    session: Session, tmp_path: Path
):
    first = tmp_path / "unpaid-prizes-20260509T120000Z.html"
    partial = tmp_path / "unpaid-prizes-20260510T120000Z.html"
    first.write_bytes(_prizes_html(n_games=5))
    partial.write_bytes(_prizes_html(n_games=3))

    run_from_file(session, first, min_games=1)
    session.commit()
    complete_run = current_complete_run_id(session)

    with pytest.raises(SourceQuarantinedError, match="RELATIVE_GAME_COUNT"):
        run_from_file(session, partial, min_games=1)
    session.commit()

    assert current_complete_run_id(session) == complete_run
    quarantined = session.scalar(
        select(ScrapeRun).where(ScrapeRun.status == "quarantined")
    )
    assert quarantined is not None
    assert quarantined.is_complete is False
    assert quarantined.error_message is not None
    assert session.scalar(
        select(func.count())
        .select_from(GameSnapshot)
        .where(GameSnapshot.scrape_run_id == quarantined.id)
    ) == 0


def test_manual_reason_can_approve_only_relative_count_gate(
    session: Session, tmp_path: Path
):
    first = tmp_path / "unpaid-prizes-20260509T120000Z.html"
    smaller = tmp_path / "unpaid-prizes-20260510T120000Z.html"
    first.write_bytes(_prizes_html(n_games=5))
    smaller.write_bytes(_prizes_html(n_games=3))
    run_from_file(session, first, min_games=1)
    session.commit()

    result = run_from_file(
        session,
        smaller,
        min_games=1,
        manual_approval_reason="source reviewed against official page",
    )
    session.commit()

    assert result.snapshots_inserted == 3
    current = session.get(ScrapeRun, current_complete_run_id(session))
    assert current is not None
    assert current.manual_approval_reason == "source reviewed against official page"
    assert current.manually_approved_at is not None
    states = dict(session.execute(select(Game.game_number, Game.is_active)).all())
    assert sum(states.values()) == 3


def test_collect_only_raw_snapshot_not_treated_as_duplicate(
    session: Session, prizes_file: Path
):
    """A RawSourceSnapshot with no associated GameSnapshots (collect-only run)
    must not trigger DuplicateImportError.
    """
    import hashlib

    content = prizes_file.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()

    # Simulate what collect_raw_snapshot.py does: ScrapeRun + RawSourceSnapshot,
    # but no GameSnapshots under that run.
    from datetime import UTC, datetime

    from illinois_lottery_tracker.models import RawSourceSnapshot as RSS
    from illinois_lottery_tracker.models import ScrapeRun as SR

    collect_run = SR(
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="success",
        source_url="https://example.test",
        raw_file_path=str(prizes_file),
    )
    session.add(collect_run)
    session.flush()
    session.add(
        RSS(
            scrape_run_id=collect_run.id,
            source_url="https://example.test",
            content_type="text/html",
            file_path=str(prizes_file),
            sha256=sha256,
            captured_at=datetime.now(UTC),
        )
    )
    session.flush()

    # pipeline import of same content should NOT raise DuplicateImportError
    result = run_from_file(session, prizes_file, min_games=1)
    session.commit()

    assert result.snapshots_inserted == 3


def test_duplicate_guard_does_not_mutate_session_on_raise(
    session: Session, prizes_file: Path
):
    run_from_file(session, prizes_file, min_games=1)
    session.commit()

    with pytest.raises(DuplicateImportError):
        run_from_file(session, prizes_file, min_games=1)

    # Session must be clean — no pending writes from the rejected run.
    assert len(session.new) == 0
    assert len(session.dirty) == 0
