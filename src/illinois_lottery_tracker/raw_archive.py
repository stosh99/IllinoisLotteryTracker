"""Read-only raw-archive inventory and non-destructive maintenance planning."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class RawFileRecord:
    path: str
    category: str
    size: int
    sha256: str


@dataclass(frozen=True)
class CategoryAudit:
    files: int
    bytes: int
    unique_hashes: int
    duplicate_bytes: int


@dataclass(frozen=True)
class RawArchiveAudit:
    root: str
    files: int
    bytes: int
    unique_hashes: int
    duplicate_bytes: int
    categories: dict[str, CategoryAudit]
    records: tuple[RawFileRecord, ...]

    def to_dict(self, *, include_records: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "root": self.root,
            "files": self.files,
            "bytes": self.bytes,
            "unique_hashes": self.unique_hashes,
            "duplicate_bytes": self.duplicate_bytes,
            "categories": {
                key: asdict(value) for key, value in sorted(self.categories.items())
            },
        }
        if include_records:
            result["records"] = [asdict(record) for record in self.records]
        return result


def validate_archive_root(root: Path, *, require_explicit: bool = True) -> Path:
    if require_explicit and not root.is_absolute():
        raise ValueError("raw archive root must be an explicit absolute path")
    resolved = root.resolve()
    home = Path.home().resolve()
    if resolved in {Path("/"), home}:
        raise ValueError("refusing broad raw archive root")
    if not resolved.is_dir():
        raise ValueError(f"raw archive root is not a directory: {resolved}")
    return resolved


def categorize_raw_path(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    lowered = path.name.casefold()
    if ".content" in relative.parts:
        return "content_blob"
    if "unpaid-instant-games-prizes" in lowered:
        return "unpaid_prizes"
    if "instant-ticket-hub" in lowered:
        return "hub"
    if "instant-ticket-detail" in lowered:
        return "detail"
    if "cloudflare" in lowered or "invalid" in lowered:
        return "invalid"
    return "other"


def audit_raw_archive(root: Path) -> RawArchiveAudit:
    root = validate_archive_root(root, require_explicit=False)
    records: list[RawFileRecord] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name.endswith(".tmp"):
            continue
        content = path.read_bytes()
        records.append(
            RawFileRecord(
                path=str(path.relative_to(root)),
                category=categorize_raw_path(path, root),
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    categories: dict[str, CategoryAudit] = {}
    for category in sorted({record.category for record in records}):
        category_records = [record for record in records if record.category == category]
        first_sizes: dict[str, int] = {}
        for record in category_records:
            first_sizes.setdefault(record.sha256, record.size)
        size = sum(record.size for record in category_records)
        categories[category] = CategoryAudit(
            files=len(category_records),
            bytes=size,
            unique_hashes=len(first_sizes),
            duplicate_bytes=size - sum(first_sizes.values()),
        )
    first_sizes: dict[str, int] = {}
    for record in records:
        first_sizes.setdefault(record.sha256, record.size)
    total_bytes = sum(record.size for record in records)
    return RawArchiveAudit(
        root=str(root),
        files=len(records),
        bytes=total_bytes,
        unique_hashes=len(first_sizes),
        duplicate_bytes=total_bytes - sum(first_sizes.values()),
        categories=categories,
        records=tuple(records),
    )


def write_maintenance_manifest(
    *,
    root: Path,
    manifest_path: Path,
    apply: bool = False,
) -> dict[str, object]:
    """Write a deduplication plan and optionally seed immutable blob copies.

    This deliberately never removes or replaces a capture.  Unpaid-prizes
    history is marked indefinite and is excluded from every proposed action.
    """
    root = validate_archive_root(root)
    manifest_path = manifest_path.resolve()
    if manifest_path.exists():
        raise FileExistsError(f"manifest already exists: {manifest_path}")
    audit = audit_raw_archive(root)
    grouped: dict[str, list[RawFileRecord]] = defaultdict(list)
    for record in audit.records:
        if record.category not in {"content_blob", "unpaid_prizes"}:
            grouped[record.sha256].append(record)
    duplicate_groups = [records for records in grouped.values() if len(records) > 1]
    seeded_blobs: list[str] = []
    if apply:
        for records in duplicate_groups:
            source = root / records[0].path
            digest = records[0].sha256
            blob_dir = root / ".content" / digest[:2]
            blob_dir.mkdir(parents=True, exist_ok=True)
            blob = blob_dir / f"{digest}{source.suffix or '.bin'}"
            if not blob.exists():
                try:
                    os.link(source, blob)
                except OSError:
                    blob.write_bytes(source.read_bytes())
                seeded_blobs.append(str(blob.relative_to(root)))
    document: dict[str, object] = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "mode": "apply_non_destructive" if apply else "dry_run",
        "policy": {
            "deletes_files": False,
            "replaces_capture_files": False,
            "unpaid_prizes_retention": "indefinite_excluded",
        },
        "audit": audit.to_dict(),
        "duplicate_groups": [
            {
                "sha256": records[0].sha256,
                "size": records[0].size,
                "projected_savings": records[0].size * (len(records) - 1),
                "paths": [record.path for record in records],
            }
            for records in duplicate_groups
        ],
        "seeded_blobs": seeded_blobs,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    temporary.replace(manifest_path)
    return document
