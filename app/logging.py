"""Logfire configuration.

Called once, before the app is constructed. ``send_to_logfire="if-token-present"`` means
tests and local development are silent without a token rather than failing.
"""

from __future__ import annotations

import logfire

from app.config.settings import get_logging_config


def setup_logging() -> None:
    """Configure Logfire from the logging config group."""
    config = get_logging_config()
    logfire.configure(
        token=config.logfire_token,
        environment=config.env,
        min_level=config.log_level,
        send_to_logfire="if-token-present",
        service_name="guides-api",
        service_version=config.service_version,
        console=logfire.ConsoleOptions(
            include_timestamps=False, min_log_level=config.console_log_level
        ),
    )
