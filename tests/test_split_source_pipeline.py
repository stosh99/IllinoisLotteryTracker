"""Safety tests for one-tree collection and independent database imports."""

from __future__ import annotations

import subprocess

import pytest
from scripts import fanout_source_bundle, run_split_source_pipeline


def _write_application_env(path) -> None:
    path.write_text(
        "\n".join(
            (
                "APP_ENV=production",
                "EXPECTED_DATABASE_NAME=illinois_lottery_tracker_prod",
                "DATABASE_URL=postgresql://prod-secret@example/prod",
                "DEV_EXPECTED_DATABASE_NAME=illinois_lottery_tracker_dev",
                "DEV_DATABASE_URL=postgresql://dev-secret@example/dev",
                "RAW_DATA_DIR=/srv/source-captures",
                "GOOGLE_OIDC_CLIENT_SECRET=must-not-reach-importers",
                "AUTH_SECRET_KEYS=must-not-reach-importers",
            )
        )
        + "\n"
    )


def test_targets_use_one_root_and_least_privilege_environments(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    _write_application_env(env_file)
    monkeypatch.setenv("GOOGLE_OIDC_CLIENT_SECRET", "inherited-secret")
    monkeypatch.setenv("AUTH_SECRET_KEYS", "inherited-key")

    development, production = fanout_source_bundle.build_targets(tmp_path, env_file)

    assert development.project_root == production.project_root == tmp_path
    assert development.environment == {
        "APP_ENV": "development",
        "EXPECTED_DATABASE_NAME": "illinois_lottery_tracker_dev",
        "DATABASE_URL": "postgresql://dev-secret@example/dev",
        "RAW_DATA_DIR": "/srv/source-captures",
        "AUTH_ENABLED": "false",
        "ILT_DISABLE_DOTENV": "true",
    }
    assert production.environment == {
        "APP_ENV": "production",
        "EXPECTED_DATABASE_NAME": "illinois_lottery_tracker_prod",
        "DATABASE_URL": "postgresql://prod-secret@example/prod",
        "RAW_DATA_DIR": "/srv/source-captures",
        "AUTH_ENABLED": "false",
        "ILT_DISABLE_DOTENV": "true",
    }
    child = fanout_source_bundle._target_environment(development)
    assert "GOOGLE_OIDC_CLIENT_SECRET" not in child
    assert "AUTH_SECRET_KEYS" not in child
    assert "DEV_DATABASE_URL" not in child
    assert child["ILT_DISABLE_DOTENV"] == "true"


def test_targets_reject_incomplete_or_nonproduction_application_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=development\n")

    with pytest.raises(ValueError, match="APP_ENV must be production"):
        fanout_source_bundle.build_targets(tmp_path, env_file)


def test_collector_strips_database_credentials_before_fanout(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    _write_application_env(env_file)
    captures: list[dict] = []

    def fake_run(command, **kwargs):
        captures.append({"command": command, **kwargs})
        if len(captures) == 1:
            return subprocess.CompletedProcess(command, 0, "bundle_manifest=/tmp/bundle.json\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(run_split_source_pipeline.subprocess, "run", fake_run)
    for key in (
        "DATABASE_URL",
        "DEV_DATABASE_URL",
        "EXPECTED_DATABASE_NAME",
        "DEV_EXPECTED_DATABASE_NAME",
        "GOOGLE_OIDC_CLIENT_SECRET",
        "AUTH_SECRET_KEYS",
        "TEST_DATABASE_URL",
        "GOOGLE_OIDC_CLIENT_ID",
        "PUBLIC_BASE_URL",
    ):
        monkeypatch.setenv(key, "must-not-survive")

    result = run_split_source_pipeline.main(
        [
            "--project-root",
            str(tmp_path),
            "--application-env",
            str(env_file),
            "--raw-root",
            str(tmp_path / "raw"),
            "--chrome-profile-dir",
            str(tmp_path / "chrome"),
        ]
    )

    assert result == 0
    collector_env = captures[0]["env"]
    for key in (
        "DATABASE_URL",
        "DEV_DATABASE_URL",
        "EXPECTED_DATABASE_NAME",
        "DEV_EXPECTED_DATABASE_NAME",
        "GOOGLE_OIDC_CLIENT_SECRET",
        "AUTH_SECRET_KEYS",
        "TEST_DATABASE_URL",
        "GOOGLE_OIDC_CLIENT_ID",
        "PUBLIC_BASE_URL",
    ):
        assert key not in collector_env
    assert collector_env["APP_ENV"] == "collector"
    assert collector_env["AUTH_ENABLED"] == "false"
    assert collector_env["ILT_DISABLE_DOTENV"] == "true"
    fanout_command = captures[1]["command"]
    assert fanout_command[fanout_command.index("--project-root") + 1] == str(tmp_path)
    assert fanout_command[fanout_command.index("--application-env") + 1] == str(env_file)


def test_fanout_attempts_production_after_development_failure(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    _write_application_env(env_file)
    attempted: list[str] = []

    def fake_run_target(target, bundle):
        attempted.append(target.name)
        return 1 if target.name == "development" else 0

    monkeypatch.setattr(fanout_source_bundle, "_run_target", fake_run_target)

    result = fanout_source_bundle.main(
        [
            "--bundle",
            str(tmp_path / "bundle.json"),
            "--project-root",
            str(tmp_path),
            "--application-env",
            str(env_file),
        ]
    )

    assert result == 1
    assert attempted == ["development", "production"]
