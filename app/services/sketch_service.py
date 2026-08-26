"""Sketch redraw orchestration.

The job row — not the running task — is the source of truth. That is what lets a restart
recover: :meth:`SketchService.reap_stalled` re-queues anything a dead process left running.
"""

from __future__ import annotations

from datetime import datetime, timezone

import logfire

from app.config.schema import SketchConfig
from app.repositories.protocols import SketchJobRepository
from app.schemas.assets import SketchJobCreateInternal, SketchJobPatchInternal, SketchJobRead
from app.schemas.enums import AssetKind, SketchJobStatus
from app.schemas.steps import CalloutCreate
from app.services.asset_service import AssetService
from app.services.content_service import StepService
from app.services.errors import SketchUnavailableError
from app.sketch.client import (
    SUPPORTED_MEDIA_TYPES,
    SketchError,
    SketchRedrawClient,
    UnsupportedSketchFormatError,
)
from app.sketch.svg_sanitiser import SvgRejectedError, sanitise_svg


class SketchService:
    """Queues, runs, and promotes sketch redraws."""

    def __init__(
        self,
        jobs: SketchJobRepository,
        assets: AssetService,
        steps: StepService,
        client: SketchRedrawClient,
        config: SketchConfig,
    ) -> None:
        """Bind the service to its collaborators.

        Args:
            jobs: Storage for redraw jobs.
            assets: Reads the sketch and stores the redrawn SVG.
            steps: Used to read the step's context and to promote a finished drawing.
            client: The Claude-backed redraw client.
            config: Sketch settings.
        """
        self._jobs = jobs
        self._assets = assets
        self._steps = steps
        self._client = client
        self._config = config

    async def queue(
        self,
        step_id: int,
        data: bytes,
        media_type: str,
        filename: str | None = None,
    ) -> SketchJobRead:
        """Store an uploaded sketch and queue a redraw for it.

        Args:
            step_id: The step the drawing belongs to.
            data: The uploaded sketch bytes.
            media_type: Its MIME type.
            filename: The uploaded filename, kept for display.

        Returns:
            SketchJobRead: The queued job.

        Raises:
            SketchUnavailableError: If redraw is disabled in this environment.
            UnsupportedSketchFormatError: If the file is not a format the model accepts.
            RevisionNotEditableError: If the step's revision is no longer a draft.
        """
        if not self._config.enabled:
            raise SketchUnavailableError("sketch redraw is disabled in this environment")

        # Check the format here as well as in the client. The client's check is what makes
        # the call safe; this one is what makes it *usable* — otherwise an unsupported file
        # is accepted with a 202 and the author only discovers it was never going to work
        # by polling a job that has already failed.
        if media_type.split(";")[0].strip().lower() not in SUPPORTED_MEDIA_TYPES:
            raise UnsupportedSketchFormatError(
                f"{media_type!r} is not a supported sketch format; "
                f"use one of {sorted(SUPPORTED_MEDIA_TYPES)}"
            )

        # Reuse the step service's editability check rather than restating the rule here;
        # a second copy of "which statuses are editable" is a second thing to get wrong.
        step = await self._steps.assert_editable(step_id)

        sketch = await self._assets.store_bytes(
            data, AssetKind.SKETCH, media_type, original_filename=filename
        )
        return await self._jobs.create(
            SketchJobCreateInternal(
                step_id=step.id,
                source_asset_id=sketch.id,
                model=self._config.model,
                prompt_version=self._config.prompt_version,
            )
        )

    async def run(self, job_id: int) -> SketchJobRead:
        """Execute one queued redraw.

        A finished job stores its drawing but does **not** attach it to the step. Promotion
        is an explicit human action, so nothing reaches a printed sheet unreviewed.

        Args:
            job_id: The job to run.

        Returns:
            SketchJobRead: The finished job, succeeded or failed.
        """
        job = await self._jobs.get(job_id)
        job = await self._jobs.update(
            job_id, SketchJobPatchInternal(status=SketchJobStatus.RUNNING)
        )

        try:
            step = await self._steps.get(job.step_id)
            sketch, data = await self._assets.read(job.source_asset_id)
            result = await self._client.redraw(
                image_bytes=data,
                media_type=sketch.content_type,
                step_title=step.title,
                instructions=step.instructions,
            )
            svg = sanitise_svg(result.svg)
        except (SketchError, SvgRejectedError) as exc:
            # A refusal, an unusable drawing, or a rejected SVG is an outcome, not a crash:
            # it belongs on the job row where the author can see it and retry.
            logfire.warning("sketch redraw failed", job_id=job_id, error=str(exc))
            return await self._jobs.update(
                job_id,
                SketchJobPatchInternal(
                    status=SketchJobStatus.FAILED,
                    error=str(exc),
                    completed_at=datetime.now(timezone.utc),
                ),
            )

        asset = await self._assets.store_bytes(
            svg.encode("utf-8"),
            AssetKind.REDRAWN_SVG,
            "image/svg+xml",
            original_filename=f"step-{step.position}-redraw.svg",
        )

        return await self._jobs.update(
            job_id,
            SketchJobPatchInternal(
                status=SketchJobStatus.SUCCEEDED,
                result_asset_id=asset.id,
                notes=result.notes,
                completed_at=datetime.now(timezone.utc),
            ),
        )

    async def approve(self, job_id: int) -> SketchJobRead:
        """Promote a finished redraw onto its step.

        Args:
            job_id: The job whose drawing to attach.

        Returns:
            SketchJobRead: The job, unchanged.

        Raises:
            SketchUnavailableError: If the job has not produced a drawing.
            RevisionNotEditableError: If the step's revision is no longer a draft.
        """
        job = await self._jobs.get(job_id)
        if job.status is not SketchJobStatus.SUCCEEDED or job.result_asset_id is None:
            raise SketchUnavailableError(
                f"job {job_id} is {job.status.value} and has no drawing to promote"
            )
        await self._steps.set_image(job.step_id, job.result_asset_id)
        return job

    async def apply_suggested_callouts(
        self, job_id: int, callouts: list[CalloutCreate]
    ) -> SketchJobRead:
        """Attach reviewed callouts to the job's step.

        Args:
            job_id: The job whose step to annotate.
            callouts: Callouts the author has reviewed and accepted.

        Returns:
            SketchJobRead: The job, unchanged.
        """
        job = await self._jobs.get(job_id)
        for callout in callouts:
            await self._steps.add_callout(job.step_id, callout)
        return job

    async def get(self, job_id: int) -> SketchJobRead:
        """Fetch a job.

        Args:
            job_id: The job's primary key.

        Returns:
            SketchJobRead: The stored job.
        """
        return await self._jobs.get(job_id)

    async def list_for_step(self, step_id: int) -> list[SketchJobRead]:
        """List a step's redraw attempts, newest first.

        Args:
            step_id: The step's primary key.

        Returns:
            list[SketchJobRead]: The step's jobs.
        """
        return await self._jobs.list_for_step(step_id)

    async def reap_stalled(self) -> list[SketchJobRead]:
        """Return jobs abandoned mid-flight back to the queue.

        Returns:
            list[SketchJobRead]: The jobs that were re-queued.
        """
        return await reap_stalled_jobs(self._jobs)


async def reap_stalled_jobs(jobs: SketchJobRepository) -> list[SketchJobRead]:
    """Move jobs stuck on ``RUNNING`` back to ``PENDING``.

    Redraws run as in-process background tasks, so a restart leaves anything in flight
    stuck on ``RUNNING`` with nothing left to advance it — a permanently wedged job and a
    spinner that never resolves. Run at startup, this turns that into a retry.

    Deliberately a free function taking only the job repository: startup has no request,
    no step service and no model client, and inventing stand-ins for them just to call a
    method would be wiring fiction.

    Args:
        jobs: Storage for redraw jobs.

    Returns:
        list[SketchJobRead]: The jobs that were re-queued.
    """
    stalled = await jobs.list_by_status(SketchJobStatus.RUNNING)
    requeued = []
    for job in stalled:
        logfire.info("re-queuing sketch job abandoned by a restart", job_id=job.id)
        requeued.append(
            await jobs.update(job.id, SketchJobPatchInternal(status=SketchJobStatus.PENDING))
        )
    return requeued
