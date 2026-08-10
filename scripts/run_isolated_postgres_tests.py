#!/usr/bin/env python3
"""Create a guarded disposable PostgreSQL database, migrate it, test it, and drop it."""

from __future__ import annotations

import argparse
import os
import re
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
        "--verify-backup-restore",
        action="store_true",
        help=(
            "after tests pass, back up the isolated database and verify a guarded "
            "restore before dropping both disposable databases"
        ),
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
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/postgres"],
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
        )
        result_code = result.returncode
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
                        "WHERE datname=:name"
                    ),
                    {"name": args.target_database},
                )
                connection.exec_driver_sql(f'DROP DATABASE "{args.target_database}"')
        admin.dispose()
        if created and args.keep_database:
            print(f"NOTICE: retained {args.target_database}")


if __name__ == "__main__":
    raise SystemExit(main())
