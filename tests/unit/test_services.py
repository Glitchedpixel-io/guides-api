"""Service-layer rules, with repositories faked at the protocol boundary."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, create_autospec

import pytest
from pydantic import ValidationError

from app.config.schema import SketchConfig
from app.repositories.errors import InvalidDataError
from app.repositories.protocols import (
    GuideRepository,
    RevisionRepository,
    SketchJobRepository,
    StepRepository,
)
from app.repositories.step_repo import _validate_permutation
from app.schemas.assets import SketchJobRead
from app.schemas.enums import LeaderDir, RevisionStatus, SketchJobStatus
from app.schemas.steps import CalloutCreate, StepCreate, StepPatch
from app.services.content_service import StepService, order_map
from app.services.errors import (
    InvalidTransitionError,
    RevisionNotEditableError,
    SketchUnavailableError,
)
from app.services.guide_service import RevisionService
from app.services.sketch_service import SketchService, reap_stalled_jobs
from app.sketch.client import (
    RedrawOutput,
    SketchRefusedError,
    SuggestedCallout,
    UnsupportedSketchFormatError,
)
from app.schemas.base import OrderedItem, ReorderRequest
from tests.factories import NOW, SAMPLE_SVG, make_revision, make_step

pytestmark = pytest.mark.unit


@pytest.fixture
def revisions() -> AsyncMock:
    """Build a faked revision repository.

    Returns:
        AsyncMock: A repository honouring the protocol's method set.
    """
    return create_autospec(RevisionRepository, instance=True, spec_set=True)


@pytest.fixture
def guides() -> AsyncMock:
    """Build a faked guide repository.

    Returns:
        AsyncMock: A repository honouring the protocol's method set.
    """
    return create_autospec(GuideRepository, instance=True, spec_set=True)


class TestRevisionLifecycle:
    """Publishing freezes content; that is the whole point of the lifecycle."""

    async def test_publish_moves_a_draft_to_published(
        self, guides: AsyncMock, revisions: AsyncMock
    ) -> None:
        """A draft publishes.

        Args:
            guides: Faked guide repository.
            revisions: Faked revision repository.
        """
        revisions.get.return_value = make_revision(status=RevisionStatus.DRAFT)
        revisions.update.return_value = make_revision(status=RevisionStatus.PUBLISHED)

        result = await RevisionService(guides, revisions).publish(10)

        assert result.status is RevisionStatus.PUBLISHED
        assert revisions.update.await_args.args[1].status is RevisionStatus.PUBLISHED

    @pytest.mark.parametrize("status", [RevisionStatus.PUBLISHED, RevisionStatus.ARCHIVED])
    async def test_publish_refuses_anything_not_a_draft(
        self, guides: AsyncMock, revisions: AsyncMock, status: RevisionStatus
    ) -> None:
        """Re-publishing an issued revision is refused.

        Args:
            guides: Faked guide repository.
            revisions: Faked revision repository.
            status: A non-draft status.
        """
        revisions.get.return_value = make_revision(status=status)
        with pytest.raises(InvalidTransitionError):
            await RevisionService(guides, revisions).publish(10)
        revisions.update.assert_not_awaited()

    async def test_archive_requires_a_published_revision(
        self, guides: AsyncMock, revisions: AsyncMock
    ) -> None:
        """A draft cannot be archived; it was never in use.

        Args:
            guides: Faked guide repository.
            revisions: Faked revision repository.
        """
        revisions.get.return_value = make_revision(status=RevisionStatus.DRAFT)
        with pytest.raises(InvalidTransitionError):
            await RevisionService(guides, revisions).archive(10)

    async def test_editing_a_published_revision_is_refused(
        self, guides: AsyncMock, revisions: AsyncMock
    ) -> None:
        """Published content is frozen so an issued sheet stays reproducible.

        Args:
            guides: Faked guide repository.
            revisions: Faked revision repository.
        """
        revisions.get.return_value = make_revision(status=RevisionStatus.PUBLISHED)
        with pytest.raises(RevisionNotEditableError, match="issue a new revision"):
            await RevisionService(guides, revisions).assert_editable(10)

    async def test_a_draft_is_editable(self, guides: AsyncMock, revisions: AsyncMock) -> None:
        """A draft passes the editability check.

        Args:
            guides: Faked guide repository.
            revisions: Faked revision repository.
        """
        draft = make_revision(status=RevisionStatus.DRAFT)
        revisions.get.return_value = draft
        assert await RevisionService(guides, revisions).assert_editable(10) == draft


class TestStepService:
    """Step editing, and the draft-only rule it inherits."""

    @pytest.fixture
    def steps(self) -> AsyncMock:
        """Build a faked step repository.

        Returns:
            AsyncMock: A repository honouring the protocol's method set.
        """
        return create_autospec(StepRepository, instance=True, spec_set=True)

    @pytest.fixture
    def draft_revisions(self, guides: AsyncMock, revisions: AsyncMock) -> RevisionService:
        """Build a revision service whose revision is always an editable draft.

        Args:
            guides: Faked guide repository.
            revisions: Faked revision repository.

        Returns:
            RevisionService: A service over draft content.
        """
        revisions.get.return_value = make_revision(status=RevisionStatus.DRAFT)
        return RevisionService(guides, revisions)

    async def test_add_appends_rather_than_inserting(
        self, steps: AsyncMock, draft_revisions: RevisionService
    ) -> None:
        """A new step goes on the end; reordering is a separate, atomic operation.

        Args:
            steps: Faked step repository.
            draft_revisions: A service over draft content.
        """
        steps.append.return_value = make_step(1)
        await StepService(steps, draft_revisions).add(10, StepCreate(title="Seat the part"))
        steps.append.assert_awaited_once()

    async def test_add_is_refused_on_a_published_revision(
        self, steps: AsyncMock, guides: AsyncMock, revisions: AsyncMock
    ) -> None:
        """Content cannot be added to an issued revision.

        Args:
            steps: Faked step repository.
            guides: Faked guide repository.
            revisions: Faked revision repository.
        """
        revisions.get.return_value = make_revision(status=RevisionStatus.PUBLISHED)
        service = StepService(steps, RevisionService(guides, revisions))
        with pytest.raises(RevisionNotEditableError):
            await service.add(10, StepCreate(title="Too late"))
        steps.append.assert_not_awaited()

    async def test_changing_the_drawing_clears_its_callouts(
        self, steps: AsyncMock, draft_revisions: RevisionService
    ) -> None:
        """Callouts are positioned against the drawing they annotate.

        Carrying them onto a different drawing would leave numbered bubbles pointing at
        whatever happens to be underneath them.

        Args:
            steps: Faked step repository.
            draft_revisions: A service over draft content.
        """
        steps.get.return_value = make_step(1, image_asset_id=501)
        steps.update.return_value = make_step(1, image_asset_id=999)

        await StepService(steps, draft_revisions).set_image(101, 999)

        steps.clear_callouts.assert_awaited_once_with(101)

    async def test_reattaching_the_same_drawing_keeps_callouts(
        self, steps: AsyncMock, draft_revisions: RevisionService
    ) -> None:
        """A no-op image change must not silently discard the author's callouts.

        Args:
            steps: Faked step repository.
            draft_revisions: A service over draft content.
        """
        steps.get.return_value = make_step(1, image_asset_id=501)
        steps.update.return_value = make_step(1, image_asset_id=501)

        await StepService(steps, draft_revisions).set_image(101, 501)

        steps.clear_callouts.assert_not_awaited()

    async def test_update_checks_the_owning_revision(
        self, steps: AsyncMock, guides: AsyncMock, revisions: AsyncMock
    ) -> None:
        """A step's editability comes from its revision, not from the step.

        Args:
            steps: Faked step repository.
            guides: Faked guide repository.
            revisions: Faked revision repository.
        """
        steps.get.return_value = make_step(1)
        revisions.get.return_value = make_revision(status=RevisionStatus.ARCHIVED)
        service = StepService(steps, RevisionService(guides, revisions))
        with pytest.raises(RevisionNotEditableError):
            await service.update(101, StepPatch(title="new"))


class TestReorderValidation:
    """A reorder must be a complete permutation."""

    def test_accepts_a_complete_permutation(self) -> None:
        """Naming every row once, using 1..n, is valid."""
        _validate_permutation({1: 2, 2: 1, 3: 3}, {1, 2, 3})

    def test_rejects_a_partial_reorder(self) -> None:
        """Omitting a row is ambiguous about where it should end up."""
        with pytest.raises(InvalidDataError, match="missing"):
            _validate_permutation({1: 1, 2: 2}, {1, 2, 3})

    def test_rejects_unknown_ids(self) -> None:
        """A row from another revision cannot be placed in this one."""
        with pytest.raises(InvalidDataError, match="unknown"):
            _validate_permutation({1: 1, 99: 2}, {1, 2})

    @pytest.mark.parametrize("positions", [{1: 1, 2: 1}, {1: 0, 2: 1}, {1: 2, 2: 3}])
    def test_rejects_positions_that_are_not_one_to_n(self, positions: dict[int, int]) -> None:
        """Duplicate, zero-based, or gapped positions are refused.

        Args:
            positions: An invalid position map.
        """
        with pytest.raises(InvalidDataError, match="permutation"):
            _validate_permutation(positions, set(positions))

    def test_order_map_flattens_the_request(self) -> None:
        """The request maps cleanly onto the repository's argument."""
        request = ReorderRequest(
            items=[OrderedItem(id=7, position=2), OrderedItem(id=8, position=1)]
        )
        assert order_map(request) == {7: 2, 8: 1}


