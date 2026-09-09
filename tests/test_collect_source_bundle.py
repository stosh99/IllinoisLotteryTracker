"""Credential-free detail-page collection for immutable source bundles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.collect_source_bundle import collect_bundle_detail_pages

from illinois_lottery_tracker.catalog import CatalogPageCapture
from illinois_lottery_tracker.config import Settings
from illinois_lottery_tracker.instant_ticket_discovery import (
    DiscoveredInstantTicket,
    InstantTicketHubDiscoveryResult,
)
from illinois_lottery_tracker.raw_collector import (
    BatchPageResult,
    PersistentChromeOptions,
    RawCollectionResult,
)
from illinois_lottery_tracker.source_bundle import BundleFile, SourceBundle, sha256_file

NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)
BASE_URL = "https://www.illinoislottery.com/games-hub/instant-tickets"


def _raw(path: Path, url: str, captured_at: datetime = NOW) -> RawCollectionResult:
    return RawCollectionResult(
        source_url=url,
        file_path=str(path),
        sha256=sha256_file(path),
        captured_at=captured_at,
        content_type="text/html",
        bytes_written=path.stat().st_size,
        fetch_method="chrome",
    )


def _bundle_file(
    raw_root: Path, path: Path, url: str, captured_at: datetime = NOW
) -> BundleFile:
    return BundleFile(
        source_url=url,
        path=path.relative_to(raw_root).as_posix(),
        sha256=sha256_file(path),
        captured_at=captured_at,
        content_type="text/html",
        bytes_written=path.stat().st_size,
        fetch_method="chrome",
    )


def _catalog_page(tmp_path: Path, urls: list[str]) -> CatalogPageCapture:
    path = tmp_path / "hub.html"
    path.write_text("hub", encoding="utf-8")
    tickets = [
        DiscoveredInstantTicket(
            detail_url=url,
            slug=url.rsplit("/", 1)[-1],
            display_name=f"Game {index}",
            ticket_price=20,
        )
        for index, url in enumerate(urls, start=1)
    ]
    return CatalogPageCapture(
        page_number=1,
        collection=_raw(path, BASE_URL),
        discovery=InstantTicketHubDiscoveryResult(
            source_url=BASE_URL,
            tickets=tickets,
            pagination_urls=[],
            current_page_label="1 - 2",
            total_count=len(tickets),
            warnings=[],
        ),
    )


def _detail_html(game_number: str) -> str:
    return f"""
    <html><body>
      <h1 class="cmp-title__text">Game {game_number}</h1>
      <div class="itg-details-block"><table>
        <tr><td>Price Point</td><td>$20</td></tr>
        <tr><td>Overall Odds</td><td>1 in 3.50</td></tr>
        <tr><td>Category</td><td>Cash</td></tr>
        <tr><td>Launch Date</td><td>August 4, 2026</td></tr>
        <tr><td>Game Number</td><td>{game_number}</td></tr>
      </table></div>
    </body></html>
    """


def _previous_bundle(raw_root: Path, detail: BundleFile) -> SourceBundle:
    placeholder = BundleFile(
        source_url="https://example.test/source",
        path=detail.path,
        sha256=detail.sha256,
        captured_at=detail.captured_at,
        content_type=detail.content_type,
        bytes_written=detail.bytes_written,
        fetch_method=detail.fetch_method,
    )
    return SourceBundle(
        bundle_id="prior",
        created_at=detail.captured_at,
        unpaid_prizes=placeholder,
        catalog_pages=(placeholder,),
        detail_pages=(detail,),
        manifest_path=raw_root / "prior.json",
    )


def _successful_result(tmp_path: Path, url: str, game_number: str) -> BatchPageResult:
    path = tmp_path / f"{game_number}.html"
    path.write_text(_detail_html(game_number), encoding="utf-8")
    return BatchPageResult(
        url=url,
        file_path=str(path),
        sha256=sha256_file(path),
        captured_at=NOW,
        content_type="text/html",
        bytes_written=path.stat().st_size,
        fetch_method="chrome",
        error=None,
    )


def test_detail_collection_reuses_fresh_page_and_fetches_new_url(tmp_path: Path):
    old_url = f"{BASE_URL}/known"
    new_url = f"{BASE_URL}/new"
    old_path = tmp_path / "known.html"
    old_path.write_text(_detail_html("7668"), encoding="utf-8")
    previous = _previous_bundle(
        tmp_path, _bundle_file(tmp_path, old_path, old_url, NOW - timedelta(days=1))
    )
    requested: list[tuple[str, str]] = []

    def collect(pairs, **_):
        requested.extend(pairs)
        return [_successful_result(tmp_path, new_url, "7673")]

    pages, refreshed, failures = collect_bundle_detail_pages(
        tmp_path,
        [_catalog_page(tmp_path, [old_url, new_url])],
        settings=Settings(
            database_url=None, raw_data_dir=str(tmp_path), app_env="collector"
        ),
        chrome=PersistentChromeOptions(profile_dir=tmp_path / "profile"),
        previous_bundle=previous,
        observed_at=NOW,
        collect_pages_batch_fn=collect,
    )

    assert [pair[0] for pair in requested] == [new_url]
    assert [page.source_url for page in pages] == [old_url, new_url]
    assert refreshed == 1
    assert failures == ()


def test_detail_collection_refreshes_week_old_page(tmp_path: Path):
    url = f"{BASE_URL}/known"
    old_path = tmp_path / "known.html"
    old_path.write_text(_detail_html("7668"), encoding="utf-8")
    previous = _previous_bundle(
        tmp_path, _bundle_file(tmp_path, old_path, url, NOW - timedelta(days=8))
    )

    def collect(pairs, **_):
        assert [pair[0] for pair in pairs] == [url]
        return [_successful_result(tmp_path, url, "7668")]

    pages, refreshed, failures = collect_bundle_detail_pages(
        tmp_path,
        [_catalog_page(tmp_path, [url])],
        settings=Settings(
            database_url=None, raw_data_dir=str(tmp_path), app_env="collector"
        ),
        chrome=PersistentChromeOptions(profile_dir=tmp_path / "profile"),
        previous_bundle=previous,
        observed_at=NOW,
        collect_pages_batch_fn=collect,
    )

    assert len(pages) == 1
    assert pages[0].captured_at == NOW
    assert refreshed == 1
    assert failures == ()


def test_failed_refresh_carries_previous_verified_page_forward(tmp_path: Path):
    url = f"{BASE_URL}/known"
    old_path = tmp_path / "known.html"
    old_path.write_text(_detail_html("7668"), encoding="utf-8")
    old_at = NOW - timedelta(days=8)
    previous = _previous_bundle(
        tmp_path, _bundle_file(tmp_path, old_path, url, old_at)
    )

    def collect(pairs, **_):
        return [
            BatchPageResult(
                url=pairs[0][0],
                file_path=None,
                sha256=None,
                captured_at=NOW,
                content_type=None,
                bytes_written=0,
                fetch_method=None,
                error="temporary failure",
            )
        ]

    pages, refreshed, failures = collect_bundle_detail_pages(
        tmp_path,
        [_catalog_page(tmp_path, [url])],
        settings=Settings(
            database_url=None, raw_data_dir=str(tmp_path), app_env="collector"
        ),
        chrome=PersistentChromeOptions(profile_dir=tmp_path / "profile"),
        previous_bundle=previous,
        observed_at=NOW,
        collect_pages_batch_fn=collect,
    )

    assert len(pages) == 1
    assert pages[0].captured_at == old_at
    assert refreshed == 0
    assert failures == (f"{url}: temporary failure",)
