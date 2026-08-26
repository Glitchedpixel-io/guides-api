"""Step and callout endpoints, addressed by step id."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api_responses import COMMON_RESPONSES, WRITE_RESPONSES, http_errors
from app.dependencies import get_step_service
from app.routers.base import QuietClientErrorRoute
from app.schemas.steps import (
    CalloutCreate,
    CalloutPatch,
    CalloutRead,
    StepPatch,
    StepRead,
)
from app.services.content_service import StepService

router = APIRouter(route_class=QuietClientErrorRoute)


@router.get(
    "/{step_id}",
    response_model=StepRead,
    operation_id="get_step",
    responses=COMMON_RESPONSES,
)
async def get_step(step_id: int, svc: StepService = Depends(get_step_service)) -> StepRead:
    """Fetch a step and its callouts.

    Args:
        step_id: The step's primary key.
        svc: Step business logic.

    Returns:
        StepRead: The stored step.
    """
    with http_errors():
        return await svc.get(step_id)


@router.patch(
    "/{step_id}",
    response_model=StepRead,
    operation_id="update_step",
    responses=WRITE_RESPONSES,
)
async def update_step(
    step_id: int, payload: StepPatch, svc: StepService = Depends(get_step_service)
) -> StepRead:
    """Amend a step.

    Args:
        step_id: The step's primary key.
        payload: Fields to change.
        svc: Step business logic.

    Returns:
        StepRead: The updated step.
    """
    with http_errors():
        return await svc.update(step_id, payload)


@router.delete(
    "/{step_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_step",
    responses=WRITE_RESPONSES,
)
async def delete_step(step_id: int, svc: StepService = Depends(get_step_service)) -> None:
    """Remove a step and close the gap in the sequence.

    Args:
        step_id: The step's primary key.
        svc: Step business logic.
    """
    with http_errors():
        await svc.delete(step_id)


@router.put(
    "/{step_id}/image/{asset_id}",
    response_model=StepRead,
    operation_id="set_step_image",
    responses=WRITE_RESPONSES,
)
async def set_step_image(
    step_id: int, asset_id: int, svc: StepService = Depends(get_step_service)
) -> StepRead:
    """Attach a stored drawing to a step.

    Any existing callouts are cleared: they are positioned against the drawing they
    annotate, so keeping them across a new drawing would point them at nothing.

    Args:
        step_id: The step's primary key.
        asset_id: The drawing to attach.
        svc: Step business logic.

    Returns:
        StepRead: The updated step.
    """
    with http_errors():
        return await svc.set_image(step_id, asset_id)


@router.delete(
    "/{step_id}/image",
    response_model=StepRead,
    operation_id="clear_step_image",
    responses=WRITE_RESPONSES,
)
async def clear_step_image(step_id: int, svc: StepService = Depends(get_step_service)) -> StepRead:
    """Detach a step's drawing and its callouts.

    Args:
        step_id: The step's primary key.
        svc: Step business logic.

    Returns:
        StepRead: The updated step.
    """
    with http_errors():
        return await svc.set_image(step_id, None)


@router.post(
    "/{step_id}/callouts",
    response_model=CalloutRead,
    operation_id="add_callout",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
async def add_callout(
    step_id: int, payload: CalloutCreate, svc: StepService = Depends(get_step_service)
) -> CalloutRead:
    """Add a numbered callout over a step's plate.

    Args:
        step_id: The step's primary key.
        payload: The callout to add.
        svc: Step business logic.

    Returns:
        CalloutRead: The stored callout.
    """
    with http_errors():
        return await svc.add_callout(step_id, payload)


@router.patch(
    "/callouts/{callout_id}",
    response_model=CalloutRead,
    operation_id="update_callout",
    responses=WRITE_RESPONSES,
)
async def update_callout(
    callout_id: int, payload: CalloutPatch, svc: StepService = Depends(get_step_service)
) -> CalloutRead:
    """Amend a callout.

    Args:
        callout_id: The callout's primary key.
        payload: Fields to change.
        svc: Step business logic.

    Returns:
        CalloutRead: The updated callout.
    """
    with http_errors():
        return await svc.update_callout(callout_id, payload)


@router.delete(
    "/callouts/{callout_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_callout",
    responses=WRITE_RESPONSES,
)
async def delete_callout(callout_id: int, svc: StepService = Depends(get_step_service)) -> None:
    """Remove a callout.

    Args:
        callout_id: The callout's primary key.
        svc: Step business logic.
    """
    with http_errors():
        await svc.delete_callout(callout_id)
