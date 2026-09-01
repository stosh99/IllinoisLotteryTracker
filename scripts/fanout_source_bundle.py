#!/usr/bin/env python3
"""Attempt independent development and production imports of one source bundle."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class Target:
    name: str
    project_root: Path
    environment: dict[str, str]


def _target_environment(target: Target) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "APP_ENV",
            "EXPECTED_DATABASE_NAME",
            "DEV_EXPECTED_DATABASE_NAME",
            "PUBLIC_BASE_URL",
            "ILT_DISABLE_DOTENV",
        }
        and not key.endswith("DATABASE_URL")
        and not key.startswith("AUTH_")
        and not key.startswith("GOOGLE_OIDC_")
    }
    environment.update(target.environment)
    environment["PYTHONPATH"] = str(target.project_root / "src")
    return environment


def _required(values: dict[str, str | None], key: str) -> str:
    value = values.get(key)
    if value is None or not value.strip():
        raise ValueError(f"application environment is missing {key}")
    return value.strip()


def build_targets(project_root: Path, env_file: Path) -> tuple[Target, Target]:
    """Build least-privilege importer environments from the canonical prod file."""
    values = dict(dotenv_values(env_file))
    if _required(values, "APP_ENV") != "production":
        raise ValueError("application environment APP_ENV must be production")
    raw_data_dir = _required(values, "RAW_DATA_DIR")
    production = {
        "APP_ENV": "production",
        "EXPECTED_DATABASE_NAME": _required(values, "EXPECTED_DATABASE_NAME"),
        "DATABASE_URL": _required(values, "DATABASE_URL"),
        "RAW_DATA_DIR": raw_data_dir,
        "AUTH_ENABLED": "false",
        "ILT_DISABLE_DOTENV": "true",
    }
    development = {
        "APP_ENV": "development",
        "EXPECTED_DATABASE_NAME": _required(values, "DEV_EXPECTED_DATABASE_NAME"),
        "DATABASE_URL": _required(values, "DEV_DATABASE_URL"),
        "RAW_DATA_DIR": raw_data_dir,
        "AUTH_ENABLED": "false",
        "ILT_DISABLE_DOTENV": "true",
    }
    root = project_root.resolve()
    return (
        Target("development", root, development),
        Target("production", root, production),
    )


def _run_target(target: Target, bundle: Path) -> int:
    script = target.project_root / "scripts" / "import_source_bundle.py"
    if not script.is_file():
        print(f"[{target.name}] ERROR: importer missing: {script}", file=sys.stderr)
        return 1
    completed = subprocess.run(
        [sys.executable, str(script), "--bundle", str(bundle)],
        cwd=target.project_root,
        env=_target_environment(target),
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"[{target.name}] exit={completed.returncode}")
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--application-env", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        targets = build_targets(args.project_root, args.application_env.resolve())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    results: dict[str, int] = {}
    for target in targets:
        try:
            results[target.name] = _run_target(target, args.bundle.resolve())
        except Exception as exc:  # noqa: BLE001
            print(f"[{target.name}] ERROR: {exc}", file=sys.stderr)
            results[target.name] = 1
    print(
        "fanout="
        + ",".join(f"{name}:{'ok' if code == 0 else 'failed'}" for name, code in results.items())
    )
    return 0 if all(code == 0 for code in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
