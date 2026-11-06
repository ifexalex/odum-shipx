"""Alembic environment configuration.

Database DDL migrations are defined in tasks 05a–05c.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_url() -> str:
    # Pin the driver to psycopg2 explicitly: SQLAlchemy 2.1 changed the default
    # DBAPI for `postgresql://` from psycopg2 to psycopg (v3), which this project
    # does not install (it uses psycopg2-binary). Without the `+psycopg2` the
    # migrate step fails with "No module named 'psycopg'" under SQLAlchemy >= 2.1
    # — in CI and in the production migrate Lambda alike.
    return (
        f"postgresql+psycopg2://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
        f"@{os.environ['DATABASE_HOST']}:{os.environ.get('DATABASE_PORT', '5432')}"
        f"/{os.environ['DATABASE_NAME']}"
    )


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
