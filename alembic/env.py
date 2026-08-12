"""Alembic environment for the PostgreSQL schema."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from illinois_lottery_tracker import analytics_models, auth_models  # noqa: F401
from illinois_lottery_tracker.config import get_settings
from illinois_lottery_tracker.database_identity import (
    validate_identity_configuration,
    verify_connection_identity,
    verify_url_identity,
)
from illinois_lottery_tracker.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    environment = os.getenv("DATABASE_URL")
    if environment:
        return environment
    return get_settings().require_database_url()


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    settings = get_settings()
    validate_identity_configuration(settings)
    verify_url_identity(_database_url(), settings.expected_database_name)
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = get_settings()
    validate_identity_configuration(settings)
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        verify_connection_identity(connection, settings.expected_database_name)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
