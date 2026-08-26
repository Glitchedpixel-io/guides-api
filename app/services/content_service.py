"""Content editing: steps, callouts, and the three ordered front-matter blocks.

Every mutation goes through :meth:`RevisionService.assert_editable` first, so a published
sheet can never be altered underneath the copy someone has already printed.
"""

from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar, cast

from app.repositories.protocols import StepRepository
from pydantic import BaseModel

from app.schemas.base import ReorderRequest
from app.schemas.steps import (
    CalloutCreate,
    CalloutCreateInternal,
    CalloutPatch,
    CalloutPatchInternal,
    CalloutRead,
    StepCreate,
    StepCreateInternal,
    StepPatch,
    StepPatchInternal,
    StepRead,
)
from app.services.guide_service import RevisionService


def order_map(request: ReorderRequest) -> dict[int, int]:
    """Flatten a reorder request into an id-to-position map.

    Args:
        request: The requested ordering.

    Returns:
        dict[int, int]: Row id mapped to its new position.
    """
    return {item.id: item.position for item in request.items}


class StepService:
    """Add, amend, reorder, and remove a revision's steps."""

    def __init__(self, steps: StepRepository, revisions: RevisionService) -> None:
        """Bind the service to its collaborators.

        Args:
            steps: Storage for steps and callouts.
            revisions: Used to enforce the draft-only editing rule.
        """
        self._steps = steps
        self._revisions = revisions

    async def add(self, revision_id: int, payload: StepCreate) -> StepRead:
        """Append a step to a revision.

        Args:
            revision_id: The owning revision.
            payload: The step to add.

        Returns:
            StepRead: The stored step.

        Raises:
            RevisionNotEditableError: If the revision is no longer a draft.
        """
        await self._revisions.assert_editable(revision_id)
        internal = StepCreateInternal(revision_id=revision_id, position=0, **payload.model_dump())
        return await self._steps.append(revision_id, internal)

    async def get(self, step_id: int) -> StepRead:
        """Fetch a step and its callouts.

        Args:
            step_id: The step's primary key.

        Returns:
            StepRead: The stored step.
        """
        return await self._steps.get(step_id)

    async def assert_editable(self, step_id: int) -> StepRead:
        """Check a step still accepts changes, via its owning revision.

        Args:
            step_id: The step's primary key.

        Returns:
            StepRead: The step, when it is editable.

        Raises:
            NotFoundError: If no such step exists.
            RevisionNotEditableError: If its revision is published or archived.
        """
        step = await self._steps.get(step_id)
        await self._revisions.assert_editable(step.revision_id)
        return step

    async def list_for_revision(self, revision_id: int) -> list[StepRead]:
        """List a revision's steps in order.

        Args:
            revision_id: The owning revision.

        Returns:
            list[StepRead]: The steps.
        """
        return await self._steps.list_for_revision(revision_id)

    async def update(self, step_id: int, payload: StepPatch) -> StepRead:
        """Amend a step.

        Args:
            step_id: The step's primary key.
            payload: Fields to change.

        Returns:
            StepRead: The updated step.

        Raises:
            RevisionNotEditableError: If the owning revision is no longer a draft.
        """
        step = await self._steps.get(step_id)
        await self._revisions.assert_editable(step.revision_id)
        return await self._steps.update(
            step_id, StepPatchInternal(**payload.model_dump(exclude_unset=True))
        )

    async def delete(self, step_id: int) -> None:
        """Remove a step and close the gap in the sequence.

        Args:
            step_id: The step's primary key.

        Raises:
            RevisionNotEditableError: If the owning revision is no longer a draft.
        """
        step = await self._steps.get(step_id)
        await self._revisions.assert_editable(step.revision_id)
        await self._steps.delete(step_id)

    async def reorder(self, revision_id: int, request: ReorderRequest) -> list[StepRead]:
        """Renumber a revision's steps.

        Args:
            revision_id: The owning revision.
            request: The complete new ordering.

        Returns:
            list[StepRead]: The steps in their new order.

        Raises:
            RevisionNotEditableError: If the revision is no longer a draft.
            InvalidDataError: If the request is not a complete permutation.
        """
        await self._revisions.assert_editable(revision_id)
        return await self._steps.reorder(revision_id, order_map(request))

    async def set_image(self, step_id: int, asset_id: int | None) -> StepRead:
        """Attach or clear a step's drawing.

        Existing callouts are cleared alongside a change of drawing: they are positioned
        against the artwork they annotate, so carrying them onto a different drawing points
        them at nothing.

        Args:
            step_id: The step's primary key.
            asset_id: The drawing to attach, or ``None`` to clear.

        Returns:
            StepRead: The updated step.

        Raises:
            RevisionNotEditableError: If the owning revision is no longer a draft.
        """
        step = await self._steps.get(step_id)
        await self._revisions.assert_editable(step.revision_id)
        if step.image_asset_id != asset_id:
            await self._steps.clear_callouts(step_id)
        return await self._steps.update(step_id, StepPatchInternal(image_asset_id=asset_id))

    async def add_callout(self, step_id: int, payload: CalloutCreate) -> CalloutRead:
        """Add a callout to a step's plate.

        Args:
            step_id: The step's primary key.
            payload: The callout to add.

        Returns:
            CalloutRead: The stored callout.

        Raises:
            RevisionNotEditableError: If the owning revision is no longer a draft.
        """
        step = await self._steps.get(step_id)
        await self._revisions.assert_editable(step.revision_id)
        return await self._steps.add_callout(
            CalloutCreateInternal(step_id=step_id, **payload.model_dump())
        )

    async def update_callout(self, callout_id: int, payload: CalloutPatch) -> CalloutRead:
        """Amend a callout.

        Args:
            callout_id: The callout's primary key.
            payload: Fields to change.

        Returns:
            CalloutRead: The updated callout.

        Raises:
            RevisionNotEditableError: If the owning revision is no longer a draft.
        """
        callout = await self._steps.get_callout(callout_id)
        step = await self._steps.get(callout.step_id)
        await self._revisions.assert_editable(step.revision_id)
        return await self._steps.update_callout(
            callout_id, CalloutPatchInternal(**payload.model_dump(exclude_unset=True))
        )

    async def delete_callout(self, callout_id: int) -> None:
        """Remove a callout.

        Args:
            callout_id: The callout's primary key.

        Raises:
            RevisionNotEditableError: If the owning revision is no longer a draft.
        """
        callout = await self._steps.get_callout(callout_id)
        step = await self._steps.get(callout.step_id)
        await self._revisions.assert_editable(step.revision_id)
        await self._steps.delete_callout(callout_id)


