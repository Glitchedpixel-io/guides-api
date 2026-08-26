"""Guide and revision business logic, including the publish lifecycle."""

from __future__ import annotations

from app.repositories.protocols import GuideRepository, RevisionRepository
from app.schemas.enums import RevisionStatus
from app.schemas.guides import (
    GuideCreate,
    GuideCreateInternal,
    GuidePatch,
    GuidePatchInternal,
    GuideRead,
    RevisionCreate,
    RevisionCreateInternal,
    RevisionPatch,
    RevisionPatchInternal,
    RevisionRead,
)
from app.services.errors import InvalidTransitionError, RevisionNotEditableError

# Content may only change while a revision is a draft.
EDITABLE_STATUSES = frozenset({RevisionStatus.DRAFT})


class GuideService:
    """Create, read, and amend guide identities."""

    def __init__(self, guides: GuideRepository) -> None:
        """Bind the service to its repository.

        Args:
            guides: Storage for guide identities.
        """
        self._guides = guides

    async def create(self, payload: GuideCreate) -> GuideRead:
        """Create a guide.

        Args:
            payload: The guide to create.

        Returns:
            GuideRead: The stored guide.
        """
        return await self._guides.create(GuideCreateInternal(**payload.model_dump()))

    async def get(self, guide_id: int) -> GuideRead:
        """Fetch a guide by id.

        Args:
            guide_id: The guide's primary key.

        Returns:
            GuideRead: The stored guide.
        """
        return await self._guides.get(guide_id)

    async def get_by_slug(self, slug: str) -> GuideRead:
        """Fetch a guide by slug.

        Args:
            slug: The guide's URL-safe identifier.

        Returns:
            GuideRead: The stored guide.
        """
        return await self._guides.get_by_slug(slug)

    async def list_all(self) -> list[GuideRead]:
        """List every guide.

        Returns:
            list[GuideRead]: All stored guides.
        """
        return await self._guides.list_all()

    async def update(self, guide_id: int, payload: GuidePatch) -> GuideRead:
        """Amend a guide.

        Args:
            guide_id: The guide's primary key.
            payload: Fields to change.

        Returns:
            GuideRead: The updated guide.
        """
        return await self._guides.update(
            guide_id, GuidePatchInternal(**payload.model_dump(exclude_unset=True))
        )

    async def delete(self, guide_id: int) -> None:
        """Delete a guide and every revision beneath it.

        Args:
            guide_id: The guide's primary key.
        """
        await self._guides.delete(guide_id)


class RevisionService:
    """Create, amend, and publish guide revisions."""

    def __init__(self, guides: GuideRepository, revisions: RevisionRepository) -> None:
        """Bind the service to its repositories.

        Args:
            guides: Storage for guide identities.
            revisions: Storage for revisions.
        """
        self._guides = guides
        self._revisions = revisions

    async def create(self, guide_id: int, payload: RevisionCreate) -> RevisionRead:
        """Open a new draft revision of a guide.

        Args:
            guide_id: The owning guide.
            payload: The revision to create.

        Returns:
            RevisionRead: The new draft revision.

        Raises:
            NotFoundError: If the guide does not exist.
        """
        await self._guides.get(guide_id)
        return await self._revisions.create(
            RevisionCreateInternal(
                guide_id=guide_id, status=RevisionStatus.DRAFT, **payload.model_dump()
            )
        )

    async def get(self, revision_id: int) -> RevisionRead:
        """Fetch a revision.

        Args:
            revision_id: The revision's primary key.

        Returns:
            RevisionRead: The stored revision.
        """
        return await self._revisions.get(revision_id)

    async def list_for_guide(self, guide_id: int) -> list[RevisionRead]:
        """List a guide's revisions.

        Args:
            guide_id: The owning guide.

        Returns:
            list[RevisionRead]: The guide's revisions, oldest first.
        """
        return await self._revisions.list_for_guide(guide_id)

    async def update(self, revision_id: int, payload: RevisionPatch) -> RevisionRead:
        """Amend a draft revision.

        Args:
            revision_id: The revision's primary key.
            payload: Fields to change.

        Returns:
            RevisionRead: The updated revision.

        Raises:
            RevisionNotEditableError: If the revision is no longer a draft.
        """
        await self.assert_editable(revision_id)
        return await self._revisions.update(
            revision_id, RevisionPatchInternal(**payload.model_dump(exclude_unset=True))
        )

    async def delete(self, revision_id: int) -> None:
        """Delete a draft revision and its content.

        Args:
            revision_id: The revision's primary key.

        Raises:
            RevisionNotEditableError: If the revision has been published.
        """
        await self.assert_editable(revision_id)
        await self._revisions.delete(revision_id)

    async def publish(self, revision_id: int) -> RevisionRead:
        """Freeze a draft revision for issue.

        Args:
            revision_id: The revision's primary key.

        Returns:
            RevisionRead: The published revision.

        Raises:
            InvalidTransitionError: If the revision is not a draft.
        """
        revision = await self._revisions.get(revision_id)
        if revision.status is not RevisionStatus.DRAFT:
            raise InvalidTransitionError(
                f"revision {revision_id} is {revision.status.value}, so it cannot be published"
            )
        return await self._revisions.update(
            revision_id, RevisionPatchInternal(status=RevisionStatus.PUBLISHED)
        )

    async def archive(self, revision_id: int) -> RevisionRead:
        """Withdraw a published revision from use.

        Args:
            revision_id: The revision's primary key.

        Returns:
            RevisionRead: The archived revision.

        Raises:
            InvalidTransitionError: If the revision was never published.
        """
        revision = await self._revisions.get(revision_id)
        if revision.status is not RevisionStatus.PUBLISHED:
            raise InvalidTransitionError(
                f"revision {revision_id} is {revision.status.value}, so it cannot be archived"
            )
        return await self._revisions.update(
            revision_id, RevisionPatchInternal(status=RevisionStatus.ARCHIVED)
        )

    async def assert_editable(self, revision_id: int) -> RevisionRead:
        """Check a revision still accepts content changes.

        Args:
            revision_id: The revision's primary key.

        Returns:
            RevisionRead: The revision, when it is editable.

        Raises:
            NotFoundError: If no such revision exists.
            RevisionNotEditableError: If it is published or archived.
        """
        revision = await self._revisions.get(revision_id)
        if revision.status not in EDITABLE_STATUSES:
            raise RevisionNotEditableError(
                f"revision {revision_id} is {revision.status.value}; "
                "issue a new revision rather than editing an issued one"
            )
        return revision
