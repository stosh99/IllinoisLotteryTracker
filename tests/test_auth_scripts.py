from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_authentication_scripts_expose_help_without_loading_auth_secrets() -> None:
    for script in ("maintain_authentication.py", "manage_user_account.py"):
        result = _run(script, "--help")
        assert result.returncode == 0
        assert "usage:" in result.stdout
        assert "GOOGLE_OIDC_CLIENT_SECRET" not in result.stdout + result.stderr


def test_operator_delete_requires_matching_uuid_confirmation() -> None:
    user_id = str(uuid.uuid4())
    result = _run(
        "manage_user_account.py",
        "--delete-user-id",
        user_id,
        "--confirm-delete-user-id",
        str(uuid.uuid4()),
        "--reason-code",
        "user_request",
    )
    assert result.returncode == 2
    assert "same UUID" in result.stderr


def test_operator_mutations_default_to_dry_run_and_require_reason() -> None:
    result = _run("manage_user_account.py", "--suspend-user-id", str(uuid.uuid4()))
    assert result.returncode == 2
    assert "--reason-code" in result.stderr


def test_auth_maintenance_rejects_conflicting_modes() -> None:
    result = _run("maintain_authentication.py", "--dry-run", "--apply")
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
