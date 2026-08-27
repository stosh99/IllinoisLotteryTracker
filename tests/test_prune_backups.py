"""Backup retention keeps one dump per recent day, week, and month."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRUNE = PROJECT_ROOT / "scripts" / "prune_backups.py"


def _backup(directory: Path, moment: datetime) -> Path:
    dump = directory / f"illinois_lottery_{moment.strftime('%Y%m%dT%H%M%S%f')}.dump"
    dump.write_bytes(b"dump")
    dump.with_suffix(".dump.manifest.json").write_text(
        json.dumps({"created_at": moment.isoformat(), "dump_file": dump.name}),
        encoding="utf-8",
    )
    return dump


def _prune(backup_dir: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PRUNE), "--backup-dir", str(backup_dir), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )


def test_keeps_recent_days_and_prunes_the_rest(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    recent = [_backup(tmp_path, now - timedelta(days=offset)) for offset in range(3)]
    stale = _backup(tmp_path, now - timedelta(days=400))

    result = _prune(tmp_path, "--keep-daily", "2", "--keep-weekly", "1", "--keep-monthly", "1")

    assert recent[0].exists() and recent[1].exists(), result.stdout
    assert not stale.exists(), result.stdout
    # The manifest and any verification marker go with the pruned dump.
    assert not stale.with_suffix(".dump.manifest.json").exists()


def test_newest_backup_survives_the_tightest_retention(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    newest = _backup(tmp_path, now)
    _backup(tmp_path, now - timedelta(days=1))

    _prune(tmp_path, "--keep-daily", "1", "--keep-weekly", "1", "--keep-monthly", "1")

    assert newest.exists()


def test_retention_reaches_back_a_year(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    oldest = _backup(tmp_path, now - timedelta(days=330))
    for offset in range(0, 30):
        _backup(tmp_path, now - timedelta(days=offset))

    _prune(tmp_path)

    # A monthly slot still covers the eleven-month-old dump.
    assert oldest.exists()
    assert len(list(tmp_path.glob("*.dump"))) < 31


def test_dry_run_deletes_nothing(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    stale = _backup(tmp_path, now - timedelta(days=400))
    _backup(tmp_path, now)

    result = _prune(tmp_path, "--keep-daily", "1", "--keep-weekly", "1", "--keep-monthly", "1",
                    "--dry-run")

    assert stale.exists()
    assert "dry run" in result.stdout


def test_dump_without_a_readable_manifest_is_never_deleted(tmp_path: Path) -> None:
    orphan = tmp_path / "illinois_lottery_20200101T000000Z.dump"
    orphan.write_bytes(b"dump")
    _backup(tmp_path, datetime.now(UTC).replace(microsecond=0))

    _prune(tmp_path, "--keep-daily", "1", "--keep-weekly", "1", "--keep-monthly", "1")

    assert orphan.exists()
