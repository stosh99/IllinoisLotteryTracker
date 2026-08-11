#!/usr/bin/env python3
"""Restore a custom dump into a guarded disposable database and verify it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url

from illinois_lottery_tracker.config import get_settings

TARGET_PATTERN = re.compile(r"^illinois_lottery_restore_verify_[a-z0-9_]+$")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _target_database(value: str) -> str:
    if not TARGET_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "target must start with illinois_lottery_restore_verify_ and contain only a-z, 0-9, _"
        )
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _postgres_environment_and_args(url: URL) -> tuple[dict[str, str], list[str]]:
    environment = os.environ.copy()
    if url.password is not None:
        environment["PGPASSWORD"] = url.password
    args: list[str] = []
    if url.host:
        args.extend(["--host", url.host])
    if url.port:
        args.extend(["--port", str(url.port)])
    if url.username:
        args.extend(["--username", url.username])
    if not url.database:
        raise ValueError("database URL must name a database")
    args.extend(["--dbname", url.database])
    return environment, args


def _manifest_for(dump_path: Path) -> Path:
    return dump_path.with_suffix(f"{dump_path.suffix}.manifest.json")


def _load_manifest(dump_path: Path) -> dict[str, Any]:
    manifest_path = _manifest_for(dump_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    if document.get("dump_file") != dump_path.name:
        raise ValueError("manifest dump filename does not match")
    if document.get("dump_sha256") != _sha256(dump_path):
        raise ValueError("dump SHA-256 does not match manifest")
    return document


def _write_verification_marker(dump_path: Path, target_database: str) -> Path:
    marker = dump_path.with_suffix(f"{dump_path.suffix}.restore-verified.manifest.json")
    document = {
        "format_version": 1,
        "verified_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "dump_file": dump_path.name,
        "dump_sha256": _sha256(dump_path),
        "disposable_database": target_database,
        "authentication_exposure": "prohibited_disposable_restore",
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{marker.name}.", dir=marker.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
        marker.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return marker


def _database_exists(admin_engine: Any, database_name: str) -> bool:
    with admin_engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database_name}
            ).scalar_one_or_none()
        )


def _quoted_database(database_name: str) -> str:
    # The strict regex validation makes quoting deterministic and guards DDL scope.
    return f'"{database_name}"'


def _alembic_configuration(target_url: URL) -> Config:
    configuration = Config(str(PROJECT_ROOT / "alembic.ini"))
    configuration.set_main_option(
        "sqlalchemy.url",
        target_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return configuration


def _schema_signature(target_url: URL) -> dict[str, Any]:
    """Return a normalized public-schema signature, excluding Alembic bookkeeping."""
    engine = create_engine(target_url, future=True)
    try:
        inspector = inspect(engine)
        signature: dict[str, Any] = {}
        for table_name in sorted(
            name for name in inspector.get_table_names() if name != "alembic_version"
        ):
            columns = {
                column["name"]: {
                    "type": str(column["type"]),
                    "nullable": bool(column["nullable"]),
                    "default": column.get("default"),
                }
                for column in inspector.get_columns(table_name)
            }
            primary_key = tuple(
                sorted(inspector.get_pk_constraint(table_name)["constrained_columns"])
            )
            unique_constraints = sorted(
                tuple(sorted(item["column_names"]))
                for item in inspector.get_unique_constraints(table_name)
            )
            foreign_keys = sorted(
                (
                    tuple(item["constrained_columns"]),
                    item["referred_table"],
                    tuple(item["referred_columns"]),
                    (item.get("options") or {}).get("ondelete"),
                )
                for item in inspector.get_foreign_keys(table_name)
            )
            indexes = sorted(
                (
                    item["name"],
                    tuple(item["column_names"]),
                    bool(item["unique"]),
                )
                for item in inspector.get_indexes(table_name)
                if not item.get("duplicates_constraint")
            )
            signature[table_name] = {
                "columns": columns,
                "primary_key": primary_key,
                "unique_constraints": unique_constraints,
                "foreign_keys": foreign_keys,
                "indexes": indexes,
            }
        return signature
    finally:
        engine.dispose()


def _verify_legacy_schema_matches_baseline(
    restored_url: URL,
    baseline_url: URL,
) -> None:
    restored = _schema_signature(restored_url)
    baseline = _schema_signature(baseline_url)
    if restored != baseline:
        restored_tables = sorted(restored)
        baseline_tables = sorted(baseline)
        differing = sorted(
            table
            for table in set(restored) & set(baseline)
            if restored[table] != baseline[table]
        )
        raise RuntimeError(
            "restored pre-Alembic schema does not exactly match revision 0001; "
            f"restored_tables={restored_tables}, baseline_tables={baseline_tables}, "
            f"differing_tables={differing}"
        )


def _drop_disposable_database(admin_engine: Any, database_name: str) -> None:
    with admin_engine.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = :name "
                "AND backend_type = 'client backend' AND usename = current_user "
                "AND pid <> pg_backend_pid()"
            ),
            {"name": database_name},
        )
        connection.exec_driver_sql(f"DROP DATABASE {_quoted_database(database_name)}")


def _verify_revision(
    target_url: URL,
    expected_revision: str | None,
    *,
    require_head: bool = True,
) -> None:
    engine = create_engine(target_url, future=True)
    try:
        tables = inspect(engine).get_table_names()
        if "alembic_version" not in tables:
            raise RuntimeError("restored database has no alembic_version table")
        with engine.connect() as connection:
            actual = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()
    configuration = _alembic_configuration(target_url)
    head = ScriptDirectory.from_config(configuration).get_current_head()
    if require_head and actual != head:
        raise RuntimeError(f"restored revision {actual!r} is not head {head!r}")
    if expected_revision is not None and actual != expected_revision:
        raise RuntimeError(
            f"restored revision {actual!r} differs from manifest {expected_revision!r}"
        )


def _verify_row_counts(target_url: URL, expected: dict[str, int]) -> None:
    engine = create_engine(target_url, future=True)
    try:
        quote = engine.dialect.identifier_preparer.quote
        with engine.connect() as connection:
            for table_name, expected_count in sorted(expected.items()):
                actual = int(
                    connection.execute(
                        text(f"SELECT count(*) FROM {quote(table_name)}")
                    ).scalar_one()
                )
                if actual != expected_count:
                    raise RuntimeError(
                        f"row count mismatch for {table_name}: "
                        f"expected {expected_count}, got {actual}"
                    )
    finally:
        engine.dispose()


def _run_restored_database_checks(target_url: URL) -> None:
    environment = os.environ.copy()
    rendered_url = target_url.render_as_string(hide_password=False)
    environment["DATABASE_URL"] = rendered_url
    environment["TEST_DATABASE_URL"] = rendered_url
    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "audit_source_data.py"),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/postgres"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", required=True, type=Path)
    parser.add_argument("--target-database", required=True, type=_target_database)
    parser.add_argument(
        "--keep-database",
        action="store_true",
        help="Keep the verified disposable database for manual inspection.",
    )
    parser.add_argument(
        "--upgrade-legacy-baseline",
        action="store_true",
        help=(
            "for a manifest with no Alembic revision, compare the restored schema "
            "to a fresh revision-0001 database before stamping and upgrading the "
            "disposable restore to head"
        ),
    )
    parser.add_argument(
        "--upgrade-existing-to-head",
        action="store_true",
        help=(
            "verify a backup at its recorded Alembic revision, then upgrade only "
            "the disposable restore to head before audits and tests"
        ),
    )
    parser.add_argument(
        "--audit-sql",
        type=Path,
        default=PROJECT_ROOT / "docs" / "database_blueprint" / "audit_queries.sql",
        help="Read-only SQL audit executed with psql after schema and row-count checks.",
    )
    parser.add_argument(
        "--auth-audit-sql",
        type=Path,
        default=PROJECT_ROOT / "docs" / "authentication_blueprint" / "auth_audit_queries.sql",
        help="Read-only authentication audit executed after the main database audit.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dump_path = args.dump.resolve()
    if not dump_path.is_file():
        print(f"ERROR: dump not found: {dump_path}", file=sys.stderr)
        return 2
    try:
        manifest = _load_manifest(dump_path)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: invalid backup: {exc}", file=sys.stderr)
        return 2
    manifest_revision = manifest.get("migration_revision")
    if manifest_revision is None and not args.upgrade_legacy_baseline:
        print(
            "ERROR: pre-Alembic backup requires --upgrade-legacy-baseline",
            file=sys.stderr,
        )
        return 2
    if manifest_revision is not None and args.upgrade_legacy_baseline:
        print(
            "ERROR: --upgrade-legacy-baseline is only valid for a manifest "
            "without a migration revision",
            file=sys.stderr,
        )
        return 2
    if manifest_revision is None and args.upgrade_existing_to_head:
        print(
            "ERROR: --upgrade-existing-to-head requires a manifest revision",
            file=sys.stderr,
        )
        return 2
    if args.upgrade_legacy_baseline and args.upgrade_existing_to_head:
        print("ERROR: choose only one upgrade mode", file=sys.stderr)
        return 2

    settings = get_settings()
    if not settings.database_url:
        print("ERROR: DATABASE_URL is not configured", file=sys.stderr)
        return 2
    configured_url = make_url(settings.database_url)
    if configured_url.database == args.target_database:
        print("ERROR: target database must differ from DATABASE_URL", file=sys.stderr)
        return 2
    admin_url = configured_url.set(database="postgres")
    target_url = configured_url.set(database=args.target_database)
    baseline_database = f"{args.target_database}_baseline"
    if args.upgrade_legacy_baseline and (
        len(baseline_database) > 63 or not TARGET_PATTERN.fullmatch(baseline_database)
    ):
        print("ERROR: target name is too long for the baseline comparison", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"DRY RUN: would create, restore, and verify {args.target_database}")
        print(
            "DRY RUN: would drop it after success"
            if not args.keep_database
            else "DRY RUN: would keep it"
        )
        return 0

    pg_restore = shutil.which("pg_restore")
    psql = shutil.which("psql")
    if pg_restore is None or psql is None:
        print("ERROR: pg_restore and psql must be available", file=sys.stderr)
        return 2
    audit_sql = args.audit_sql.resolve()
    if not audit_sql.is_file():
        print(f"ERROR: audit SQL not found: {audit_sql}", file=sys.stderr)
        return 2
    auth_audit_sql = args.auth_audit_sql.resolve()
    if not auth_audit_sql.is_file():
        print(f"ERROR: auth audit SQL not found: {auth_audit_sql}", file=sys.stderr)
        return 2

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    if _database_exists(admin_engine, args.target_database):
        print(f"ERROR: target database already exists: {args.target_database}", file=sys.stderr)
        admin_engine.dispose()
        return 2
    if args.upgrade_legacy_baseline and _database_exists(
        admin_engine, baseline_database
    ):
        print(
            f"ERROR: baseline comparison database already exists: {baseline_database}",
            file=sys.stderr,
        )
        admin_engine.dispose()
        return 2

    created = False
    baseline_created = False
    verified = False
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {_quoted_database(args.target_database)}")
        created = True
        environment, connection_args = _postgres_environment_and_args(target_url)
        subprocess.run(
            [
                pg_restore,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                *connection_args,
                str(dump_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        if args.upgrade_legacy_baseline:
            baseline_url = configured_url.set(database=baseline_database)
            with admin_engine.connect() as connection:
                connection.exec_driver_sql(
                    f"CREATE DATABASE {_quoted_database(baseline_database)}"
                )
            baseline_created = True
            command.upgrade(_alembic_configuration(baseline_url), "0001_existing_schema_baseline")
            _verify_legacy_schema_matches_baseline(target_url, baseline_url)
            command.stamp(
                _alembic_configuration(target_url),
                "0001_existing_schema_baseline",
            )
            command.upgrade(_alembic_configuration(target_url), "head")
        if args.upgrade_existing_to_head:
            _verify_revision(target_url, manifest_revision, require_head=False)
            _verify_row_counts(target_url, manifest.get("row_counts", {}))
            command.upgrade(_alembic_configuration(target_url), "head")
            _verify_revision(target_url, None)
        else:
            _verify_revision(target_url, manifest_revision)
            _verify_row_counts(target_url, manifest.get("row_counts", {}))
        subprocess.run(
            [psql, *connection_args, "--set", "ON_ERROR_STOP=1", "--file", str(audit_sql)],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        subprocess.run(
            [
                psql,
                *connection_args,
                "--set",
                "ON_ERROR_STOP=1",
                "--file",
                str(auth_audit_sql),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        _run_restored_database_checks(target_url)
        verified = True
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "subprocess verification failed").strip()
        print(f"ERROR: restore failed: {detail}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: verification failed: {exc}", file=sys.stderr)
    finally:
        if baseline_created:
            _drop_disposable_database(admin_engine, baseline_database)
        if created and not args.keep_database:
            _drop_disposable_database(admin_engine, args.target_database)
        admin_engine.dispose()

    if not verified:
        return 1
    marker = _write_verification_marker(dump_path, args.target_database)
    print(f"OK: restored and verified {args.target_database}")
    print(f"verification_marker={marker}")
    if args.keep_database:
        print("NOTICE: verified database retained by explicit request")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
