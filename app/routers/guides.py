"""Guide and revision endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api_responses import COMMON_RESPONSES, WRITE_RESPONSES, http_errors
from app.dependencies import get_guide_service, get_revision_service
from app.routers.base import QuietClientErrorRoute
from app.schemas.guides import (
    GuideCreate,
    GuidePatch,
    GuideRead,
    RevisionCreate,
    RevisionRead,
)
from app.services.guide_service import GuideService, RevisionService

router = APIRouter(route_class=QuietClientErrorRoute)


@router.get("/", response_model=list[GuideRead], operation_id="list_guides")
async def list_guides(svc: GuideService = Depends(get_guide_service)) -> list[GuideRead]:
    """List every guide.

    Args:
        svc: Guide business logic.

    Returns:
        list[GuideRead]: All stored guides.
    """
    return await svc.list_all()


@router.post(
    "/",
    response_model=GuideRead,
    operation_id="create_guide",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
async def create_guide(
    payload: GuideCreate, svc: GuideService = Depends(get_guide_service)
) -> GuideRead:
    """Create a guide.

    Args:
        payload: The guide to create.
        svc: Guide business logic.

    Returns:
        GuideRead: The stored guide.
    """
    with http_errors():
        return await svc.create(payload)


@router.get(
    "/{guide_id}",
    response_model=GuideRead,
    operation_id="get_guide",
    responses=COMMON_RESPONSES,
)
async def get_guide(guide_id: int, svc: GuideService = Depends(get_guide_service)) -> GuideRead:
    """Fetch one guide.

    Args:
        guide_id: The guide's primary key.
        svc: Guide business logic.

    Returns:
        GuideRead: The stored guide.
    """
    with http_errors():
        return await svc.get(guide_id)


@router.patch(
    "/{guide_id}",
    response_model=GuideRead,
    operation_id="update_guide",
    responses=WRITE_RESPONSES,
)
async def update_guide(
    guide_id: int, payload: GuidePatch, svc: GuideService = Depends(get_guide_service)
) -> GuideRead:
    """Amend a guide.

    Args:
        guide_id: The guide's primary key.
        payload: Fields to change.
        svc: Guide business logic.

    Returns:
        GuideRead: The updated guide.
    """
    with http_errors():
        return await svc.update(guide_id, payload)


@router.delete(
    "/{guide_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_guide",
    responses=COMMON_RESPONSES,
)
async def delete_guide(guide_id: int, svc: GuideService = Depends(get_guide_service)) -> None:
    """Delete a guide and every revision beneath it.

    Args:
        guide_id: The guide's primary key.
        svc: Guide business logic.
    """
    with http_errors():
        await svc.delete(guide_id)


@router.get(
    "/{guide_id}/revisions",
    response_model=list[RevisionRead],
    operation_id="list_revisions",
    responses=COMMON_RESPONSES,
)
async def list_revisions(
    guide_id: int, svc: RevisionService = Depends(get_revision_service)
) -> list[RevisionRead]:
    """List a guide's revisions, oldest first.

    Args:
        guide_id: The owning guide.
        svc: Revision business logic.

    Returns:
        list[RevisionRead]: The guide's revisions.
    """
    with http_errors():
        return await svc.list_for_guide(guide_id)


@router.post(
    "/{guide_id}/revisions",
    response_model=RevisionRead,
    operation_id="create_revision",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
async def create_revision(
    guide_id: int,
    payload: RevisionCreate,
    svc: RevisionService = Depends(get_revision_service),
) -> RevisionRead:
    """Open a new draft revision.

    Args:
        guide_id: The owning guide.
        payload: The revision to create.
        svc: Revision business logic.

    Returns:
        RevisionRead: The new draft revision.
    """
    with http_errors():
        return await svc.create(guide_id, payload)
