"""Integration fixtures: a real Postgres schema, built by Alembic.

The schema comes from ``alembic upgrade head`` rather than ``Base.metadata.create_all()``.
Those two can differ — a migration that fails to reproduce the models is exactly the bug
worth catching, and ``create_all`` would hide it by building the models directly.

Alembic runs in a subprocess because ``env.py`` calls ``asyncio.run()`` internally and
cannot be invoked from inside a running event loop.
"""

from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import SCHEMA_NAME, SESSION_KWARGS
from tests.conftest import TEST_DATABASE_URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# FK-ordered: children before parents. Kept by hand because TRUNCATE order matters and a
# generated order would silently reorder itself when a relationship changes.
TRUNCATE_SQL = text(f"""
    TRUNCATE TABLE
        {SCHEMA_NAME}.step_callouts,
        {SCHEMA_NAME}.sketch_jobs,
        {SCHEMA_NAME}.renders,
        {SCHEMA_NAME}.steps,
        {SCHEMA_NAME}.bom_items,
        {SCHEMA_NAME}.required_tools,
        {SCHEMA_NAME}.safety_warnings,
        {SCHEMA_NAME}.guide_revisions,
        {SCHEMA_NAME}.guides,
        {SCHEMA_NAME}.assets
    RESTART IDENTITY CASCADE
    """)


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Build the schema with Alembic and yield an engine over it.

    Yields:
        AsyncEngine: An engine bound to a migrated test database.
    """
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with eng.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment-dependent
        await eng.dispose()
        pytest.skip(f"no test database at TEST_DATABASE_URL: {exc}")

    async with eng.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_NAME}" CASCADE'))

    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        check=True,
        cwd=PROJECT_ROOT,
        env={
            **__import__("os").environ,
            "ALEMBIC_DATABASE_URL": TEST_DATABASE_URL,
            "APP_ENV": "test",
        },
        capture_output=True,
    )

    yield eng

    async with eng.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA_NAME}" CASCADE'))
    await eng.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield a session, then truncate every table.

    ``SESSION_KWARGS`` is imported from the application rather than restated. A fixture
    that diverges on ``expire_on_commit`` keeps attributes loaded that production would
    have expired, hiding real lazy-load faults.

    Args:
        engine: The migrated engine.

    Yields:
        AsyncSession: A session for one test.
    """
    factory = async_sessionmaker(engine, **SESSION_KWARGS)
    async with factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.execute(TRUNCATE_SQL)
