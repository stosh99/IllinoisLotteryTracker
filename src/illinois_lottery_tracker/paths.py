"""Filesystem path helpers for the project."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from .config import Settings, get_settings

DATE_DIR_FORMAT = "%Y-%m-%d"


def project_root() -> Path:
    """Return the absolute path to the project root."""
    return Path(__file__).resolve().parents[2]


def raw_data_dir(settings: Settings | None = None) -> Path:
    """Return the absolute path to the configured raw data directory."""
    settings = settings or get_settings()
    raw = Path(settings.raw_data_dir)
    if not raw.is_absolute():
        raw = project_root() / raw
    return raw


def format_date_dir(when: date | datetime) -> str:
    """Format a date or datetime as the dated subdirectory name (YYYY-MM-DD)."""
    if isinstance(when, datetime):
        when = when.date()
    return when.strftime(DATE_DIR_FORMAT)


def dated_raw_dir(
    when: date | datetime | None = None,
    settings: Settings | None = None,
    create: bool = True,
) -> Path:
    """Return data/raw/YYYY-MM-DD for the given date, creating it if requested."""
    if when is None:
        when = datetime.now(UTC)
    target = raw_data_dir(settings) / format_date_dir(when)
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target
