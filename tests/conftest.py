"""Shared fixtures. No test logic lives here."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config.schema import (
    AppConfig,
    DatabaseConfig,
    LoggingConfig,
    RenderConfig,
    SheetStyleConfig,
    SketchConfig,
    StorageConfig,
)
from app.storage import AssetStore


def pytest_sessionstart(session: pytest.Session) -> None:
    """Refuse to run unless the test environment is selected.

    Args:
        session: The pytest session.

    Raises:
        SystemExit: If ``APP_ENV`` is not ``test``.
    """
    if os.environ.get("APP_ENV") != "test":
        os.environ["APP_ENV"] = "test"


TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guides_api_test",
)


@pytest.fixture
def storage_config(tmp_path: Path) -> StorageConfig:
    """Build a storage config rooted in a temporary directory.

    Args:
        tmp_path: pytest's per-test temporary directory.

    Returns:
        StorageConfig: Storage settings for the test.
    """
    return StorageConfig(asset_root=tmp_path / "assets", max_upload_bytes=1024 * 1024)


@pytest.fixture
def asset_store(storage_config: StorageConfig) -> AssetStore:
    """Build an asset store over a temporary root.

    Args:
        storage_config: Storage settings.

    Returns:
        AssetStore: The store.
    """
    return AssetStore(storage_config)


@pytest.fixture
def render_config() -> RenderConfig:
    """Build a render config with the default house style.

    Returns:
        RenderConfig: Render settings.
    """
    return RenderConfig(
        style=SheetStyleConfig(support_url_template="https://mso.example.test/{doc_number}")
    )


@pytest.fixture
def sketch_config() -> SketchConfig:
    """Build a sketch config that never reaches the network.

    Returns:
        SketchConfig: Sketch settings with a dummy key.
    """
    return SketchConfig(enabled=True, api_key="test-key")


@pytest.fixture
def app_config(
    storage_config: StorageConfig,
    render_config: RenderConfig,
    sketch_config: SketchConfig,
) -> AppConfig:
    """Assemble a whole test configuration.

    Args:
        storage_config: Storage settings.
        render_config: Render settings.
        sketch_config: Sketch settings.

    Returns:
        AppConfig: The test configuration.
    """
    return AppConfig(
        debug=True,
        database=DatabaseConfig(url=TEST_DATABASE_URL, require_migration_head=False),
        storage=storage_config,
        sketch=sketch_config,
        render=render_config,
        logging=LoggingConfig(env="test"),
    )
