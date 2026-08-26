"""Sketch redraw endpoints.

Upload a sketch, poll the job, review the result, then explicitly promote it onto the
step. Nothing a model drew reaches a printed sheet without that last step.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status

from app.api_responses import COMMON_RESPONSES, WRITE_RESPONSES, http_errors
from app.dependencies import get_sketch_service
from app.routers.base import QuietClientErrorRoute
from app.schemas.assets import SketchJobRead
from app.schemas.steps import CalloutCreate
from app.services.sketch_service import SketchService

router = APIRouter(route_class=QuietClientErrorRoute)

SKETCH_RESPONSES = {
    **WRITE_RESPONSES,
    413: {"description": "Sketch exceeds the configured upload limit"},
    503: {"description": "Sketch redraw is disabled or unavailable"},
}


@router.post(
    "/steps/{step_id}/sketch",
    response_model=SketchJobRead,
    operation_id="queue_sketch_redraw",
    status_code=status.HTTP_202_ACCEPTED,
    responses=SKETCH_RESPONSES,
)
async def queue_sketch_redraw(
    step_id: int,
    background: BackgroundTasks,
    file: UploadFile = File(..., description="Hand-drawn sketch: PNG, JPEG, GIF or WebP."),
    svc: SketchService = Depends(get_sketch_service),
) -> SketchJobRead:
    """Upload a sketch and queue its redraw.

    Returns 202 immediately: a redraw takes tens of seconds, so the job row is the handle
    and ``GET /api/sketch-jobs/{id}`` is how the caller follows it.

    Args:
        step_id: The step the drawing belongs to.
        background: FastAPI's background runner.
        file: The uploaded sketch.
        svc: Redraw orchestration.

    Returns:
        SketchJobRead: The queued job.
    """
    data = await file.read()
    with http_errors():
        job = await svc.queue(
            step_id,
            data,
            file.content_type or "application/octet-stream",
            filename=file.filename,
        )
    background.add_task(svc.run, job.id)
    return job


@router.get(
    "/sketch-jobs/{job_id}",
    response_model=SketchJobRead,
    operation_id="get_sketch_job",
    responses=COMMON_RESPONSES,
)
async def get_sketch_job(
    job_id: int, svc: SketchService = Depends(get_sketch_service)
) -> SketchJobRead:
    """Fetch a redraw job's state.

    Args:
        job_id: The job's primary key.
        svc: Redraw orchestration.

    Returns:
        SketchJobRead: The stored job.
    """
    with http_errors():
        return await svc.get(job_id)


@router.get(
    "/steps/{step_id}/sketch-jobs",
    response_model=list[SketchJobRead],
    operation_id="list_sketch_jobs",
    responses=COMMON_RESPONSES,
)
async def list_sketch_jobs(
    step_id: int, svc: SketchService = Depends(get_sketch_service)
) -> list[SketchJobRead]:
    """List a step's redraw attempts, newest first.

    Args:
        step_id: The step's primary key.
        svc: Redraw orchestration.

    Returns:
        list[SketchJobRead]: The step's jobs.
    """
    with http_errors():
        return await svc.list_for_step(step_id)


@router.post(
    "/sketch-jobs/{job_id}/approve",
    response_model=SketchJobRead,
    operation_id="approve_sketch_redraw",
    responses=SKETCH_RESPONSES,
)
async def approve_sketch_redraw(
    job_id: int, svc: SketchService = Depends(get_sketch_service)
) -> SketchJobRead:
    """Promote a finished redraw onto its step.

    Args:
        job_id: The job whose drawing to attach.
        svc: Redraw orchestration.

    Returns:
        SketchJobRead: The job.
    """
    with http_errors():
        return await svc.approve(job_id)


@router.post(
    "/sketch-jobs/{job_id}/callouts",
    response_model=SketchJobRead,
    operation_id="apply_suggested_callouts",
    responses=SKETCH_RESPONSES,
)
async def apply_suggested_callouts(
    job_id: int,
    callouts: list[CalloutCreate],
    svc: SketchService = Depends(get_sketch_service),
) -> SketchJobRead:
    """Attach reviewed callouts to the job's step.

    The model's suggestions come back on the job for a human to accept, edit, or discard;
    this endpoint takes whichever survived that review.

    Args:
        job_id: The job whose step to annotate.
        callouts: The callouts to add.
        svc: Redraw orchestration.

    Returns:
        SketchJobRead: The job.
    """
    with http_errors():
        return await svc.apply_suggested_callouts(job_id, callouts)
