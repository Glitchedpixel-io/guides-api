"""Shared column mixins for the ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import SCHEMA_NAME


def fk(table: str, column: str = "id") -> str:
    """Build a schema-qualified foreign key target.

    Args:
        table: Unqualified table name.
        column: Column name on that table.

    Returns:
        str: e.g. ``gd.guides.id``.
    """
    return f"{SCHEMA_NAME}.{table}.{column}"


class TimestampedMixin:
    """Adds server-maintained ``created_at`` and ``updated_at`` columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
