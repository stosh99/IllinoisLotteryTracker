"""Safety and dry-run tests for database backup tooling."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.verify_database_restore import _run_restored_database_checks
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = ROOT / "scripts" / "backup_database.py"
RESTORE_SCRIPT = ROOT / "scripts" / "verify_database_restore.py"
FAKE_DATABASE_URL = "postgresql+psycopg://user:password@127.0.0.1/example"


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = FAKE_DATABASE_URL
    return environment


def test_backup_dry_run_writes_nothing(tmp_path):
    target = tmp_path / "backups"
    result = subprocess.run(
        [
            sys.executable,
            str(BACKUP_SCRIPT),
            "--target-dir",
            str(target),
            "--name",
            "test-backup",
            "--dry-run",
        ],
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    assert not target.exists()


def test_backup_refuses_broad_target():
    result = subprocess.run(
        [sys.executable, str(BACKUP_SCRIPT), "--target-dir", "/", "--dry-run"],
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "refusing broad target" in result.stderr


def test_backup_refuses_existing_output(tmp_path):
    existing = tmp_path / "test-backup.dump"
    existing.write_bytes(b"existing")
    result = subprocess.run(
        [
            sys.executable,
            str(BACKUP_SCRIPT),
            "--target-dir",
            str(tmp_path),
            "--name",
            "test-backup",
            "--dry-run",
        ],
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "already exists" in result.stderr


def test_restore_dry_run_validates_manifest_without_database_access(tmp_path):
    dump = tmp_path / "test.dump"
    dump.write_bytes(b"custom-format-placeholder")
    manifest = {
        "dump_file": dump.name,
        "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        "migration_revision": "0001_existing_schema_baseline",
        "row_counts": {},
    }
    dump.with_suffix(".dump.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(RESTORE_SCRIPT),
            "--dump",
            str(dump),
            "--target-database",
            "illinois_lottery_restore_verify_unit",
            "--dry-run",
        ],
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "would create, restore, and verify" in result.stdout


def test_pre_alembic_restore_requires_explicit_baseline_upgrade(tmp_path):
    dump = tmp_path / "legacy.dump"
    dump.write_bytes(b"legacy-custom-format-placeholder")
    manifest = {
        "dump_file": dump.name,
        "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        "migration_revision": None,
        "row_counts": {},
    }
    dump.with_suffix(".dump.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    base_command = [
        sys.executable,
        str(RESTORE_SCRIPT),
        "--dump",
        str(dump),
        "--target-database",
        "illinois_lottery_restore_verify_legacy_unit",
        "--dry-run",
    ]

    refused = subprocess.run(
        base_command,
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    accepted = subprocess.run(
        [*base_command, "--upgrade-legacy-baseline"],
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert refused.returncode == 2
    assert "requires --upgrade-legacy-baseline" in refused.stderr
    assert accepted.returncode == 0


def test_restore_verification_fails_closed_when_source_audit_fails(monkeypatch):
    def failed_audit(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], output="audit failed")

    monkeypatch.setattr(subprocess, "run", failed_audit)
    with pytest.raises(subprocess.CalledProcessError):
        _run_restored_database_checks(make_url(FAKE_DATABASE_URL))
