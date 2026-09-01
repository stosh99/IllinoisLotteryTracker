#!/usr/bin/env python3
"""Collect one database-free bundle, then fan it out to both environments."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--application-env", required=True, type=Path)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--chrome-profile-dir", required=True, type=Path)
    parser.add_argument("--chrome-force-x11", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--browser-first", action="store_true")
    parser.add_argument("--skip-if-today-collected", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
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
    environment["APP_ENV"] = "collector"
    environment["AUTH_ENABLED"] = "false"
    environment["ILT_DISABLE_DOTENV"] = "true"
    environment["RAW_DATA_DIR"] = str(args.raw_root.resolve())
    environment["PYTHONPATH"] = str(project_root / "src")
    collect_command = [
        sys.executable,
        str(project_root / "scripts" / "collect_source_bundle.py"),
        "--chrome-profile-dir",
        str(args.chrome_profile_dir.resolve()),
    ]
    for enabled, flag in (
        (args.chrome_force_x11, "--chrome-force-x11"),
        (args.headless, "--headless"),
        (args.browser_first, "--browser-first"),
        (args.skip_if_today_collected, "--skip-if-today-collected"),
    ):
        if enabled:
            collect_command.append(flag)
    collected = subprocess.run(
        collect_command,
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if collected.stdout:
        print(collected.stdout.rstrip())
    if collected.stderr:
        print(collected.stderr.rstrip(), file=sys.stderr)
    if collected.returncode != 0:
        return collected.returncode
    match = re.search(r"bundle_manifest=([^\s]+)", collected.stdout)
    if match is None:
        print("ERROR: collector did not report a bundle manifest", file=sys.stderr)
        return 1
    fanout = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "fanout_source_bundle.py"),
            "--bundle",
            match.group(1),
            "--project-root",
            str(project_root),
            "--application-env",
            str(args.application_env.resolve()),
        ],
        cwd=project_root,
        check=False,
    )
    return fanout.returncode


if __name__ == "__main__":
    raise SystemExit(main())
