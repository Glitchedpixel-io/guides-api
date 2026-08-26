"""Asset, sketch-job, and render persistence against a real schema."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.asset_repo import (
    SQLAlchemyAssetRepository,
    SQLAlchemyRenderRepository,
    SQLAlchemySketchJobRepository,
)
from app.repositories.errors import NotFoundError
from app.repositories.guide_repo import SQLAlchemyGuideRepository, SQLAlchemyRevisionRepository
from app.repositories.step_repo import SQLAlchemyStepRepository
from app.schemas.assets import (
    AssetCreateInternal,
    RenderCreateInternal,
    SketchJobCreateInternal,
    SketchJobPatchInternal,
)
from app.schemas.enums import AssetKind, SketchJobStatus
from app.schemas.guides import GuideCreateInternal, RevisionCreateInternal
from app.schemas.steps import StepCreateInternal
from app.services.sketch_service import reap_stalled_jobs

pytestmark = [pytest.mark.integration]


async def _asset(session: AsyncSession, digest: str, kind: AssetKind = AssetKind.SKETCH) -> int:
    """Record an asset and return its id.

    Args:
        session: The test session.
        digest: A 64-character hex digest.
        kind: The asset's kind.

    Returns:
        int: The asset's primary key.
    """
    asset = await SQLAlchemyAssetRepository(session).create(
        AssetCreateInternal(
            kind=kind,
            content_type="image/png",
            storage_path=f"{digest[:2]}/{digest[2:4]}/{digest}.png",
            sha256=digest,
            byte_size=10,
        )
    )
    return asset.id


async def _step(session: AsyncSession) -> tuple[int, int]:
    """Create a guide, revision, and one step.

    Args:
        session: The test session.

    Returns:
        tuple[int, int]: The revision id and the step id.
    """
    guide = await SQLAlchemyGuideRepository(session).create(
        GuideCreateInternal(slug="jobs-guide", doc_number="D-1", title="T")
    )
    revision = await SQLAlchemyRevisionRepository(session).create(
        RevisionCreateInternal(
            guide_id=guide.id,
            rev_label="A",
            revision_date=date(2026, 8, 26),
            author_byline="R. Vane",
        )
    )
    step = await SQLAlchemyStepRepository(session).append(
        revision.id,
        StepCreateInternal(revision_id=revision.id, position=0, title="A step"),
    )
    return revision.id, step.id


class TestAssetRepository:
    """Asset metadata."""

    async def test_finds_an_asset_by_content_hash(self, db_session: AsyncSession) -> None:
        """Content addressing is what makes a repeated upload free.

        Args:
            db_session: The test session.
        """
        repo = SQLAlchemyAssetRepository(db_session)
        digest = "a" * 64
        created_id = await _asset(db_session, digest)
        found = await repo.find_by_sha256(digest)
        assert found is not None
        assert found.id == created_id

    async def test_unknown_hash_returns_none(self, db_session: AsyncSession) -> None:
        """An absent hash is not an error; it means "write it".

        Args:
            db_session: The test session.
        """
        assert await SQLAlchemyAssetRepository(db_session).find_by_sha256("f" * 64) is None

    async def test_missing_asset_raises(self, db_session: AsyncSession) -> None:
        """An unknown id is a domain NotFoundError.

        Args:
            db_session: The test session.
        """
        with pytest.raises(NotFoundError):
            await SQLAlchemyAssetRepository(db_session).get(999_999)


class TestSketchJobRepository:
    """Redraw job persistence and the startup reaper."""

    async def test_job_advances_through_its_states(self, db_session: AsyncSession) -> None:
        """A job is created pending and updated in place.

        Args:
            db_session: The test session.
        """
        _, step_id = await _step(db_session)
        source = await _asset(db_session, "b" * 64)
        repo = SQLAlchemySketchJobRepository(db_session)

        job = await repo.create(
            SketchJobCreateInternal(
                step_id=step_id,
                source_asset_id=source,
                model="claude-opus-5",
                prompt_version="blueprint-v1",
            )
        )
        assert job.status is SketchJobStatus.PENDING

        result = await _asset(db_session, "c" * 64, AssetKind.REDRAWN_SVG)
        finished = await repo.update(
            job.id,
            SketchJobPatchInternal(
                status=SketchJobStatus.SUCCEEDED,
                result_asset_id=result,
                notes="assumed symmetry",
                completed_at=datetime.now(timezone.utc),
            ),
        )
        assert finished.status is SketchJobStatus.SUCCEEDED
        assert finished.result_asset_id == result
        assert finished.notes == "assumed symmetry"

    async def test_lists_a_steps_attempts_newest_first(self, db_session: AsyncSession) -> None:
        """An author needs the latest attempt, not the first.

        Args:
            db_session: The test session.
        """
        _, step_id = await _step(db_session)
        repo = SQLAlchemySketchJobRepository(db_session)
        for index, digest in enumerate("de"):
            await repo.create(
                SketchJobCreateInternal(
                    step_id=step_id,
                    source_asset_id=await _asset(db_session, digest * 64),
                    model="claude-opus-5",
                    prompt_version=f"v{index}",
                )
            )
        jobs = await repo.list_for_step(step_id)
        assert [j.prompt_version for j in jobs] == ["v1", "v0"]

    async def test_reaper_requeues_jobs_left_running(self, db_session: AsyncSession) -> None:
        """A restart must not leave a job wedged on RUNNING forever.

        Args:
            db_session: The test session.
        """
        _, step_id = await _step(db_session)
        repo = SQLAlchemySketchJobRepository(db_session)
        job = await repo.create(
            SketchJobCreateInternal(
                step_id=step_id,
                source_asset_id=await _asset(db_session, "1" * 64),
                model="claude-opus-5",
                prompt_version="blueprint-v1",
            )
        )
        await repo.update(job.id, SketchJobPatchInternal(status=SketchJobStatus.RUNNING))

        requeued = await reap_stalled_jobs(repo)

        assert [j.id for j in requeued] == [job.id]
        assert (await repo.get(job.id)).status is SketchJobStatus.PENDING

    async def test_reaper_leaves_finished_jobs_alone(self, db_session: AsyncSession) -> None:
        """Only in-flight work is re-queued; a failure stays a failure.

        Args:
            db_session: The test session.
        """
        _, step_id = await _step(db_session)
        repo = SQLAlchemySketchJobRepository(db_session)
        job = await repo.create(
            SketchJobCreateInternal(
                step_id=step_id,
                source_asset_id=await _asset(db_session, "2" * 64),
                model="claude-opus-5",
                prompt_version="blueprint-v1",
            )
        )
        await repo.update(
            job.id, SketchJobPatchInternal(status=SketchJobStatus.FAILED, error="declined")
        )

        assert await reap_stalled_jobs(repo) == []
        assert (await repo.get(job.id)).status is SketchJobStatus.FAILED


class TestRenderRepository:
    """Render records."""

    async def test_latest_returns_the_most_recent_render(self, db_session: AsyncSession) -> None:
        """Downloading a sheet serves the newest one produced.

        Args:
            db_session: The test session.
        """
        revision_id, _ = await _step(db_session)
        repo = SQLAlchemyRenderRepository(db_session)
        for index, digest in enumerate("34"):
            await repo.create(
                RenderCreateInternal(
                    revision_id=revision_id,
                    pdf_asset_id=await _asset(db_session, digest * 64, AssetKind.PDF),
                    template_version=f"blueprint-1.{index}",
                    page_count=3 + index,
                    rendered_at=datetime.now(timezone.utc),
                )
            )
        latest = await repo.latest_for_revision(revision_id)
        assert latest is not None
        assert latest.template_version == "blueprint-1.1"
        assert len(await repo.list_for_revision(revision_id)) == 2

    async def test_latest_is_none_before_any_render(self, db_session: AsyncSession) -> None:
        """An unrendered revision has no sheet to serve.

        Args:
            db_session: The test session.
        """
        revision_id, _ = await _step(db_session)
        assert await SQLAlchemyRenderRepository(db_session).latest_for_revision(revision_id) is None

    async def test_missing_render_raises(self, db_session: AsyncSession) -> None:
        """An unknown render id is a domain NotFoundError.

        Args:
            db_session: The test session.
        """
        with pytest.raises(NotFoundError):
            await SQLAlchemyRenderRepository(db_session).get(999_999)
