"""Raw archive inventory and non-destructive maintenance tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from illinois_lottery_tracker.raw_archive import (
    audit_raw_archive,
    validate_archive_root,
    write_maintenance_manifest,
)


def test_audit_reports_category_file_byte_hash_and_savings_counts(tmp_path: Path):
    day = tmp_path / "2026-08-08"
    day.mkdir()
    (day / "unpaid-instant-games-prizes-a.html").write_bytes(b"history")
    (day / "instant-ticket-hub-a.html").write_bytes(b"same")
    (day / "instant-ticket-hub-b.html").write_bytes(b"same")
    (day / "instant-ticket-detail-a.html").write_bytes(b"detail")

    audit = audit_raw_archive(tmp_path)

    assert audit.files == 4
    assert audit.unique_hashes == 3
    assert audit.duplicate_bytes == len(b"same")
    assert audit.categories["hub"].files == 2
    assert audit.categories["hub"].unique_hashes == 1
    assert audit.categories["unpaid_prizes"].bytes == len(b"history")


def test_maintenance_defaults_to_plan_and_never_changes_captures(tmp_path: Path):
    day = tmp_path / "2026-08-08"
    day.mkdir()
    unpaid = day / "unpaid-instant-games-prizes-a.html"
    first = day / "instant-ticket-detail-a.html"
    second = day / "instant-ticket-detail-b.html"
    unpaid.write_bytes(b"same")
    first.write_bytes(b"duplicate")
    second.write_bytes(b"duplicate")
    before = {path: path.read_bytes() for path in (unpaid, first, second)}
    manifest = tmp_path.parent / f"{tmp_path.name}-manifest.json"

    document = write_maintenance_manifest(root=tmp_path, manifest_path=manifest)

    assert document["mode"] == "dry_run"
    assert document["policy"]["deletes_files"] is False
    assert len(document["duplicate_groups"]) == 1
    assert {path: path.read_bytes() for path in before} == before
    assert json.loads(manifest.read_text())["policy"]["unpaid_prizes_retention"] == (
        "indefinite_excluded"
    )


def test_maintenance_requires_safe_absolute_root(tmp_path: Path):
    with pytest.raises(ValueError, match="absolute"):
        validate_archive_root(Path("relative"))
    with pytest.raises(ValueError, match="broad"):
        validate_archive_root(Path("/"))
