"""Async engine, declarative base, and session factory.

One physical database per environment, one schema name everywhere. Schema ownership
belongs to Alembic — nothing here calls ``create_all()``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Final, TypedDict

import logfire
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config.schema import DatabaseConfig
from app.config.settings import get_config

SCHEMA_NAME: Final[str] = "gd"


class Base(DeclarativeBase):
    """Declarative base for every ORM model in this service."""

    __table_args__: Any = {"schema": SCHEMA_NAME}


def _create_engine_from_config(config: DatabaseConfig) -> AsyncEngine:
    """Build an async engine from a database config.

    Args:
        config: The database configuration group.

    Returns:
        AsyncEngine: A configured, not-yet-connected engine.
    """
    return create_async_engine(
        config.url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout,
        pool_pre_ping=True,
        echo=False,
    )


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first use.

    Returns:
        AsyncEngine: The cached engine.
    """
    app_config = get_config()
    engine = _create_engine_from_config(app_config.database)
    if app_config.logging.logfire_for_sqlalchemy:
        logfire.instrument_sqlalchemy(engine=engine)
    return engine


class SessionKwargs(TypedDict):
    """Session options, as a TypedDict so unpacking keeps the inferred type."""

    autoflush: bool
    autocommit: bool
    future: bool
    expire_on_commit: bool


# Single source of truth, shared with the integration-test fixture. Keeping one copy is
# deliberate: a fixture that diverges on `expire_on_commit` hides real lazy-load bugs,
# because the test session keeps attributes loaded that production would have expired.
SESSION_KWARGS: Final[SessionKwargs] = {
    "autoflush": False,
    "autocommit": False,
    "future": True,
    "expire_on_commit": True,
}


def AsyncSessionLocal() -> AsyncSession:  # noqa: N802 - factory named like a sessionmaker
    """Open a new session bound to the process-wide engine.

    Returns:
        AsyncSession: A fresh session. The caller owns its lifetime.
    """
    return async_sessionmaker(bind=get_engine(), **SESSION_KWARGS)()