ReadT = TypeVar("ReadT", bound=BaseModel)


class _OrderedBlockRepository(Protocol):
    """The shape every ordered front-matter block repository shares."""

    async def append(self, revision_id: int, item: Any) -> Any: ...
    async def get(self, item_id: int) -> Any: ...
    async def list_for_revision(self, revision_id: int) -> list[ReadT]: ...
    async def update(self, item_id: int, update: Any) -> Any: ...
    async def delete(self, item_id: int) -> None: ...
    async def reorder(self, revision_id: int, order: dict[int, int]) -> list[Any]: ...


class BlockService(Generic[ReadT]):
    """Editing for one ordered front-matter block.

    Instantiated once per block kind — BOM, tools, warnings — because the three differ only
    in their types, not in their behaviour. Generic over the read model so callers get a
    concrete type rather than ``Any``: without the parameter every router handling a block
    would be returning an unchecked value from a typed endpoint.
    """

    def __init__(
        self,
        repository: _OrderedBlockRepository,
        revisions: RevisionService,
        create_internal: type[Any],
        patch_internal: type[Any],
        read_model: type[ReadT],
    ) -> None:
        """Bind the service to its repository and schema types.

        Args:
            repository: Storage for this block kind.
            revisions: Used to enforce the draft-only editing rule.
            create_internal: The repository's create schema.
            patch_internal: The repository's patch schema.
            read_model: The read schema this block returns.
        """
        self._repository = repository
        self._revisions = revisions
        self._create_internal = create_internal
        self._patch_internal = patch_internal
        self._read_model = read_model

    async def add(self, revision_id: int, payload: Any) -> ReadT:
        """Append an entry to the block.

        Args:
            revision_id: The owning revision.
            payload: The entry to add.

        Returns:
            Any: The stored entry.

        Raises:
            RevisionNotEditableError: If the revision is no longer a draft.
        """
        await self._revisions.assert_editable(revision_id)
        internal = self._create_internal(
            revision_id=revision_id, position=0, **payload.model_dump()
        )
        return cast(ReadT, await self._repository.append(revision_id, internal))

    async def list_for_revision(self, revision_id: int) -> list[ReadT]:
        """List the block's entries in order.

        Args:
            revision_id: The owning revision.

        Returns:
            list[ReadT]: The entries.
        """
        return cast("list[ReadT]", await self._repository.list_for_revision(revision_id))

    async def update(self, item_id: int, payload: Any) -> ReadT:
        """Amend an entry.

        Args:
            item_id: The entry's primary key.
            payload: Fields to change.

        Returns:
            ReadT: The updated entry.

        Raises:
            RevisionNotEditableError: If the owning revision is no longer a draft.
        """
        item = await self._repository.get(item_id)
        await self._revisions.assert_editable(item.revision_id)
        return cast(
            ReadT,
            await self._repository.update(
                item_id, self._patch_internal(**payload.model_dump(exclude_unset=True))
            ),
        )

    async def delete(self, item_id: int) -> None:
        """Remove an entry and close the gap.

        Args:
            item_id: The entry's primary key.

        Raises:
            RevisionNotEditableError: If the owning revision is no longer a draft.
        """
        item = await self._repository.get(item_id)
        await self._revisions.assert_editable(item.revision_id)
        await self._repository.delete(item_id)

    async def reorder(self, revision_id: int, request: ReorderRequest) -> list[ReadT]:
        """Renumber the block's entries.

        Args:
            revision_id: The owning revision.
            request: The complete new ordering.

        Returns:
            list[ReadT]: The entries in their new order.

        Raises:
            RevisionNotEditableError: If the revision is no longer a draft.
            InvalidDataError: If the request is not a complete permutation.
        """
        await self._revisions.assert_editable(revision_id)
        return cast("list[ReadT]", await self._repository.reorder(revision_id, order_map(request)))