class TestSketchService:
    """Redraw orchestration, with the model and repositories faked."""

    @pytest.fixture
    def jobs(self) -> AsyncMock:
        """Build a faked job repository.

        Returns:
            AsyncMock: A repository honouring the protocol's method set.
        """
        return create_autospec(SketchJobRepository, instance=True, spec_set=True)

    @staticmethod
    def _job(**overrides: object) -> SketchJobRead:
        """Build a job read model.

        Args:
            **overrides: Field values to replace.

        Returns:
            SketchJobRead: The fixture job.
        """
        data: dict[str, object] = {
            "id": 1,
            "step_id": 101,
            "source_asset_id": 500,
            "result_asset_id": None,
            "status": SketchJobStatus.PENDING,
            "model": "claude-opus-5",
            "prompt_version": "blueprint-v1",
            "notes": "",
            "error": None,
            "completed_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
        data.update(overrides)
        return SketchJobRead(**data)  # type: ignore[arg-type]

    def _service(
        self, jobs: AsyncMock, client: AsyncMock, assets: AsyncMock, steps: AsyncMock
    ) -> SketchService:
        """Assemble a sketch service from fakes.

        Args:
            jobs: Faked job repository.
            client: Faked redraw client.
            assets: Faked asset service.
            steps: Faked step service.

        Returns:
            SketchService: The service under test.
        """
        return SketchService(jobs, assets, steps, client, SketchConfig(api_key="k"))

    async def test_success_stores_the_drawing_but_does_not_attach_it(self, jobs: AsyncMock) -> None:
        """A finished redraw waits for a human before it can reach a sheet.

        Args:
            jobs: Faked job repository.
        """
        jobs.get.return_value = self._job()
        jobs.update.return_value = self._job(status=SketchJobStatus.RUNNING)

        steps = AsyncMock()
        steps.get.return_value = make_step(1)
        assets = AsyncMock()
        assets.read.return_value = (
            type("A", (), {"content_type": "image/png"})(),
            b"sketchbytes",
        )
        assets.store_bytes.return_value = type("A", (), {"id": 777})()
        client = AsyncMock()
        client.redraw.return_value = RedrawOutput(
            svg=SAMPLE_SVG, suggested_callouts=[], notes="assumed symmetry", confidence=0.9
        )

        await self._service(jobs, client, assets, steps).run(1)

        final = jobs.update.await_args.args[1]
        assert final.status is SketchJobStatus.SUCCEEDED
        assert final.result_asset_id == 777
        steps.set_image.assert_not_awaited()

    async def test_stores_only_sanitised_markup(self, jobs: AsyncMock) -> None:
        """Whatever the model returns, what lands on disk is inert.

        Args:
            jobs: Faked job repository.
        """
        jobs.get.return_value = self._job()
        jobs.update.return_value = self._job(status=SketchJobStatus.RUNNING)

        steps = AsyncMock()
        steps.get.return_value = make_step(1)
        assets = AsyncMock()
        assets.read.return_value = (type("A", (), {"content_type": "image/png"})(), b"x")
        assets.store_bytes.return_value = type("A", (), {"id": 1})()
        client = AsyncMock()
        client.redraw.return_value = RedrawOutput(
            svg=SAMPLE_SVG.replace("<rect", "<script>alert(1)</script><rect"),
            confidence=0.5,
        )

        await self._service(jobs, client, assets, steps).run(1)

        stored = assets.store_bytes.await_args.args[0].decode()
        assert "script" not in stored
        assert "<path" in stored or "<rect" in stored

    async def test_a_refusal_becomes_a_failed_job_not_a_crash(self, jobs: AsyncMock) -> None:
        """A model refusal is an outcome the author can see and retry.

        Args:
            jobs: Faked job repository.
        """
        jobs.get.return_value = self._job()
        jobs.update.return_value = self._job(status=SketchJobStatus.RUNNING)

        steps = AsyncMock()
        steps.get.return_value = make_step(1)
        assets = AsyncMock()
        assets.read.return_value = (type("A", (), {"content_type": "image/png"})(), b"x")
        client = AsyncMock()
        client.redraw.side_effect = SketchRefusedError("declined")

        await self._service(jobs, client, assets, steps).run(1)

        final = jobs.update.await_args.args[1]
        assert final.status is SketchJobStatus.FAILED
        assert "declined" in final.error

    async def test_unusable_svg_becomes_a_failed_job(self, jobs: AsyncMock) -> None:
        """A drawing the sanitiser rejects fails the job rather than the request.

        Args:
            jobs: Faked job repository.
        """
        jobs.get.return_value = self._job()
        jobs.update.return_value = self._job(status=SketchJobStatus.RUNNING)

        steps = AsyncMock()
        steps.get.return_value = make_step(1)
        assets = AsyncMock()
        assets.read.return_value = (type("A", (), {"content_type": "image/png"})(), b"x")
        client = AsyncMock()
        client.redraw.return_value = RedrawOutput(svg="<html>nope</html>", confidence=0.1)

        await self._service(jobs, client, assets, steps).run(1)

        assert jobs.update.await_args.args[1].status is SketchJobStatus.FAILED

    @pytest.mark.parametrize(
        "status", [SketchJobStatus.PENDING, SketchJobStatus.RUNNING, SketchJobStatus.FAILED]
    )
    async def test_approve_refuses_a_job_with_no_drawing(
        self, jobs: AsyncMock, status: SketchJobStatus
    ) -> None:
        """Only a succeeded job has anything to promote.

        Args:
            jobs: Faked job repository.
            status: A status with no result asset.
        """
        jobs.get.return_value = self._job(status=status)
        steps = AsyncMock()
        service = self._service(jobs, AsyncMock(), AsyncMock(), steps)
        with pytest.raises(SketchUnavailableError):
            await service.approve(1)
        steps.set_image.assert_not_awaited()

    async def test_approve_attaches_the_drawing(self, jobs: AsyncMock) -> None:
        """Promotion is what puts a redraw on the sheet.

        Args:
            jobs: Faked job repository.
        """
        jobs.get.return_value = self._job(status=SketchJobStatus.SUCCEEDED, result_asset_id=777)
        steps = AsyncMock()
        await self._service(jobs, AsyncMock(), AsyncMock(), steps).approve(1)
        steps.set_image.assert_awaited_once_with(101, 777)

    async def test_queue_refuses_a_format_the_model_cannot_read(self, jobs: AsyncMock) -> None:
        """The check happens before anything is stored or queued.

        Args:
            jobs: Faked job repository.
        """
        assets = AsyncMock()
        service = self._service(jobs, AsyncMock(), assets, AsyncMock())
        with pytest.raises(UnsupportedSketchFormatError):
            await service.queue(101, b"<svg/>", "image/svg+xml")
        assets.store_bytes.assert_not_awaited()
        jobs.create.assert_not_awaited()

    async def test_queue_is_refused_when_redraw_is_disabled(self, jobs: AsyncMock) -> None:
        """A disabled environment declines rather than failing later.

        Args:
            jobs: Faked job repository.
        """
        service = SketchService(
            jobs, AsyncMock(), AsyncMock(), AsyncMock(), SketchConfig(enabled=False)
        )
        with pytest.raises(SketchUnavailableError):
            await service.queue(101, b"x", "image/png")

    async def test_reap_requeues_jobs_left_running_by_a_restart(self, jobs: AsyncMock) -> None:
        """In-process work does not survive a restart, so the row is re-queued.

        Args:
            jobs: Faked job repository.
        """
        jobs.list_by_status.return_value = [
            self._job(id=1, status=SketchJobStatus.RUNNING),
            self._job(id=2, status=SketchJobStatus.RUNNING),
        ]
        jobs.update.return_value = self._job(status=SketchJobStatus.PENDING)

        requeued = await reap_stalled_jobs(jobs)

        assert len(requeued) == 2
        assert jobs.update.await_args.args[1].status is SketchJobStatus.PENDING

    async def test_reap_is_a_no_op_when_nothing_is_stuck(self, jobs: AsyncMock) -> None:
        """A clean start does no writes.

        Args:
            jobs: Faked job repository.
        """
        jobs.list_by_status.return_value = []
        assert await reap_stalled_jobs(jobs) == []
        jobs.update.assert_not_awaited()

    async def test_suggested_callouts_are_applied_only_when_asked(self, jobs: AsyncMock) -> None:
        """The model's suggestions reach the step only through an explicit call.

        Args:
            jobs: Faked job repository.
        """
        jobs.get.return_value = self._job()
        steps = AsyncMock()
        service = self._service(jobs, AsyncMock(), AsyncMock(), steps)

        await service.apply_suggested_callouts(
            1,
            [CalloutCreate(index=1, x_pct=10, y_pct=20, leader_dir=LeaderDir.RIGHT, label="Here")],
        )

        steps.add_callout.assert_awaited_once()


def test_suggested_callout_schema_bounds_coordinates() -> None:
    """A callout outside the plate would be drawn off the drawing."""
    with pytest.raises(ValidationError):
        SuggestedCallout(index=1, x_pct=120, y_pct=10, leader_dir="right", label="x")


def test_revision_history_uses_the_revision_date() -> None:
    """The printed history is keyed on the edition date, not on insertion order."""
    assert make_revision().revision_date == date(2026, 8, 26)
