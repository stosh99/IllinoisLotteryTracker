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
    env_file: Path


def _target_environment(target: Target) -> dict[str, str]:
    values = dotenv_values(target.env_file)
    environment = os.environ.copy()
    for key, value in values.items():
        if value is not None:
            environment[key] = value
    environment["PYTHONPATH"] = str(target.project_root / "src")
    return environment


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
    parser.add_argument("--development-root", required=True, type=Path)
    parser.add_argument("--development-env", required=True, type=Path)
    parser.add_argument("--production-root", required=True, type=Path)
    parser.add_argument("--production-env", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    targets = (
        Target("development", args.development_root.resolve(), args.development_env.resolve()),
        Target("production", args.production_root.resolve(), args.production_env.resolve()),
    )
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
