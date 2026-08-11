#!/usr/bin/env python3
"""Create a guarded disposable PostgreSQL database, migrate it, test it, and drop it."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from illinois_lottery_tracker.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATTERN = re.compile(r"^illinois_lottery_test_[a-z0-9_]+$")


def _target_database(value: str) -> str:
    if not TARGET_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "target must start with illinois_lottery_test_ and contain only a-z, 0-9, _"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-database", required=True, type=_target_database)
    parser.add_argument("--keep-database", action="store_true")
    parser.add_argument(
        "--pytest-target",
        action="append",
        default=[],
        help="pytest path to run in the disposable database; repeatable (default: tests/postgres)",
    )
    parser.add_argument(
        "--verify-backup-restore",
        action="store_true",
        help=(
            "after tests pass, back up the isolated database and verify a guarded "
            "restore before dropping both disposable databases"
        ),
    )
    parser.add_argument(
        "--verify-auth-maintenance",
        action="store_true",
        help="run auth maintenance dry/apply and the read-only auth audit after tests",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configured = make_url(get_settings().require_database_url())
    if configured.database == args.target_database:
        print("ERROR: test target must differ from DATABASE_URL", file=sys.stderr)
        return 2
    admin_url = configured.set(database="postgres")
    target_url = configured.set(database=args.target_database)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    created = False
    result_code = 1
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname=:name"),
                {"name": args.target_database},
            ).scalar_one_or_none()
            if exists:
                print(
                    f"ERROR: target database already exists: {args.target_database}",
                    file=sys.stderr,
                )
                return 2
            connection.exec_driver_sql(f'CREATE DATABASE "{args.target_database}"')
            created = True

        configuration = Config(str(PROJECT_ROOT / "alembic.ini"))
        configuration.set_main_option(
            "sqlalchemy.url", target_url.render_as_string(hide_password=False).replace("%", "%%")
        )
        command.upgrade(configuration, "head")

        environment = os.environ.copy()
        environment["TEST_DATABASE_URL"] = target_url.render_as_string(hide_password=False)
        pytest_targets = args.pytest_target or ["tests/postgres"]
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *pytest_targets],
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
        )
        result_code = result.returncode
        if result_code == 0 and args.verify_auth_maintenance:
            environment["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
            for mode in ("--dry-run", "--apply"):
                maintenance = subprocess.run(
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "scripts" / "maintain_authentication.py"),
                        mode,
                    ],
                    cwd=PROJECT_ROOT,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if maintenance.returncode != 0:
                    print(maintenance.stderr, file=sys.stderr)
                    return maintenance.returncode
                print(f"auth_maintenance_{mode[2:]}={maintenance.stdout.strip()}")
            psql = shutil.which("psql")
            if psql is None:
                print("ERROR: psql is required for the auth audit", file=sys.stderr)
                return 2
            psql_environment = environment.copy()
            if target_url.password is not None:
                psql_environment["PGPASSWORD"] = target_url.password
            connection_args: list[str] = []
            if target_url.host:
                connection_args.extend(["--host", target_url.host])
            if target_url.port:
                connection_args.extend(["--port", str(target_url.port)])
            if target_url.username:
                connection_args.extend(["--username", target_url.username])
            connection_args.extend(["--dbname", target_url.database or ""])
            audit = subprocess.run(
                [
                    psql,
                    *connection_args,
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--file",
                    str(
                        PROJECT_ROOT
                        / "docs"
                        / "authentication_blueprint"
                        / "auth_audit_queries.sql"
                    ),
                ],
                cwd=PROJECT_ROOT,
                env=psql_environment,
                check=False,
            )
            if audit.returncode != 0:
                return audit.returncode
        if result_code == 0 and args.verify_backup_restore:
            suffix = args.target_database.removeprefix("illinois_lottery_test_")
            restore_database = f"illinois_lottery_restore_verify_{suffix}"
            environment["DATABASE_URL"] = target_url.render_as_string(
                hide_password=False
            )
            with tempfile.TemporaryDirectory(
                prefix="illinois-lottery-backup-smoke-"
            ) as directory:
                backup = subprocess.run(
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "scripts" / "backup_database.py"),
                        "--target-dir",
                        directory,
                        "--name",
                        "isolated",
                    ],
                    cwd=PROJECT_ROOT,
                    env=environment,
                    check=False,
                )
                if backup.returncode != 0:
                    return backup.returncode
                restore = subprocess.run(
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "scripts" / "verify_database_restore.py"),
                        "--dump",
                        str(Path(directory) / "isolated.dump"),
                        "--target-database",
                        restore_database,
                    ],
                    cwd=PROJECT_ROOT,
                    env=environment,
                    check=False,
                )
                result_code = restore.returncode
        return result_code
    except Exception as exc:  # noqa: BLE001 - guarded command boundary
        print(f"ERROR: isolated PostgreSQL validation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if created and not args.keep_database:
            with admin.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=:name AND backend_type='client backend' "
                        "AND usename=current_user AND pid <> pg_backend_pid()"
                    ),
                    {"name": args.target_database},
                )
                connection.exec_driver_sql(f'DROP DATABASE "{args.target_database}"')
        admin.dispose()
        if created and args.keep_database:
            print(f"NOTICE: retained {args.target_database}")


if __name__ == "__main__":
    raise SystemExit(main())
