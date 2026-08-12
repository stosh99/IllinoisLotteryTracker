#!/usr/bin/env python3
"""Compare schema revision and row counts without revealing database credentials."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text

AUTH_TABLES = (
    "app_users",
    "user_identities",
    "user_sessions",
    "oidc_login_attempts",
    "auth_events",
)


def _snapshot(env_file: Path) -> tuple[str, str, dict[str, int]]:
    values = dotenv_values(env_file)
    database_url = values.get("DATABASE_URL")
    expected = values.get("EXPECTED_DATABASE_NAME")
    if not database_url or not expected:
        raise ValueError(f"incomplete guarded database environment: {env_file}")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        quote = engine.dialect.identifier_preparer.quote
        with engine.connect() as connection:
            actual = str(connection.scalar(text("SELECT current_database()")))
            if actual != expected:
                raise RuntimeError(f"expected {expected!r}, connected to {actual!r}")
            revision = str(connection.scalar(text("SELECT version_num FROM alembic_version")))
            counts = {
                table: int(connection.scalar(text(f"SELECT count(*) FROM {quote(table)}")))
                for table in sorted(inspector.get_table_names())
            }
    finally:
        engine.dispose()
    return actual, revision, counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-env", required=True, type=Path)
    parser.add_argument("--production-env", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        development = _snapshot(args.development_env.resolve())
        production = _snapshot(args.production_env.resolve())
        if development[1] != production[1]:
            raise RuntimeError(
                f"migration revision differs: dev={development[1]} prod={production[1]}"
            )
        if development[2] != production[2]:
            differing = sorted(
                table
                for table in set(development[2]) | set(production[2])
                if development[2].get(table) != production[2].get(table)
            )
            raise RuntimeError(f"table row counts differ: {differing}")
        auth_counts = {table: production[2].get(table) for table in AUTH_TABLES}
        if any(auth_counts.values()):
            raise RuntimeError(f"authentication tables are not empty: {auth_counts}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: environment comparison failed: {exc}", file=sys.stderr)
        return 1
    print(f"development_database={development[0]}")
    print(f"production_database={production[0]}")
    print(f"migration_revision={development[1]}")
    print(f"tables_compared={len(development[2])}")
    print("row_counts_identical=true")
    print("authentication_rows=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
