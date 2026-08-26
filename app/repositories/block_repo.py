"""SQLAlchemy repositories for the three optional front-matter blocks.

BOM lines, required tools and safety warnings are the same shape — an ordered child
collection of a revision — so the ordering machinery lives once in
:class:`_OrderedChildRepository` and each concrete class supplies only its types.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.models.blocks import BomItem, RequiredTool, SafetyWarning
from app.repositories.base import SQLAlchemyBaseRepository
from app.repositories.errors import InvalidDataError, NotFoundError
from app.repositories.protocols import (
    BomItemRepository,
    RequiredToolRepository,
    SafetyWarningRepository,
)
from app.schemas.blocks import (
    BomItemCreateInternal,
    BomItemPatchInternal,
    BomItemRead,
    RequiredToolCreateInternal,
    RequiredToolPatchInternal,
    RequiredToolRead,
    SafetyWarningCreateInternal,
    SafetyWarningPatchInternal,
    SafetyWarningRead,
)


class _OrderedChildRepository(SQLAlchemyBaseRepository):
    """Shared CRUD and reordering for an ordered child collection of a revision.

    Subclasses set :attr:`model`, :attr:`read_model` and :attr:`label`.
    """

    model: Any
    read_model: type[BaseModel]
    label: str

    def _to_read(self, orm: Any) -> Any:
        """Convert an ORM row to this collection's read schema.

        Args:
            orm: The loaded ORM row.

        Returns:
            Any: The corresponding read model.
        """
        return self.read_model.model_validate(orm, from_attributes=True)

    async def _load(self, item_id: int) -> Any:
        """Load one row, or raise.

        Args:
            item_id: The row's primary key.

        Returns:
            Any: The loaded ORM row.

        Raises:
            NotFoundError: If no such row exists.
        """
        orm = await self.db.scalar(select(self.model).where(self.model.id == item_id))
        if orm is None:
            raise NotFoundError(f"{self.label} {item_id} not found")
        return orm

    async def append(self, revision_id: int, item: BaseModel) -> Any:
        """Insert a row at the end of the revision's collection.

        Args:
            revision_id: The owning revision.
            item: The row to create; its ``position`` is overwritten.

        Returns:
            Any: The stored row.
        """
        payload = item.model_dump()
        payload["revision_id"] = revision_id
        payload["position"] = await self._next_position(self.model, revision_id=revision_id)
        orm = self.model(**payload)
        self.db.add(orm)
        await self._safe_commit()
        await self.db.refresh(orm)
        return self._to_read(orm)

    async def get(self, item_id: int) -> Any:
        """Fetch one row.

        Args:
            item_id: The row's primary key.

        Returns:
            Any: The stored row.

        Raises:
            NotFoundError: If no such row exists.
        """
        return self._to_read(await self._load(item_id))

    async def list_for_revision(self, revision_id: int) -> list[Any]:
        """List a revision's rows in order.

        Args:
            revision_id: The owning revision.

        Returns:
            list[Any]: The rows, ordered by position.
        """
        rows = await self.db.scalars(
            select(self.model)
            .where(self.model.revision_id == revision_id)
            .order_by(self.model.position)
        )
        return [self._to_read(r) for r in rows]

    async def update(self, item_id: int, update: BaseModel) -> Any:
        """Apply a partial update to a row.

        Args:
            item_id: The row's primary key.
            update: Fields to change; unset fields are left alone.

        Returns:
            Any: The updated row.

        Raises:
            NotFoundError: If no such row exists.
        """
        orm = await self._load(item_id)
        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(orm, key, value)
        await self._safe_commit()
        await self.db.refresh(orm)
        return self._to_read(orm)

    async def delete(self, item_id: int) -> None:
        """Delete a row and close the gap it left.

        Args:
            item_id: The row's primary key.

        Raises:
            NotFoundError: If no such row exists.
        """
        orm = await self._load(item_id)
        revision_id = orm.revision_id
        await self.db.delete(orm)
        await self._safe_flush()

        remaining = list(
            await self.db.scalars(
                select(self.model)
                .where(self.model.revision_id == revision_id)
                .order_by(self.model.position)
            )
        )
        await self._apply_positions({r.id: i for i, r in enumerate(remaining, start=1)}, remaining)
        await self._safe_commit()

    async def reorder(self, revision_id: int, order: dict[int, int]) -> list[Any]:
        """Renumber the revision's rows in one transaction.

        Args:
            revision_id: The owning revision.
            order: Map of row id to new 1-based position.

        Returns:
            list[Any]: The rows in their new order.

        Raises:
            InvalidDataError: If the map is not a complete permutation.
        """
        rows = list(
            await self.db.scalars(
                select(self.model)
                .where(self.model.revision_id == revision_id)
                .order_by(self.model.position)
            )
        )
        known = {r.id for r in rows}
        given = set(order)
        if given != known:
            raise InvalidDataError(
                f"reorder must name every {self.label} exactly once "
                f"(missing={sorted(known - given)}, unknown={sorted(given - known)})"
            )
        if sorted(order.values()) != list(range(1, len(order) + 1)):
            raise InvalidDataError(f"positions must be a permutation of 1..{len(order)}")

        await self._apply_positions(order, rows)
        await self._safe_commit()
        return await self.list_for_revision(revision_id)

    async def _apply_positions(self, order: dict[int, int], rows: list[Any]) -> None:
        """Write new positions in two phases to dodge the uniqueness constraint.

        Assigning final positions directly collides whenever two rows swap, so everything
        is parked on negative positions first; every intermediate state stays legal.

        Args:
            order: Map of row id to new position.
            rows: The rows being renumbered.
        """
        for row in rows:
            row.position = -row.position
        await self._safe_flush()
        for row in rows:
            if row.id in order:
                row.position = order[row.id]
        await self._safe_flush()


class SQLAlchemyBomItemRepository(_OrderedChildRepository, BomItemRepository):
    """Postgres-backed storage for bill-of-materials lines."""

    model = BomItem
    read_model = BomItemRead
    label = "bom item"

    async def append(self, revision_id: int, item: BomItemCreateInternal) -> BomItemRead:  # type: ignore[override]
        """Append a BOM line.

        Args:
            revision_id: The owning revision.
            item: The line to create.

        Returns:
            BomItemRead: The stored line.
        """
        return await super().append(revision_id, item)  # type: ignore[no-any-return]

    async def update(self, item_id: int, update: BomItemPatchInternal) -> BomItemRead:  # type: ignore[override]
        """Update a BOM line.

        Args:
            item_id: The line's primary key.
            update: Fields to change.

        Returns:
            BomItemRead: The updated line.
        """
        return await super().update(item_id, update)  # type: ignore[no-any-return]


class SQLAlchemyRequiredToolRepository(_OrderedChildRepository, RequiredToolRepository):
    """Postgres-backed storage for required-tool lines."""

    model = RequiredTool
    read_model = RequiredToolRead
    label = "required tool"

    async def append(  # type: ignore[override]
        self, revision_id: int, item: RequiredToolCreateInternal
    ) -> RequiredToolRead:
        """Append a required tool.

        Args:
            revision_id: The owning revision.
            item: The tool to create.

        Returns:
            RequiredToolRead: The stored tool.
        """
        return await super().append(revision_id, item)  # type: ignore[no-any-return]

    async def update(  # type: ignore[override]
        self, item_id: int, update: RequiredToolPatchInternal
    ) -> RequiredToolRead:
        """Update a required tool.

        Args:
            item_id: The tool's primary key.
            update: Fields to change.

        Returns:
            RequiredToolRead: The updated tool.
        """
        return await super().update(item_id, update)  # type: ignore[no-any-return]


class SQLAlchemySafetyWarningRepository(_OrderedChildRepository, SafetyWarningRepository):
    """Postgres-backed storage for safety warnings."""

    model = SafetyWarning
    read_model = SafetyWarningRead
    label = "safety warning"

    async def append(  # type: ignore[override]
        self, revision_id: int, item: SafetyWarningCreateInternal
    ) -> SafetyWarningRead:
        """Append a safety warning.

        Args:
            revision_id: The owning revision.
            item: The warning to create.

        Returns:
            SafetyWarningRead: The stored warning.
        """
        return await super().append(revision_id, item)  # type: ignore[no-any-return]

    async def update(  # type: ignore[override]
        self, item_id: int, update: SafetyWarningPatchInternal
    ) -> SafetyWarningRead:
        """Update a safety warning.

        Args:
            item_id: The warning's primary key.
            update: Fields to change.

        Returns:
            SafetyWarningRead: The updated warning.
        """
        return await super().update(item_id, update)  # type: ignore[no-any-return]
