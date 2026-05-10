from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_help(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_parse_saved_html_help_exits_cleanly():
    result = run_help("parse_saved_html.py")

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "file not found" not in result.stderr


def test_discover_source_help_exits_without_starting_discovery():
    result = run_help("discover_source.py")

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "discovery run failed" not in result.stderr
    assert "BrowserType.launch" not in result.stderr
