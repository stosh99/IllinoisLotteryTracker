"""Metadata enrichment imported from a verified source bundle."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from scripts.import_source_bundle import import_bundle_detail_metadata
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from illinois_lottery_tracker.auth_models import AppUser  # noqa: F401
from illinois_lottery_tracker.models import (
    Base,
    CatalogQualityIssue,
    Game,
    GameCatalogSnapshot,
    ScrapeRun,
)
from illinois_lottery_tracker.source_bundle import BundleFile, SourceBundle, sha256_file

DETAIL_URL = (
    "https://www.illinoislottery.com/games-hub/instant-tickets/big-time-blowout"
)


def test_bundle_detail_metadata_resolves_new_game_catalog_mapping(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    detail_path = tmp_path / "detail.html"
    detail_path.write_text(
        """
        <html><body>
          <h1 class="cmp-title__text">Big Time Blowout</h1>
          <div class="itg-details-block"><table>
            <tr><td>Price Point</td><td>$20</td></tr>
            <tr><td>Overall Odds</td><td>1 in 9.68</td></tr>
            <tr><td>Category</td><td>Money</td></tr>
            <tr><td>Play Style</td><td>Symbol Reveal</td></tr>
            <tr><td>Launch Date</td><td>August 4, 2026</td></tr>
            <tr><td>Game Number</td><td>7668</td></tr>
          </table></div>
        </body></html>
        """,
        encoding="utf-8",
    )
    detail = BundleFile(
        source_url=DETAIL_URL,
        path=detail_path.relative_to(tmp_path).as_posix(),
        sha256=sha256_file(detail_path),
        captured_at=datetime(2026, 9, 9, 12, tzinfo=UTC),
        content_type="text/html",
        bytes_written=detail_path.stat().st_size,
        fetch_method="chrome",
    )
    bundle = SourceBundle(
        bundle_id="test",
        created_at=detail.captured_at,
        unpaid_prizes=detail,
        catalog_pages=(),
        detail_pages=(detail,),
        manifest_path=tmp_path / "manifest.json",
    )

    with Session(engine, expire_on_commit=False) as session:
        game = Game(
            game_number="7668",
            name="BIG-TIME BLOWOUT",
            ticket_price=Decimal("20"),
            is_active=True,
        )
        catalog_run = ScrapeRun(
            started_at=datetime(2026, 9, 9, 12, tzinfo=UTC),
            finished_at=datetime(2026, 9, 9, 12, tzinfo=UTC),
            status="success",
            workflow="instant_ticket_catalog",
            is_complete=True,
        )
        session.add_all([game, catalog_run])
        session.flush()
        card = GameCatalogSnapshot(
            scrape_run_id=catalog_run.id,
            game_id=None,
            detail_url=DETAIL_URL,
            slug="big-time-blowout",
            display_name="Big Time Blowout",
            ticket_price=Decimal("20"),
            page_number=1,
            card_position=0,
        )
        session.add(card)
        session.flush()
        issue = CatalogQualityIssue(
            scrape_run_id=catalog_run.id,
            catalog_snapshot_id=card.id,
            code="UNKNOWN_URL_REQUIRES_VERIFICATION",
            severity="warning",
            detail_url=DETAIL_URL,
            details={"candidate_game_ids": [game.id]},
        )
        session.add(issue)
        session.flush()

        result, resolved = import_bundle_detail_metadata(
            session,
            raw_root=tmp_path,
            bundle=bundle,
            catalog_run_id=catalog_run.id,
        )

        assert result.games_updated == 1
        assert resolved == 1
        assert game.source_url == DETAIL_URL
        assert game.launch_date == date(2026, 8, 4)
        assert game.overall_odds_one_in == Decimal("9.68")
        assert game.category == "Money"
        assert card.game_id == game.id
        assert issue.resolved_game_id == game.id
        assert issue.resolved_at is not None
        assert session.scalar(select(Game).where(Game.game_number == "7668")) is game
