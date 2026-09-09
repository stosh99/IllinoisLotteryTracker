"""Immutable source-bundle manifest tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from illinois_lottery_tracker.catalog import CatalogPageCapture
from illinois_lottery_tracker.instant_ticket_discovery import (
    DiscoveredInstantTicket,
    InstantTicketHubDiscoveryResult,
)
from illinois_lottery_tracker.raw_collector import RawCollectionResult
from illinois_lottery_tracker.source_bundle import (
    bundle_file_path,
    bundle_has_complete_detail_coverage,
    load_source_bundle,
    sha256_file,
    valid_bundle_manifests,
    write_source_bundle,
)


def _collection(path: Path, *, source_url: str) -> RawCollectionResult:
    return RawCollectionResult(
        source_url=source_url,
        file_path=str(path),
        sha256=sha256_file(path),
        captured_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
        content_type="text/html",
        bytes_written=path.stat().st_size,
        fetch_method="chrome",
    )


def _write_bundle(
    raw_root: Path,
    *,
    suffix: str = "",
    created_at: datetime = datetime(2026, 8, 11, 13, tzinfo=UTC),
    include_detail: bool = False,
) -> Path:
    capture_dir = raw_root / "2026-08-11"
    capture_dir.mkdir(parents=True, exist_ok=True)
    unpaid_path = capture_dir / f"unpaid{suffix}.html"
    hub_path = capture_dir / f"hub{suffix}.html"
    unpaid_path.write_text(f"unpaid evidence {suffix}", encoding="utf-8")
    hub_path.write_text(f"catalog evidence {suffix}", encoding="utf-8")
    detail_path = capture_dir / f"detail{suffix}.html"
    detail_path.write_text(f"detail evidence {suffix}", encoding="utf-8")
    page = CatalogPageCapture(
        page_number=1,
        collection=_collection(hub_path, source_url="https://example.test/hub"),
        discovery=InstantTicketHubDiscoveryResult(
            source_url="https://example.test/hub",
            tickets=[],
            pagination_urls=[],
            current_page_label=None,
            total_count=0,
            warnings=[],
        ),
    )
    return write_source_bundle(
        raw_root,
        unpaid_prizes=_collection(unpaid_path, source_url="https://example.test/unpaid"),
        catalog_pages=[page],
        detail_pages=(
            [_collection(detail_path, source_url="https://example.test/detail")]
            if include_detail
            else []
        ),
        created_at=created_at,
    )


def test_bundle_round_trip_uses_relative_verified_paths(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path, include_detail=True)
    bundle = load_source_bundle(tmp_path, manifest)

    assert bundle.bundle_id in manifest.name
    assert bundle.unpaid_prizes.path == "2026-08-11/unpaid.html"
    assert bundle_file_path(tmp_path, bundle.unpaid_prizes).read_text() == "unpaid evidence "
    assert [page.page_number for page in bundle.catalog_pages] == [1]
    assert [detail.path for detail in bundle.detail_pages] == ["2026-08-11/detail.html"]


def test_bundle_loader_preserves_legacy_format_one_replay(tmp_path: Path) -> None:
    current_manifest = _write_bundle(tmp_path)
    document = json.loads(current_manifest.read_text(encoding="utf-8"))
    document["format_version"] = 1
    document.pop("detail_pages")
    digest_document = {
        "format_version": 1,
        "unpaid_prizes": document["unpaid_prizes"],
        "catalog_pages": document["catalog_pages"],
    }
    encoded = json.dumps(
        digest_document, sort_keys=True, separators=(",", ":")
    ).encode()
    document["bundle_id"] = hashlib.sha256(encoded).hexdigest()
    legacy_manifest = tmp_path / "legacy-source-bundle.json"
    legacy_manifest.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    bundle = load_source_bundle(tmp_path, legacy_manifest)

    assert bundle.bundle_id == document["bundle_id"]
    assert bundle.detail_pages == ()


def test_bundle_detail_coverage_matches_catalog_urls(tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-08-11"
    capture_dir.mkdir(parents=True)
    detail_url = (
        "https://www.illinoislottery.com/games-hub/instant-tickets/7668"
    )
    unpaid_path = capture_dir / "unpaid.html"
    unpaid_path.write_text("unpaid", encoding="utf-8")
    hub_path = capture_dir / "hub.html"
    hub_path.write_text(
        '<div class="simple-game-card"><a href="/games-hub/instant-tickets/7668" '
        'aria-label="Big Time Blowout"></a>'
        '<span class="simple-game-card-prize__price">$20</span></div>',
        encoding="utf-8",
    )
    detail_path = capture_dir / "detail.html"
    detail_path.write_text("detail", encoding="utf-8")
    page = CatalogPageCapture(
        page_number=1,
        collection=_collection(hub_path, source_url="https://example.test/hub"),
        discovery=InstantTicketHubDiscoveryResult(
            source_url="https://example.test/hub",
            tickets=[
                DiscoveredInstantTicket(
                    detail_url=detail_url,
                    display_name="Big Time Blowout",
                    ticket_price=20,
                )
            ],
            pagination_urls=[],
            current_page_label="1 - 1",
            total_count=1,
            warnings=[],
        ),
    )
    missing_manifest = write_source_bundle(
        tmp_path,
        unpaid_prizes=_collection(unpaid_path, source_url="https://example.test/unpaid"),
        catalog_pages=[page],
        created_at=datetime(2026, 8, 11, 13, tzinfo=UTC),
    )
    complete_manifest = write_source_bundle(
        tmp_path,
        unpaid_prizes=_collection(unpaid_path, source_url="https://example.test/unpaid"),
        catalog_pages=[page],
        detail_pages=[_collection(detail_path, source_url=detail_url)],
        created_at=datetime(2026, 8, 11, 14, tzinfo=UTC),
    )

    assert not bundle_has_complete_detail_coverage(
        tmp_path, load_source_bundle(tmp_path, missing_manifest)
    )
    assert bundle_has_complete_detail_coverage(
        tmp_path, load_source_bundle(tmp_path, complete_manifest)
    )


def test_bundle_rejects_capture_tampering(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    capture = tmp_path / document["unpaid_prizes"]["path"]
    capture.write_text("changed evidence", encoding="utf-8")

    with pytest.raises(ValueError, match="mismatch"):
        load_source_bundle(tmp_path, manifest)


def test_bundle_rejects_capture_outside_raw_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-source.html"
    outside.write_text("evidence", encoding="utf-8")
    catalog_path = tmp_path / "hub.html"
    catalog_path.write_text("hub", encoding="utf-8")
    page = CatalogPageCapture(
        page_number=1,
        collection=_collection(catalog_path, source_url="https://example.test/hub"),
        discovery=InstantTicketHubDiscoveryResult(None, [], [], None, 0, []),
    )
    try:
        with pytest.raises(ValueError, match="outside RAW_DATA_DIR"):
            write_source_bundle(
                tmp_path,
                unpaid_prizes=_collection(outside, source_url="https://example.test/unpaid"),
                catalog_pages=[page],
            )
    finally:
        outside.unlink(missing_ok=True)


def test_valid_manifests_are_ordered_by_created_at_not_hash_name(tmp_path: Path) -> None:
    newer = _write_bundle(
        tmp_path,
        suffix="-newer",
        created_at=datetime(2026, 8, 11, 15, tzinfo=UTC),
    )
    older = _write_bundle(
        tmp_path,
        suffix="-older",
        created_at=datetime(2026, 8, 11, 14, tzinfo=UTC),
    )

    assert valid_bundle_manifests(tmp_path) == [older, newer]
