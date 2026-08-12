"""Immutable database-independent manifests for one complete source capture."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .catalog import CatalogPageCapture
from .instant_ticket_discovery import parse_instant_ticket_hub_html
from .raw_collector import RawCollectionResult

BUNDLE_FORMAT_VERSION = 1


@dataclass(frozen=True)
class BundleFile:
    source_url: str
    path: str
    sha256: str
    captured_at: datetime
    content_type: str | None
    bytes_written: int
    fetch_method: str
    page_number: int | None = None


@dataclass(frozen=True)
class SourceBundle:
    bundle_id: str
    created_at: datetime
    unpaid_prizes: BundleFile
    catalog_pages: tuple[BundleFile, ...]
    manifest_path: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_capture_path(raw_root: Path, file_path: str) -> str:
    root = raw_root.expanduser().resolve()
    path = Path(file_path).expanduser().resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"capture is outside RAW_DATA_DIR: {path}") from exc
    return relative.as_posix()


def _file_document(
    raw_root: Path, collection: RawCollectionResult, *, page_number: int | None = None
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "source_url": collection.source_url,
        "path": _relative_capture_path(raw_root, collection.file_path),
        "sha256": collection.sha256,
        "captured_at": collection.captured_at.astimezone(UTC).isoformat(),
        "content_type": collection.content_type,
        "bytes_written": collection.bytes_written,
        "fetch_method": collection.fetch_method,
    }
    if page_number is not None:
        document["page_number"] = page_number
    return document


def _bundle_digest(unpaid: dict[str, Any], catalog: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {
            "format_version": BUNDLE_FORMAT_VERSION,
            "unpaid_prizes": unpaid,
            "catalog_pages": catalog,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def write_source_bundle(
    raw_root: Path,
    *,
    unpaid_prizes: RawCollectionResult,
    catalog_pages: list[CatalogPageCapture],
    created_at: datetime | None = None,
) -> Path:
    """Atomically publish a complete manifest after all captures validate."""
    root = raw_root.expanduser().resolve()
    unpaid = _file_document(root, unpaid_prizes)
    catalog = [
        _file_document(root, page.collection, page_number=page.page_number)
        for page in sorted(catalog_pages, key=lambda item: item.page_number)
    ]
    bundle_id = _bundle_digest(unpaid, catalog)
    timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)
    target_dir = root / "bundles" / timestamp.strftime("%Y-%m-%d")
    target_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    target = target_dir / f"source-bundle-{bundle_id}.json"
    document = {
        "format_version": BUNDLE_FORMAT_VERSION,
        "bundle_id": bundle_id,
        "created_at": timestamp.isoformat(),
        "unpaid_prizes": unpaid,
        "catalog_pages": catalog,
    }
    encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    if target.exists():
        if target.read_bytes() != encoded:
            raise RuntimeError(f"immutable bundle collision: {target}")
        return target
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target_dir)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _safe_file(raw_root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"unsafe bundle path: {relative!r}")
    root = raw_root.expanduser().resolve()
    path = root.joinpath(*pure.parts).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"bundle path escapes RAW_DATA_DIR: {relative!r}") from exc
    return path


def _parse_file(raw_root: Path, document: Any, *, page: bool) -> BundleFile:
    if not isinstance(document, dict):
        raise ValueError("bundle file entry must be an object")
    required = {
        "source_url", "path", "sha256", "captured_at", "bytes_written", "fetch_method"
    }
    if not required <= document.keys():
        raise ValueError(f"bundle file entry lacks: {sorted(required - document.keys())}")
    path = _safe_file(raw_root, str(document["path"]))
    if not path.is_file():
        raise FileNotFoundError(f"bundle capture not found: {path}")
    size = int(document["bytes_written"])
    if path.stat().st_size != size:
        raise ValueError(f"bundle size mismatch: {path}")
    expected_hash = str(document["sha256"])
    if len(expected_hash) != 64 or sha256_file(path) != expected_hash:
        raise ValueError(f"bundle SHA-256 mismatch: {path}")
    captured_at = datetime.fromisoformat(str(document["captured_at"]))
    if captured_at.tzinfo is None:
        raise ValueError("bundle captured_at must include a timezone")
    page_number = int(document["page_number"]) if page else None
    return BundleFile(
        source_url=str(document["source_url"]),
        path=str(document["path"]),
        sha256=expected_hash,
        captured_at=captured_at.astimezone(UTC),
        content_type=(str(document["content_type"]) if document.get("content_type") else None),
        bytes_written=size,
        fetch_method=str(document["fetch_method"]),
        page_number=page_number,
    )


def load_source_bundle(raw_root: Path, manifest_path: Path) -> SourceBundle:
    root = raw_root.expanduser().resolve()
    manifest = manifest_path.expanduser().resolve()
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if document.get("format_version") != BUNDLE_FORMAT_VERSION:
        raise ValueError("unsupported source-bundle format version")
    unpaid_document = document.get("unpaid_prizes")
    catalog_document = document.get("catalog_pages")
    if not isinstance(catalog_document, list) or not catalog_document:
        raise ValueError("source bundle has no catalog pages")
    expected_id = _bundle_digest(unpaid_document, catalog_document)
    if document.get("bundle_id") != expected_id:
        raise ValueError("source-bundle ID does not match its contents")
    unpaid = _parse_file(root, unpaid_document, page=False)
    catalog = tuple(_parse_file(root, item, page=True) for item in catalog_document)
    numbers = [item.page_number for item in catalog]
    if numbers != list(range(1, len(catalog) + 1)):
        raise ValueError("catalog pages are not a contiguous 1-based sequence")
    created_at = datetime.fromisoformat(str(document["created_at"]))
    if created_at.tzinfo is None:
        raise ValueError("bundle created_at must include a timezone")
    return SourceBundle(
        bundle_id=expected_id,
        created_at=created_at.astimezone(UTC),
        unpaid_prizes=unpaid,
        catalog_pages=catalog,
        manifest_path=manifest,
    )


def bundle_file_path(raw_root: Path, item: BundleFile) -> Path:
    return _safe_file(raw_root, item.path)


def catalog_captures(raw_root: Path, bundle: SourceBundle) -> list[CatalogPageCapture]:
    pages: list[CatalogPageCapture] = []
    for item in bundle.catalog_pages:
        path = bundle_file_path(raw_root, item)
        discovery = parse_instant_ticket_hub_html(path, source_url=item.source_url)
        pages.append(
            CatalogPageCapture(
                page_number=item.page_number or 0,
                collection=RawCollectionResult(
                    source_url=item.source_url,
                    file_path=str(path),
                    sha256=item.sha256,
                    captured_at=item.captured_at,
                    content_type=item.content_type,
                    bytes_written=item.bytes_written,
                    fetch_method=item.fetch_method,  # type: ignore[arg-type]
                ),
                discovery=discovery,
            )
        )
    return pages


def valid_bundle_manifests(raw_root: Path) -> list[Path]:
    root = raw_root.expanduser().resolve()
    manifests: list[tuple[datetime, Path]] = []
    for path in sorted(root.glob("bundles/*/source-bundle-*.json")):
        try:
            bundle = load_source_bundle(root, path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        manifests.append((bundle.created_at, path))
    return [path for _, path in sorted(manifests, key=lambda item: (item[0], item[1]))]
