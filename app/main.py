"""ASGI entry point.

Deliberately thin: logging is configured before the app exists, and assembly lives in
``app_factory`` so tests can build an app around a test configuration without importing
this module's side effects.
"""

from __future__ import annotations

from app.app_factory import create_app
from app.config.settings import get_config
from app.logging import setup_logging

setup_logging()

api = create_app(get_config())

# `uvicorn app.main:app` is the more common incantation; keep both names working.
app = api
