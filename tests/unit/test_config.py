"""Configuration loading, and which environment variable wins where."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import _load, get_config

pytestmark = pytest.mark.unit

PROD_URL = "postgresql+asyncpg://prod:prod@prod-host:5432/guides_api"
TEST_URL = "postgresql+asyncpg://test:test@test-host:5432/testdb"


@pytest.fixture(autouse=True)
def clear_config_cache() -> None:
    """Drop the cached configuration so each test loads fresh."""
    get_config.cache_clear()


def test_production_ignores_test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stray ``TEST_DATABASE_URL`` must never redirect production.

    Dev containers and CI hosts commonly export ``TEST_DATABASE_URL`` for whatever else
    they run. If that name won in production, the service would connect to a test database
    and say nothing about it — which is exactly what happened during development here.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TEST_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("GD_DATABASE_URL", PROD_URL)

    assert _load().database.url == PROD_URL


def test_test_environment_prefers_test_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under the test runner, ``TEST_DATABASE_URL`` outranks everything.

    The inverse hazard: an inherited ``DATABASE_URL`` pointing the suite at a real
    database, which then gets truncated between tests.
    """
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("DATABASE_URL", PROD_URL)

    assert _load().database.url == TEST_URL


def test_unknown_environment_falls_back_to_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo in ``APP_ENV`` gets development defaults, not production behaviour.

    Args:
        monkeypatch: Environment patcher.
    """
    monkeypatch.setenv("APP_ENV", "staging-ish")
    assert _load().logging.env == "development"


def test_asset_root_is_resolved_to_an_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A relative asset root would move with the process's working directory.

    Args:
        monkeypatch: Environment patcher.
        tmp_path: A temporary directory.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GD_ASSET_ROOT", "./relative/assets")
    assert _load().storage.asset_root.is_absolute()


def test_house_style_is_configuration_not_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sheet furniture comes from config, so changing it does not touch any guide.

    Args:
        monkeypatch: Environment patcher.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GD_SHEET_ORGANISATION", "Acme Works")
    monkeypatch.setenv("GD_SHEET_PLATE_GRID", "false")
    monkeypatch.setenv("GD_TEMPLATE_VERSION", "blueprint-2.0")

    render = _load().render
    assert render.style.organisation == "Acme Works"
    assert render.style.plate_grid is False
    assert render.template_version == "blueprint-2.0"


def test_config_is_cached_once_per_process() -> None:
    """The accessor is cached, so config is read once rather than per request."""
    assert get_config() is get_config()


def test_sketch_key_falls_back_to_the_conventional_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain ``ANTHROPIC_API_KEY`` is honoured, as the SDK's own convention.

    Args:
        monkeypatch: Environment patcher.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-value")
    assert _load().sketch.api_key == "sk-test-value"
