"""Shared repository base and SQLAlchemy error mapping."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.errors import (
    DatabaseLockedError,
    DuplicateEntityError,
    InvalidDataError,
    RepositoryError,
    RequiredFieldError,
)


def map_sqla_error(exc: SQLAlchemyError) -> RepositoryError:
    """Translate a SQLAlchemy exception into a domain error.

    Args:
        exc: The exception raised by the driver.

    Returns:
        RepositoryError: The closest domain error.
    """
    text = str(getattr(exc, "orig", exc)).lower()

    if isinstance(exc, IntegrityError):
        if "unique" in text or "duplicate key" in text:
            return DuplicateEntityError(str(getattr(exc, "orig", exc)))
        if "not null" in text or "null value" in text:
            return RequiredFieldError(str(getattr(exc, "orig", exc)))
        return InvalidDataError(str(getattr(exc, "orig", exc)))

    if isinstance(exc, DataError):
        return InvalidDataError(str(getattr(exc, "orig", exc)))

    if "read-only" in text or "permission denied" in text:
        return DatabaseLockedError(str(getattr(exc, "orig", exc)))

    return InvalidDataError(str(getattr(exc, "orig", exc)))


class SQLAlchemyBaseRepository:
    """Holds the session and centralises commit/flush error handling.

    Every write goes through :meth:`_safe_commit` or :meth:`_safe_flush` so the session is
    always rolled back on failure — otherwise the next statement on that session fails
    with ``PendingRollbackError`` and the real cause is lost.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to a session.

        Args:
            db: The session this repository reads and writes through.
        """
        self.db = db

    async def _safe_commit(self) -> None:
        """Commit, mapping any failure onto a domain error.

        Raises:
            RepositoryError: If the commit was rejected.
        """
        try:
            await self.db.commit()
        except SQLAlchemyError as exc:
            await self.db.rollback()
            raise map_sqla_error(exc) from exc
        except Exception:
            await self.db.rollback()
            raise

    async def _safe_flush(self) -> None:
        """Flush, mapping any failure onto a domain error.

        Raises:
            RepositoryError: If the flush was rejected.
        """
        try:
            await self.db.flush()
        except SQLAlchemyError as exc:
            await self.db.rollback()
            raise map_sqla_error(exc) from exc
        except Exception:
            await self.db.rollback()
            raise

    async def _next_position(self, model: Any, **filters: Any) -> int:
        """Return the next free 1-based position within an ordered collection.

        Args:
            model: The ORM class holding a ``position`` column.
            **filters: Equality filters scoping the collection, e.g. ``revision_id=3``.

        Returns:
            int: One past the current maximum, or 1 when the collection is empty.
        """
        stmt = select(func.max(model.position))
        for column, value in filters.items():
            stmt = stmt.where(getattr(model, column) == value)
        current = await self.db.scalar(stmt)
        return int(current or 0) + 1
