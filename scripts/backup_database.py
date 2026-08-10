#!/usr/bin/env python3
"""Create an atomic PostgreSQL custom-format backup and audit manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, inspect, text
from sqlalchemy.engine import URL, make_url

from illinois_lottery_tracker.config import get_settings
from illinois_lottery_tracker.db import get_engine


def _safe_target_directory(value: str) -> Path:
    if not value.strip() or value.startswith("~"):
        raise argparse.ArgumentTypeError("target directory must be an explicit path")
    target = Path(value).expanduser().resolve()
    if target in {Path("/"), Path.home().resolve()}:
        raise argparse.ArgumentTypeError("refusing broad target directory")
    return target


def _safe_name(value: str) -> str:
    if not value or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in value
    ):
        raise argparse.ArgumentTypeError("name may contain only lowercase letters, digits, _ and -")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _postgres_environment_and_args(url: URL) -> tuple[dict[str, str], list[str]]:
    if not url.database:
        raise ValueError("DATABASE_URL must name a database")
    environment = os.environ.copy()
    if url.password is not None:
        environment["PGPASSWORD"] = url.password
    sslmode = url.query.get("sslmode")
    if sslmode:
        environment["PGSSLMODE"] = sslmode
    args: list[str] = []
    if url.host:
        args.extend(["--host", url.host])
    if url.port:
        args.extend(["--port", str(url.port)])
    if url.username:
        args.extend(["--username", url.username])
    args.extend(["--dbname", url.database])
    return environment, args


def _row_counts(connection: Connection) -> dict[str, int]:
    inspector = inspect(connection)
    quote = connection.dialect.identifier_preparer.quote
    counts: dict[str, int] = {}
    for table_name in sorted(inspector.get_table_names()):
        counts[table_name] = int(
            connection.execute(text(f"SELECT count(*) FROM {quote(table_name)}")).scalar_one()
        )
    return counts


def _migration_revision(connection: Connection) -> str | None:
    if "alembic_version" not in inspect(connection).get_table_names():
        return None
    return connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one_or_none()


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-dir",
        required=True,
        type=_safe_target_directory,
        help="Explicit directory in which to create the dump and manifest.",
    )
    parser.add_argument(
        "--name",
        type=_safe_name,
        help="Optional deterministic basename; defaults to a UTC timestamp.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and print without writing."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if not settings.database_url:
        print("ERROR: DATABASE_URL is not configured", file=sys.stderr)
        return 2

    database_url = make_url(settings.database_url)
    timestamp = datetime.now(UTC).replace(microsecond=0)
    basename = args.name or f"illinois_lottery_{timestamp:%Y%m%dT%H%M%SZ}"
    dump_path = args.target_dir / f"{basename}.dump"
    manifest_path = dump_path.with_suffix(".dump.manifest.json")
    if dump_path.exists() or manifest_path.exists():
        print(f"ERROR: backup target already exists: {dump_path}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"DRY RUN: would create {dump_path}")
        print(f"DRY RUN: would create {manifest_path}")
        return 0

    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        print("ERROR: pg_dump is not available", file=sys.stderr)
        return 2

    args.target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.target_dir.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{basename}.", dir=args.target_dir)
    os.close(descriptor)
    temporary_dump = Path(temporary_name)
    temporary_dump.chmod(0o600)

    try:
        environment, connection_args = _postgres_environment_and_args(database_url)
        engine = get_engine(settings)
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                snapshot_id = connection.execute(
                    text("SELECT pg_export_snapshot()")
                ).scalar_one()
                migration_revision = _migration_revision(connection)
                row_counts = _row_counts(connection)
                subprocess.run(
                    [
                        pg_dump,
                        "--format=custom",
                        "--no-owner",
                        "--no-privileges",
                        "--snapshot",
                        snapshot_id,
                        "--file",
                        str(temporary_dump),
                        *connection_args,
                    ],
                    check=True,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                transaction.rollback()
        finally:
            engine.dispose()
        temporary_dump.chmod(0o600)
        manifest = {
            "format_version": 1,
            "created_at": timestamp.isoformat(),
            "database_name": database_url.database,
            "migration_revision": migration_revision,
            "dump_file": dump_path.name,
            "dump_bytes": temporary_dump.stat().st_size,
            "dump_sha256": _sha256(temporary_dump),
            "row_counts": row_counts,
        }
        os.replace(temporary_dump, dump_path)
        dump_path.chmod(0o600)
        _write_json_atomic(manifest_path, manifest)
    except subprocess.CalledProcessError as exc:
        temporary_dump.unlink(missing_ok=True)
        error = (exc.stderr or "pg_dump failed").strip()
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        temporary_dump.unlink(missing_ok=True)
        dump_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        print(f"ERROR: backup failed: {exc}", file=sys.stderr)
        return 1

    print(f"backup={dump_path}")
    print(f"manifest={manifest_path}")
    print(f"sha256={manifest['dump_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
