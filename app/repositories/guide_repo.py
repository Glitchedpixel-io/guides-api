"""SQLAlchemy repositories for guides and revisions."""

from __future__ import annotations

from sqlalchemy import select

from app.models.guide import Guide, GuideRevision
from app.repositories.base import SQLAlchemyBaseRepository
from app.repositories.errors import NotFoundError
from app.repositories.protocols import GuideRepository, RevisionRepository
from app.schemas.guides import (
    GuideCreateInternal,
    GuidePatchInternal,
    GuideRead,
    RevisionCreateInternal,
    RevisionPatchInternal,
    RevisionRead,
)


class SQLAlchemyGuideRepository(SQLAlchemyBaseRepository, GuideRepository):
    """Postgres-backed storage for guide identities."""

    async def create(self, guide: GuideCreateInternal) -> GuideRead:
        """Insert a new guide.

        Args:
            guide: The guide to create.

        Returns:
            GuideRead: The stored guide.

        Raises:
            DuplicateEntityError: If the slug is already taken.
        """
        orm = Guide(**guide.model_dump())
        self.db.add(orm)
        await self._safe_commit()
        await self.db.refresh(orm)
        return GuideRead.model_validate(orm, from_attributes=True)

    async def get(self, guide_id: int) -> GuideRead:
        """Fetch one guide by id.

        Args:
            guide_id: The guide's primary key.

        Returns:
            GuideRead: The stored guide.

        Raises:
            NotFoundError: If no such guide exists.
        """
        orm = await self.db.scalar(select(Guide).where(Guide.id == guide_id))
        if orm is None:
            raise NotFoundError(f"guide {guide_id} not found")
        return GuideRead.model_validate(orm, from_attributes=True)

    async def get_by_slug(self, slug: str) -> GuideRead:
        """Fetch one guide by its slug.

        Args:
            slug: The guide's URL-safe identifier.

        Returns:
            GuideRead: The stored guide.

        Raises:
            NotFoundError: If no such guide exists.
        """
        orm = await self.db.scalar(select(Guide).where(Guide.slug == slug))
        if orm is None:
            raise NotFoundError(f"guide '{slug}' not found")
        return GuideRead.model_validate(orm, from_attributes=True)

    async def list_all(self) -> list[GuideRead]:
        """List every guide, newest first.

        Returns:
            list[GuideRead]: All stored guides.
        """
        rows = await self.db.scalars(select(Guide).order_by(Guide.created_at.desc()))
        return [GuideRead.model_validate(r, from_attributes=True) for r in rows]

    async def update(self, guide_id: int, update: GuidePatchInternal) -> GuideRead:
        """Apply a partial update to a guide.

        Args:
            guide_id: The guide's primary key.
            update: Fields to change; unset fields are left alone.

        Returns:
            GuideRead: The updated guide.

        Raises:
            NotFoundError: If no such guide exists.
            DuplicateEntityError: If the new slug is already taken.
        """
        orm = await self.db.scalar(select(Guide).where(Guide.id == guide_id))
        if orm is None:
            raise NotFoundError(f"guide {guide_id} not found")
        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(orm, key, value)
        await self._safe_commit()
        await self.db.refresh(orm)
        return GuideRead.model_validate(orm, from_attributes=True)

    async def delete(self, guide_id: int) -> None:
        """Delete a guide and, by cascade, every revision beneath it.

        Args:
            guide_id: The guide's primary key.

        Raises:
            NotFoundError: If no such guide exists.
        """
        orm = await self.db.scalar(select(Guide).where(Guide.id == guide_id))
        if orm is None:
            raise NotFoundError(f"guide {guide_id} not found")
        await self.db.delete(orm)
        await self._safe_commit()


class SQLAlchemyRevisionRepository(SQLAlchemyBaseRepository, RevisionRepository):
    """Postgres-backed storage for guide revisions."""

    async def create(self, revision: RevisionCreateInternal) -> RevisionRead:
        """Insert a new revision.

        Args:
            revision: The revision to create.

        Returns:
            RevisionRead: The stored revision.

        Raises:
            DuplicateEntityError: If that revision label already exists for the guide.
        """
        orm = GuideRevision(**revision.model_dump())
        self.db.add(orm)
        await self._safe_commit()
        await self.db.refresh(orm)
        return RevisionRead.model_validate(orm, from_attributes=True)

    async def get(self, revision_id: int) -> RevisionRead:
        """Fetch one revision by id.

        Args:
            revision_id: The revision's primary key.

        Returns:
            RevisionRead: The stored revision.

        Raises:
            NotFoundError: If no such revision exists.
        """
        orm = await self.db.scalar(select(GuideRevision).where(GuideRevision.id == revision_id))
        if orm is None:
            raise NotFoundError(f"revision {revision_id} not found")
        return RevisionRead.model_validate(orm, from_attributes=True)

    async def list_for_guide(self, guide_id: int) -> list[RevisionRead]:
        """List a guide's revisions, oldest first.

        The order matters: this list is also what the sheet's printed revision history
        renders from, and that table reads chronologically.

        Args:
            guide_id: The owning guide's primary key.

        Returns:
            list[RevisionRead]: The guide's revisions.
        """
        rows = await self.db.scalars(
            select(GuideRevision)
            .where(GuideRevision.guide_id == guide_id)
            .order_by(GuideRevision.revision_date, GuideRevision.id)
        )
        return [RevisionRead.model_validate(r, from_attributes=True) for r in rows]

    async def update(self, revision_id: int, update: RevisionPatchInternal) -> RevisionRead:
        """Apply a partial update to a revision.

        Args:
            revision_id: The revision's primary key.
            update: Fields to change; unset fields are left alone.

        Returns:
            RevisionRead: The updated revision.

        Raises:
            NotFoundError: If no such revision exists.
        """
        orm = await self.db.scalar(select(GuideRevision).where(GuideRevision.id == revision_id))
        if orm is None:
            raise NotFoundError(f"revision {revision_id} not found")
        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(orm, key, value)
        await self._safe_commit()
        await self.db.refresh(orm)
        return RevisionRead.model_validate(orm, from_attributes=True)

    async def delete(self, revision_id: int) -> None:
        """Delete a revision and every content row beneath it.

        Args:
            revision_id: The revision's primary key.

        Raises:
            NotFoundError: If no such revision exists.
        """
        orm = await self.db.scalar(select(GuideRevision).where(GuideRevision.id == revision_id))
        if orm is None:
            raise NotFoundError(f"revision {revision_id} not found")
        await self.db.delete(orm)
        await self._safe_commit()
