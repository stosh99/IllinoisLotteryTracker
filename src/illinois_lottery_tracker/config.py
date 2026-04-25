"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_RAW_DATA_DIR = "data/raw"


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    raw_data_dir: str

    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Copy .env.example to .env and configure it."
            )
        return self.database_url


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    """Load settings from a .env file (if present) plus the process environment."""
    if env_file is None:
        candidate = _project_root() / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
    else:
        load_dotenv(env_file, override=False)

    return Settings(
        database_url=os.getenv("DATABASE_URL") or None,
        raw_data_dir=os.getenv("RAW_DATA_DIR") or DEFAULT_RAW_DATA_DIR,
    )


def get_settings() -> Settings:
    return load_settings()
