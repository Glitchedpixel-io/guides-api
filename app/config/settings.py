"""Environment loading, and the only place ``pydantic-settings`` is allowed to appear.

A factory reads ``APP_ENV``, instantiates the matching ``BaseSettings`` subclass, and maps
it onto the frozen dataclasses in :mod:`app.config.schema`. The result is cached once per
process; every consumer depends on the dataclasses, never on this module.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.schema import (
    AppConfig,
    Effort,
    LogLevel,
    DatabaseConfig,
    LoggingConfig,
    RenderConfig,
    SheetStyleConfig,
    SketchConfig,
    StorageConfig,
)
from app.version import get_version


class _Settings(BaseSettings):
    """Development defaults, read from the environment and ``.env.development``."""

    model_config = SettingsConfigDict(
        env_prefix="GD_",
        env_file=".env.development",
        extra="ignore",
    )

    debug: bool = False

    # Database. Note which names are read here and which are NOT: `TEST_DATABASE_URL` is
    # deliberately absent, and is added back only in _TestSettings below. A dev container
    # or CI host commonly exports TEST_DATABASE_URL for whatever else it runs; if that name
    # won here, a production process on such a host would connect to a test database and
    # say nothing about it.
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/guides_api",
        validation_alias=AliasChoices("GD_DATABASE_URL", "DATABASE_URL"),
    )
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_require_migration_head: bool = True

    # Storage
    asset_root: Path = Path("./var/assets")
    max_upload_bytes: int = 20 * 1024 * 1024

    # Sketch redraw
    sketch_enabled: bool = True
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GD_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    sketch_model: str = "claude-opus-5"
    sketch_effort: Effort = "high"
    sketch_max_tokens: int = 32000
    sketch_timeout_seconds: float = 300.0
    sketch_prompt_version: str = "blueprint-v1"

    # Rendering / house style
    template_version: str = "blueprint-1.0"
    page_size: str = "letter"
    sheet_organisation: str = "Eldritch County"
    sheet_department: str = "Metrology Standards Office"
    sheet_document_kind: str = "Procedure Sheet"
    sheet_logo_path: Path | None = None
    sheet_frame_weight: str = "standard"
    sheet_plate_grid: bool = True
    sheet_registration_marks: bool = True
    sheet_footer_note: str = "HATCHED PANELS DENOTE SAFETY-CRITICAL CONTENT · DO NOT REDRAW BY HAND"
    sheet_retention_note: str = "RETAIN COMPLETED SHEET 7 YEARS · UNCONTROLLED WHEN PRINTED"
    sheet_support_url_template: str = ""

    # Observability
    log_level: LogLevel = "info"
    console_log_level: LogLevel = "info"
    logfire_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GD_LOGFIRE_TOKEN", "LOGFIRE_TOKEN"),
    )
    logfire_for_sqlalchemy: bool = False


class _TestSettings(_Settings):
    """Test-runner overrides.

    ``TEST_DATABASE_URL`` is honoured *only* here, and it outranks the others so an
    inherited ``DATABASE_URL`` can never point the test suite at a real database.
    """

    model_config = SettingsConfigDict(
        env_prefix="GD_",
        env_file=".env.test",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/guides_api_test",
        validation_alias=AliasChoices("TEST_DATABASE_URL", "GD_DATABASE_URL", "DATABASE_URL"),
    )


class _ProductionSettings(_Settings):
    """Production: real environment variables only, never a ``.env`` file on disk."""

    model_config = SettingsConfigDict(
        env_prefix="GD_",
        env_file=None,
        extra="ignore",
    )


def _build_database_config(s: _Settings) -> DatabaseConfig:
    """Map settings onto the database config group.

    Args:
        s: The loaded settings object.

    Returns:
        DatabaseConfig: The database configuration.
    """
    return DatabaseConfig(
        url=s.database_url,
        pool_size=s.database_pool_size,
        max_overflow=s.database_max_overflow,
        pool_timeout=s.database_pool_timeout,
        require_migration_head=s.database_require_migration_head,
    )


def _build_storage_config(s: _Settings) -> StorageConfig:
    """Map settings onto the storage config group.

    Args:
        s: The loaded settings object.

    Returns:
        StorageConfig: The storage configuration, with an absolute asset root.
    """
    return StorageConfig(
        asset_root=s.asset_root.expanduser().resolve(),
        max_upload_bytes=s.max_upload_bytes,
    )


def _build_sketch_config(s: _Settings) -> SketchConfig:
    """Map settings onto the sketch-redraw config group.

    Args:
        s: The loaded settings object.

    Returns:
        SketchConfig: The sketch configuration.
    """
    return SketchConfig(
        enabled=s.sketch_enabled,
        api_key=s.anthropic_api_key,
        model=s.sketch_model,
        effort=s.sketch_effort,
        max_tokens=s.sketch_max_tokens,
        timeout_seconds=s.sketch_timeout_seconds,
        prompt_version=s.sketch_prompt_version,
    )


def _build_render_config(s: _Settings) -> RenderConfig:
    """Map settings onto the render config group.

    Args:
        s: The loaded settings object.

    Returns:
        RenderConfig: The render configuration, including the house style.
    """
    style = SheetStyleConfig(
        organisation=s.sheet_organisation,
        department=s.sheet_department,
        document_kind=s.sheet_document_kind,
        logo_path=s.sheet_logo_path.expanduser().resolve() if s.sheet_logo_path else None,
        frame_weight=s.sheet_frame_weight,
        plate_grid=s.sheet_plate_grid,
        registration_marks=s.sheet_registration_marks,
        footer_note=s.sheet_footer_note,
        retention_note=s.sheet_retention_note,
        support_url_template=s.sheet_support_url_template,
    )
    return RenderConfig(
        template_version=s.template_version,
        page_size=s.page_size,
        style=style,
    )


def _build_logging_config(s: _Settings, env: str) -> LoggingConfig:
    """Map settings onto the logging config group.

    Args:
        s: The loaded settings object.
        env: The active ``APP_ENV`` value.

    Returns:
        LoggingConfig: The observability configuration.
    """
    return LoggingConfig(
        env=env,
        log_level=s.log_level,
        console_log_level=s.console_log_level,
        logfire_token=s.logfire_token,
        service_version=get_version(),
        logfire_for_sqlalchemy=s.logfire_for_sqlalchemy,
    )


def _load() -> AppConfig:
    """Read ``APP_ENV`` and build the full application configuration.

    Returns:
        AppConfig: The assembled configuration.
    """
    env = os.getenv("APP_ENV", "development").lower()
    match env:
        case "production":
            s: _Settings = _ProductionSettings()
        case "test":
            s = _TestSettings()
        case _:
            env = "development"
            s = _Settings()

    return AppConfig(
        debug=s.debug,
        database=_build_database_config(s),
        storage=_build_storage_config(s),
        sketch=_build_sketch_config(s),
        render=_build_render_config(s),
        logging=_build_logging_config(s, env),
    )


@lru_cache
def get_config() -> AppConfig:
    """Return the process-wide application configuration.

    Never call this at import time — an import-time call populates the cache before any
    ``dependency_overrides`` are in place and silently wins for the rest of the process.

    Returns:
        AppConfig: The cached configuration.
    """
    return _load()


def get_db_config() -> DatabaseConfig:
    """Return just the database config group.

    Returns:
        DatabaseConfig: The database configuration.
    """
    return get_config().database


def get_storage_config() -> StorageConfig:
    """Return just the storage config group.

    Returns:
        StorageConfig: The storage configuration.
    """
    return get_config().storage


def get_sketch_config() -> SketchConfig:
    """Return just the sketch-redraw config group.

    Returns:
        SketchConfig: The sketch configuration.
    """
    return get_config().sketch


def get_render_config() -> RenderConfig:
    """Return just the render config group.

    Returns:
        RenderConfig: The render configuration.
    """
    return get_config().render


def get_logging_config() -> LoggingConfig:
    """Return just the logging config group.

    Returns:
        LoggingConfig: The observability configuration.
    """
    return get_config().logging
