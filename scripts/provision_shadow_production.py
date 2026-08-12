#!/usr/bin/env python3
"""One-time guarded provisioning of shadow-production DB credentials and env files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PRODUCTION_DATABASE = "illinois_lottery_tracker_prod"
PRODUCTION_ROLE = "lottery_prod"
DEVELOPMENT_DATABASE = "illinois_lottery_tracker_dev"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_backup(dump: Path) -> None:
    manifest_path = dump.with_suffix(f"{dump.suffix}.manifest.json")
    marker_path = dump.with_suffix(f"{dump.suffix}.restore-verified.manifest.json")
    if not dump.is_file() or not manifest_path.is_file() or not marker_path.is_file():
        raise ValueError("backup, manifest, and restore-verification marker are required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    digest = _sha256(dump)
    if manifest.get("dump_sha256") != digest or marker.get("dump_sha256") != digest:
        raise ValueError("backup SHA-256 does not match its verification records")


def _admin_query(sql: str) -> str:
    completed = subprocess.run(
        ["sudo", "-n", "-u", "postgres", "psql", "-XAt", "-d", "postgres"],
        input=sql,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _write_private(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite configuration: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for key, value in values.items():
                if "\n" in value or "\r" in value:
                    raise ValueError(f"newline is not allowed in {key}")
                handle.write(f"{key}={value}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", required=True, type=Path)
    parser.add_argument("--development-env", required=True, type=Path)
    parser.add_argument("--config-dir", required=True, type=Path)
    parser.add_argument("--raw-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dump = args.dump.expanduser().resolve()
        _validate_backup(dump)
        source_values = dotenv_values(args.development_env.expanduser().resolve())
        source_url_text = source_values.get("DATABASE_URL")
        if not source_url_text:
            raise ValueError("development source env does not define DATABASE_URL")
        source_url = make_url(source_url_text)
        if source_url.database != DEVELOPMENT_DATABASE:
            raise ValueError(
                f"development source URL must name {DEVELOPMENT_DATABASE}"
            )
        exists = _admin_query(
            "SELECT concat((SELECT count(*) FROM pg_roles WHERE rolname = "
            f"'{PRODUCTION_ROLE}'), ':', (SELECT count(*) FROM pg_database WHERE datname = "
            f"'{PRODUCTION_DATABASE}'));\n"
        )
        if exists != "0:0":
            raise RuntimeError("production role or database already exists")

        password = secrets.token_urlsafe(36)
        escaped_password = password.replace("'", "''")
        _admin_query(
            f"CREATE ROLE {PRODUCTION_ROLE} LOGIN PASSWORD '{escaped_password}';\n"
        )
        _admin_query(
            f"CREATE DATABASE {PRODUCTION_DATABASE} OWNER {PRODUCTION_ROLE};\n"
        )
        with dump.open("rb") as backup_stream:
            subprocess.run(
                [
                    "sudo",
                    "-n",
                    "-u",
                    "postgres",
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    f"--role={PRODUCTION_ROLE}",
                    f"--dbname={PRODUCTION_DATABASE}",
                ],
                stdin=backup_stream,
                check=True,
                capture_output=True,
            )

        raw_root = str(args.raw_root.expanduser().resolve())
        production_url = source_url.set(
            username=PRODUCTION_ROLE,
            password=password,
            database=PRODUCTION_DATABASE,
        ).render_as_string(hide_password=False)
        engine = create_engine(production_url, future=True)
        try:
            with engine.connect() as connection:
                actual = connection.scalar(text("SELECT current_database()"))
                if actual != PRODUCTION_DATABASE:
                    raise RuntimeError(f"restored connection reached {actual!r}")
        finally:
            engine.dispose()

        config_dir = args.config_dir.expanduser().resolve()
        _write_private(
            config_dir / "development.env",
            {
                "APP_ENV": "development",
                "EXPECTED_DATABASE_NAME": DEVELOPMENT_DATABASE,
                "DATABASE_URL": source_url.render_as_string(hide_password=False),
                "RAW_DATA_DIR": raw_root,
                "AUTH_ENABLED": "false",
            },
        )
        _write_private(
            config_dir / "production.env",
            {
                "APP_ENV": "production",
                "EXPECTED_DATABASE_NAME": PRODUCTION_DATABASE,
                "DATABASE_URL": production_url,
                "RAW_DATA_DIR": raw_root,
                "AUTH_ENABLED": "false",
            },
        )
        _write_private(
            config_dir / "collector.env",
            {
                "APP_ENV": "collector",
                "RAW_DATA_DIR": raw_root,
                "AUTH_ENABLED": "false",
            },
        )
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: provisioning command failed: {(exc.stderr or '').strip()}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: shadow provisioning failed: {exc}", file=sys.stderr)
        return 1
    print(f"production_database={PRODUCTION_DATABASE}")
    print(f"production_role={PRODUCTION_ROLE}")
    print(f"configuration_dir={config_dir}")
    print("authentication_enabled=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
