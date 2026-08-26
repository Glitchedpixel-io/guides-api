"""Alembic environment.

The database URL comes from ``ALEMBIC_DATABASE_URL`` when set, falling back to the app's
own configuration. Deploy passes it as a step-level variable rather than putting it in the
service's ``.env``, so the migration role and the runtime role can differ.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, inspect, pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing the models package registers every table on the metadata. Without it,
# autogenerate produces an empty migration and reports success.
import app.models  # noqa: F401
from app.config.settings import get_config
from app.database import SCHEMA_NAME, Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _migration_database_url() -> str:
    """Resolve the URL migrations run against.

    Returns:
        str: An async SQLAlchemy URL.
    """
    override = os.environ.get("ALEMBIC_DATABASE_URL")
    if override:
        return override
    return get_config().database.url


def _include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    """Restrict autogenerate to this service's own schema.

    Args:
        name: The object's name.
        type_: The kind of object being considered.
        parent_names: Names of the object's parents.

    Returns:
        bool: True when the object belongs to this service.
    """
    if type_ == "schema":
        return name in (None, SCHEMA_NAME)
    return True


def run_migrations_offline() -> None:
    """Emit SQL for the migrations without connecting to a database."""
    context.configure(
        url=_migration_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=_include_name,
        version_table_schema=SCHEMA_NAME,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on an open connection.

    Args:
        connection: A live synchronous connection.
    """
    if not inspect(connection).has_schema(SCHEMA_NAME):
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_NAME}"'))

    # Close the transaction SQLAlchemy autobegan before Alembic starts its own. Without
    # this commit every migration is silently rolled back at the end of the run: alembic
    # reports success, and the schema is unchanged. control-api#301 lost a release to it.
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=_include_name,
        version_table_schema=SCHEMA_NAME,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Connect asynchronously and run the migrations."""
    configuration = config.get_section(config.config_ini_section) or {}
    # Injected directly rather than via set_main_option: ConfigParser would treat a `%`
    # in a password as interpolation and mangle the URL.
    configuration["sqlalchemy.url"] = _migration_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
