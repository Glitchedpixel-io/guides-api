"""SQLAlchemy repositories for assets, sketch jobs, and renders."""

from __future__ import annotations

from sqlalchemy import select

from app.models.asset import Asset, Render, SketchJob
from app.repositories.base import SQLAlchemyBaseRepository
from app.repositories.errors import NotFoundError
from app.repositories.protocols import AssetRepository, RenderRepository, SketchJobRepository
from app.schemas.assets import (
    AssetCreateInternal,
    AssetRead,
    RenderCreateInternal,
    RenderRead,
    SketchJobCreateInternal,
    SketchJobPatchInternal,
    SketchJobRead,
)
from app.schemas.enums import SketchJobStatus


class SQLAlchemyAssetRepository(SQLAlchemyBaseRepository, AssetRepository):
    """Postgres-backed storage for stored-file metadata."""

    async def create(self, asset: AssetCreateInternal) -> AssetRead:
        """Record a stored file.

        Args:
            asset: The metadata to store.

        Returns:
            AssetRead: The stored asset.

        Raises:
            DuplicateEntityError: If that storage path is already recorded.
        """
        orm = Asset(**asset.model_dump())
        self.db.add(orm)
        await self._safe_commit()
        await self.db.refresh(orm)
        return AssetRead.model_validate(orm, from_attributes=True)

    async def get(self, asset_id: int) -> AssetRead:
        """Fetch one asset.

        Args:
            asset_id: The asset's primary key.

        Returns:
            AssetRead: The stored asset.

        Raises:
            NotFoundError: If no such asset exists.
        """
        orm = await self.db.scalar(select(Asset).where(Asset.id == asset_id))
        if orm is None:
            raise NotFoundError(f"asset {asset_id} not found")
        return AssetRead.model_validate(orm, from_attributes=True)

    async def find_by_sha256(self, sha256: str) -> AssetRead | None:
        """Look up an asset by content hash.

        Storage is content-addressed, so re-uploading identical bytes should reuse the
        existing row rather than write a second copy of the same file.

        Args:
            sha256: Hex digest of the file's contents.

        Returns:
            AssetRead | None: The matching asset, or ``None``.
        """
        orm = await self.db.scalar(select(Asset).where(Asset.sha256 == sha256).limit(1))
        return AssetRead.model_validate(orm, from_attributes=True) if orm else None


class SQLAlchemySketchJobRepository(SQLAlchemyBaseRepository, SketchJobRepository):
    """Postgres-backed storage for sketch-redraw jobs."""

    async def create(self, job: SketchJobCreateInternal) -> SketchJobRead:
        """Queue a redraw job.

        Args:
            job: The job to create.

        Returns:
            SketchJobRead: The queued job.
        """
        orm = SketchJob(**job.model_dump())
        self.db.add(orm)
        await self._safe_commit()
        await self.db.refresh(orm)
        return SketchJobRead.model_validate(orm, from_attributes=True)

    async def get(self, job_id: int) -> SketchJobRead:
        """Fetch one job.

        Args:
            job_id: The job's primary key.

        Returns:
            SketchJobRead: The stored job.

        Raises:
            NotFoundError: If no such job exists.
        """
        orm = await self.db.scalar(select(SketchJob).where(SketchJob.id == job_id))
        if orm is None:
            raise NotFoundError(f"sketch job {job_id} not found")
        return SketchJobRead.model_validate(orm, from_attributes=True)

    async def list_for_step(self, step_id: int) -> list[SketchJobRead]:
        """List every redraw attempt for a step, newest first.

        Args:
            step_id: The step's primary key.

        Returns:
            list[SketchJobRead]: The step's jobs.
        """
        rows = await self.db.scalars(
            select(SketchJob).where(SketchJob.step_id == step_id).order_by(SketchJob.id.desc())
        )
        return [SketchJobRead.model_validate(r, from_attributes=True) for r in rows]

    async def list_by_status(self, status: SketchJobStatus) -> list[SketchJobRead]:
        """List jobs in a given state.

        The startup reaper uses this to find work abandoned by a restart.

        Args:
            status: The state to select.

        Returns:
            list[SketchJobRead]: Matching jobs, oldest first.
        """
        rows = await self.db.scalars(
            select(SketchJob).where(SketchJob.status == status).order_by(SketchJob.id)
        )
        return [SketchJobRead.model_validate(r, from_attributes=True) for r in rows]

    async def update(self, job_id: int, update: SketchJobPatchInternal) -> SketchJobRead:
        """Advance a job's state.

        Args:
            job_id: The job's primary key.
            update: Fields to change; unset fields are left alone.

        Returns:
            SketchJobRead: The updated job.

        Raises:
            NotFoundError: If no such job exists.
        """
        orm = await self.db.scalar(select(SketchJob).where(SketchJob.id == job_id))
        if orm is None:
            raise NotFoundError(f"sketch job {job_id} not found")
        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(orm, key, value)
        await self._safe_commit()
        await self.db.refresh(orm)
        return SketchJobRead.model_validate(orm, from_attributes=True)


class SQLAlchemyRenderRepository(SQLAlchemyBaseRepository, RenderRepository):
    """Postgres-backed storage for produced PDFs."""

    async def create(self, render: RenderCreateInternal) -> RenderRead:
        """Record a render.

        Args:
            render: The render to store.

        Returns:
            RenderRead: The stored render.
        """
        orm = Render(**render.model_dump())
        self.db.add(orm)
        await self._safe_commit()
        await self.db.refresh(orm)
        return RenderRead.model_validate(orm, from_attributes=True)

    async def get(self, render_id: int) -> RenderRead:
        """Fetch one render.

        Args:
            render_id: The render's primary key.

        Returns:
            RenderRead: The stored render.

        Raises:
            NotFoundError: If no such render exists.
        """
        orm = await self.db.scalar(select(Render).where(Render.id == render_id))
        if orm is None:
            raise NotFoundError(f"render {render_id} not found")
        return RenderRead.model_validate(orm, from_attributes=True)

    async def list_for_revision(self, revision_id: int) -> list[RenderRead]:
        """List every render of a revision, newest first.

        Args:
            revision_id: The revision's primary key.

        Returns:
            list[RenderRead]: The revision's renders.
        """
        rows = await self.db.scalars(
            select(Render).where(Render.revision_id == revision_id).order_by(Render.id.desc())
        )
        return [RenderRead.model_validate(r, from_attributes=True) for r in rows]

    async def latest_for_revision(self, revision_id: int) -> RenderRead | None:
        """Return the most recent render of a revision.

        Args:
            revision_id: The revision's primary key.

        Returns:
            RenderRead | None: The latest render, or ``None`` if never rendered.
        """
        orm = await self.db.scalar(
            select(Render)
            .where(Render.revision_id == revision_id)
            .order_by(Render.id.desc())
            .limit(1)
        )
        return RenderRead.model_validate(orm, from_attributes=True) if orm else None
