"""Application configuration.

Import the frozen dataclasses from :mod:`app.config.schema` and the accessors from
:mod:`app.config.settings`. Nothing outside this package may import ``pydantic-settings``.
"""

from app.config.schema import (
    FRAME_WEIGHTS,
    AppConfig,
    DatabaseConfig,
    LoggingConfig,
    RenderConfig,
    SheetStyleConfig,
    SketchConfig,
    StorageConfig,
    SymbolLegendEntry,
)
from app.config.settings import (
    get_config,
    get_db_config,
    get_logging_config,
    get_render_config,
    get_sketch_config,
    get_storage_config,
)

__all__ = [
    # schema
    "FRAME_WEIGHTS",
    "AppConfig",
    "DatabaseConfig",
    "LoggingConfig",
    "RenderConfig",
    "SheetStyleConfig",
    "SketchConfig",
    "StorageConfig",
    "SymbolLegendEntry",
    # accessors
    "get_config",
    "get_db_config",
    "get_logging_config",
    "get_render_config",
    "get_sketch_config",
    "get_storage_config",
]
