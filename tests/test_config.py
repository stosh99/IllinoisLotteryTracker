"""Tests for illinois_lottery_tracker.config."""

from __future__ import annotations

import pytest

from illinois_lottery_tracker.config import DEFAULT_RAW_DATA_DIR, Settings, load_settings


def test_load_settings_defaults_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RAW_DATA_DIR", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("EXPECTED_DATABASE_NAME", raising=False)
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")

    settings = load_settings(empty_env)

    assert settings.database_url is None
    assert settings.raw_data_dir == DEFAULT_RAW_DATA_DIR
    assert settings.app_env == "development"
    assert settings.expected_database_name is None


def test_load_settings_reads_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("RAW_DATA_DIR", "custom/raw")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EXPECTED_DATABASE_NAME", "db")
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")

    settings = load_settings(empty_env)

    assert settings.database_url == "postgresql://example/db"
    assert settings.raw_data_dir == "custom/raw"
    assert settings.app_env == "production"
    assert settings.expected_database_name == "db"


def test_require_database_url_raises_when_missing():
    settings = Settings(database_url=None, raw_data_dir="data/raw")

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.require_database_url()


def test_require_database_url_returns_when_set():
    settings = Settings(database_url="postgresql://x/y", raw_data_dir="data/raw")

    assert settings.require_database_url() == "postgresql://x/y"
