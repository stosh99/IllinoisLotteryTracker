"""Tests for illinois_lottery_tracker.paths."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from illinois_lottery_tracker.config import Settings
from illinois_lottery_tracker.paths import (
    DATE_DIR_FORMAT,
    dated_raw_dir,
    format_date_dir,
    project_root,
    raw_data_dir,
)

DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _settings(raw_dir: str) -> Settings:
    return Settings(database_url=None, raw_data_dir=raw_dir)


def test_project_root_is_a_directory():
    assert project_root().is_dir()


def test_format_date_dir_uses_yyyy_mm_dd():
    formatted = format_date_dir(date(2026, 4, 24))
    assert formatted == "2026-04-24"
    assert DATE_DIR_RE.match(formatted)


def test_format_date_dir_accepts_datetime():
    formatted = format_date_dir(datetime(2026, 1, 5, 23, 59, tzinfo=UTC))
    assert formatted == "2026-01-05"
    assert DATE_DIR_FORMAT == "%Y-%m-%d"


def test_raw_data_dir_resolves_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = _settings("data/raw")

    resolved = raw_data_dir(settings)

    assert resolved.is_absolute()
    assert resolved.name == "raw"
    assert resolved.parent.name == "data"


def test_raw_data_dir_keeps_absolute_path(tmp_path):
    settings = _settings(str(tmp_path / "absolute_raw"))

    resolved = raw_data_dir(settings)

    assert resolved == tmp_path / "absolute_raw"


def test_dated_raw_dir_creates_dated_subdir(tmp_path):
    settings = _settings(str(tmp_path))
    when = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)

    target = dated_raw_dir(when, settings=settings)

    assert target == tmp_path / "2026-04-24"
    assert target.is_dir()
    assert DATE_DIR_RE.match(target.name)


def test_dated_raw_dir_is_idempotent(tmp_path):
    settings = _settings(str(tmp_path))
    when = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)

    first = dated_raw_dir(when, settings=settings)
    second = dated_raw_dir(when, settings=settings)

    assert first == second
    assert second.is_dir()


def test_dated_raw_dir_skip_create(tmp_path):
    settings = _settings(str(tmp_path))
    when = datetime(2026, 4, 24, tzinfo=UTC)

    target = dated_raw_dir(when, settings=settings, create=False)

    assert target == tmp_path / "2026-04-24"
    assert not target.exists()
