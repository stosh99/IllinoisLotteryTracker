#!/usr/bin/env python3
"""Rotate the shadow-production database password without printing it."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

PRODUCTION_DATABASE = "illinois_lottery_tracker_prod"
PRODUCTION_ROLE = "lottery_prod"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage: rotate_shadow_production_password.py ENV_FILE", file=sys.stderr)
        return 2
    path = Path(arguments[0]).expanduser().resolve()
    try:
        values = dotenv_values(path)
        database_url = values.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL is missing")
        url = make_url(database_url)
        if url.username != PRODUCTION_ROLE or url.database != PRODUCTION_DATABASE:
            raise ValueError("environment file is not the fixed shadow-production target")
        password = secrets.token_urlsafe(36)
        escaped = password.replace("'", "''")
        subprocess.run(
            [
                "sudo", "-n", "-u", "postgres", "psql", "-X",
                "-d", "postgres", "-v", "ON_ERROR_STOP=1",
            ],
            input=f"ALTER ROLE {PRODUCTION_ROLE} PASSWORD '{escaped}';\n",
            capture_output=True,
            text=True,
            check=True,
        )
        values["DATABASE_URL"] = url.set(password=password).render_as_string(
            hide_password=False
        )
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                for key, value in values.items():
                    if value is not None:
                        handle.write(f"{key}={value}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: password rotation failed: {(exc.stderr or '').strip()}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: password rotation failed: {exc}", file=sys.stderr)
        return 1
    print("production_database_password_rotated=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
