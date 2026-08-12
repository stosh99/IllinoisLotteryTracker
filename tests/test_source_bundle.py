"""Immutable source-bundle manifest tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from illinois_lottery_tracker.catalog import CatalogPageCapture
from illinois_lottery_tracker.instant_ticket_discovery import (
    InstantTicketHubDiscoveryResult,
)
from illinois_lottery_tracker.raw_collector import RawCollectionResult
from illinois_lottery_tracker.source_bundle import (
    bundle_file_path,
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
) -> Path:
    capture_dir = raw_root / "2026-08-11"
    capture_dir.mkdir(parents=True, exist_ok=True)
    unpaid_path = capture_dir / f"unpaid{suffix}.html"
    hub_path = capture_dir / f"hub{suffix}.html"
    unpaid_path.write_text(f"unpaid evidence {suffix}", encoding="utf-8")
    hub_path.write_text(f"catalog evidence {suffix}", encoding="utf-8")
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
        created_at=created_at,
    )


def test_bundle_round_trip_uses_relative_verified_paths(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    bundle = load_source_bundle(tmp_path, manifest)

    assert bundle.bundle_id in manifest.name
    assert bundle.unpaid_prizes.path == "2026-08-11/unpaid.html"
    assert bundle_file_path(tmp_path, bundle.unpaid_prizes).read_text() == "unpaid evidence "
    assert [page.page_number for page in bundle.catalog_pages] == [1]


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
