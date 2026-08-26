"""SQLAlchemy repository for steps and their drawing-plate callouts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.step import Step, StepCallout
from app.repositories.base import SQLAlchemyBaseRepository
from app.repositories.errors import InvalidDataError, NotFoundError
from app.repositories.protocols import StepRepository
from app.schemas.steps import (
    CalloutCreateInternal,
    CalloutPatchInternal,
    CalloutRead,
    StepCreateInternal,
    StepPatchInternal,
    StepRead,
)


class SQLAlchemyStepRepository(SQLAlchemyBaseRepository, StepRepository):
    """Postgres-backed storage for steps and callouts."""

    @staticmethod
    def _to_read(orm: Step) -> StepRead:
        """Convert a loaded step ORM row to its read schema.

        Args:
            orm: A step with its ``callouts`` relationship already loaded.

        Returns:
            StepRead: The step and its callouts.
        """
        return StepRead(
            id=orm.id,
            revision_id=orm.revision_id,
            position=orm.position,
            title=orm.title,
            instructions=orm.instructions,
            est_minutes=orm.est_minutes,
            plate_layout=orm.plate_layout,
            side_note=orm.side_note,
            image_asset_id=orm.image_asset_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            callouts=[CalloutRead.model_validate(c, from_attributes=True) for c in orm.callouts],
        )

    async def _load(self, step_id: int) -> Step:
        """Load one step with its callouts, or raise.

        Args:
            step_id: The step's primary key.

        Returns:
            Step: The loaded ORM row.

        Raises:
            NotFoundError: If no such step exists.
        """
        orm = await self.db.scalar(
            select(Step).where(Step.id == step_id).options(selectinload(Step.callouts))
        )
        if orm is None:
            raise NotFoundError(f"step {step_id} not found")
        return orm

    async def create(self, step: StepCreateInternal) -> StepRead:
        """Insert a step at an explicit position.

        Args:
            step: The step to create, including its position.

        Returns:
            StepRead: The stored step.

        Raises:
            DuplicateEntityError: If that position is already taken in the revision.
        """
        orm = Step(**step.model_dump())
        self.db.add(orm)
        # Flush to obtain the generated id, and read it *before* committing. With
        # `expire_on_commit=True` every attribute on `orm` is expired by the commit, so
        # touching `orm.id` afterwards triggers a lazy refresh from synchronous context
        # and raises MissingGreenlet. Holding the plain int avoids the reload entirely.
        await self._safe_flush()
        step_id = int(orm.id)
        await self._safe_commit()
        return self._to_read(await self._load(step_id))

    async def append(self, revision_id: int, step: StepCreateInternal) -> StepRead:
        """Insert a step at the end of the revision's sequence.

        Args:
            revision_id: The owning revision.
            step: The step to create; its ``position`` is overwritten.

        Returns:
            StepRead: The stored step.
        """
        payload = step.model_dump()
        payload["revision_id"] = revision_id
        payload["position"] = await self._next_position(Step, revision_id=revision_id)
        orm = Step(**payload)
        self.db.add(orm)
        # See `create`: read the generated id after the flush and before the commit.
        await self._safe_flush()
        step_id = int(orm.id)
        await self._safe_commit()
        return self._to_read(await self._load(step_id))

    async def get(self, step_id: int) -> StepRead:
        """Fetch one step with its callouts.

        Args:
            step_id: The step's primary key.

        Returns:
            StepRead: The stored step.

        Raises:
            NotFoundError: If no such step exists.
        """
        return self._to_read(await self._load(step_id))

    async def list_for_revision(self, revision_id: int) -> list[StepRead]:
        """List a revision's steps in strict order.

        Args:
            revision_id: The owning revision.

        Returns:
            list[StepRead]: The steps, ordered by position.
        """
        rows = await self.db.scalars(
            select(Step)
            .where(Step.revision_id == revision_id)
            .order_by(Step.position)
            .options(selectinload(Step.callouts))
        )
        return [self._to_read(r) for r in rows]

    async def update(self, step_id: int, update: StepPatchInternal) -> StepRead:
        """Apply a partial update to a step.

        Args:
            step_id: The step's primary key.
            update: Fields to change; unset fields are left alone.

        Returns:
            StepRead: The updated step.

        Raises:
            NotFoundError: If no such step exists.
        """
        orm = await self._load(step_id)
        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(orm, key, value)
        await self._safe_commit()
        return self._to_read(await self._load(step_id))

    async def delete(self, step_id: int) -> None:
        """Delete a step, then close the gap it left in the sequence.

        Args:
            step_id: The step's primary key.

        Raises:
            NotFoundError: If no such step exists.
        """
        orm = await self._load(step_id)
        revision_id = orm.revision_id
        await self.db.delete(orm)
        await self._safe_flush()

        # Renumber what is left so positions stay 1..n with no holes. A gap is not wrong
        # in the database, but it prints as "STEP 1, STEP 3" on the sheet.
        remaining = list(
            await self.db.scalars(
                select(Step).where(Step.revision_id == revision_id).order_by(Step.position)
            )
        )
        await self._apply_positions({s.id: i for i, s in enumerate(remaining, start=1)}, remaining)
        await self._safe_commit()

    async def reorder(self, revision_id: int, order: dict[int, int]) -> list[StepRead]:
        """Renumber a revision's steps in one transaction.

        Args:
            revision_id: The owning revision.
            order: Map of step id to new 1-based position.

        Returns:
            list[StepRead]: The steps in their new order.

        Raises:
            InvalidDataError: If the map does not name every step exactly once, or the
                positions are not a permutation of 1..n.
        """
        steps = list(
            await self.db.scalars(
                select(Step).where(Step.revision_id == revision_id).order_by(Step.position)
            )
        )
        _validate_permutation(order, {s.id for s in steps})
        await self._apply_positions(order, steps)
        await self._safe_commit()
        return await self.list_for_revision(revision_id)

    async def _apply_positions(self, order: dict[int, int], rows: list[Step]) -> None:
        """Write new positions in two phases to dodge the uniqueness constraint.

        ``unique (revision_id, position)`` means assigning final positions directly
        collides whenever two rows swap. Parking everything on negative positions first
        keeps every intermediate state legal.

        Args:
            order: Map of step id to new position.
            rows: The step rows being renumbered.
        """
        for row in rows:
            row.position = -row.position
        await self._safe_flush()
        for row in rows:
            if row.id in order:
                row.position = order[row.id]
        await self._safe_flush()

    async def add_callout(self, callout: CalloutCreateInternal) -> CalloutRead:
        """Attach a callout to a step.

        Args:
            callout: The callout to create.

        Returns:
            CalloutRead: The stored callout.

        Raises:
            DuplicateEntityError: If that index is already used on the step.
        """
        orm = StepCallout(**callout.model_dump())
        self.db.add(orm)
        await self._safe_commit()
        await self.db.refresh(orm)
        return CalloutRead.model_validate(orm, from_attributes=True)

    async def get_callout(self, callout_id: int) -> CalloutRead:
        """Fetch one callout.

        Args:
            callout_id: The callout's primary key.

        Returns:
            CalloutRead: The stored callout.

        Raises:
            NotFoundError: If no such callout exists.
        """
        orm = await self.db.scalar(select(StepCallout).where(StepCallout.id == callout_id))
        if orm is None:
            raise NotFoundError(f"callout {callout_id} not found")
        return CalloutRead.model_validate(orm, from_attributes=True)

    async def update_callout(self, callout_id: int, update: CalloutPatchInternal) -> CalloutRead:
        """Apply a partial update to a callout.

        Args:
            callout_id: The callout's primary key.
            update: Fields to change; unset fields are left alone.

        Returns:
            CalloutRead: The updated callout.

        Raises:
            NotFoundError: If no such callout exists.
        """
        orm = await self.db.scalar(select(StepCallout).where(StepCallout.id == callout_id))
        if orm is None:
            raise NotFoundError(f"callout {callout_id} not found")
        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(orm, key, value)
        await self._safe_commit()
        await self.db.refresh(orm)
        return CalloutRead.model_validate(orm, from_attributes=True)

    async def delete_callout(self, callout_id: int) -> None:
        """Delete one callout.

        Args:
            callout_id: The callout's primary key.

        Raises:
            NotFoundError: If no such callout exists.
        """
        orm = await self.db.scalar(select(StepCallout).where(StepCallout.id == callout_id))
        if orm is None:
            raise NotFoundError(f"callout {callout_id} not found")
        await self.db.delete(orm)
        await self._safe_commit()

    async def clear_callouts(self, step_id: int) -> None:
        """Remove every callout from a step.

        Used when a step's image is replaced: callouts are positioned against the drawing
        they annotate, so keeping them across a new drawing points them at nothing.

        Args:
            step_id: The step's primary key.
        """
        rows = await self.db.scalars(select(StepCallout).where(StepCallout.step_id == step_id))
        for row in rows:
            await self.db.delete(row)
        await self._safe_commit()


def _validate_permutation(order: dict[int, int], known_ids: set[int]) -> None:
    """Check a reorder request names every row once and uses positions 1..n.

    Args:
        order: Map of row id to new position.
        known_ids: The ids that actually belong to the collection.

    Raises:
        InvalidDataError: If ids are missing, unknown, or positions are not 1..n.
    """
    given = set(order)
    if given != known_ids:
        missing = sorted(known_ids - given)
        unknown = sorted(given - known_ids)
        raise InvalidDataError(
            f"reorder must name every member exactly once (missing={missing}, unknown={unknown})"
        )
    if sorted(order.values()) != list(range(1, len(order) + 1)):
        raise InvalidDataError(f"positions must be a permutation of 1..{len(order)}")
