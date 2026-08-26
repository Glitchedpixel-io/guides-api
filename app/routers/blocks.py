"""Endpoints for individual front-matter entries.

Entries are addressed by their own id rather than through their revision, because an
entry's id is stable while its position is not — a client holding a position would edit
the wrong row the moment anything above it moved.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api_responses import WRITE_RESPONSES, http_errors
from app.dependencies import get_bom_service, get_tool_service, get_warning_service
from app.routers.base import QuietClientErrorRoute
from app.schemas.blocks import (
    BomItemPatch,
    BomItemRead,
    RequiredToolPatch,
    RequiredToolRead,
    SafetyWarningPatch,
    SafetyWarningRead,
)
from app.services.content_service import BlockService

router = APIRouter(route_class=QuietClientErrorRoute)

# ----------------------------------------------------- block item mutations ---
# Individual entries are addressed by their own id rather than through the revision,
# because an entry's id is stable while its position is not.


@router.patch(
    "/bom-items/{item_id}",
    response_model=BomItemRead,
    operation_id="update_bom_item",
    responses=WRITE_RESPONSES,
)
async def update_bom_item(
    item_id: int, payload: BomItemPatch, svc: BlockService[BomItemRead] = Depends(get_bom_service)
) -> BomItemRead:
    """Amend a bill-of-materials line.

    Args:
        item_id: The line's primary key.
        payload: Fields to change.
        svc: Panel A editing.

    Returns:
        BomItemRead: The updated line.
    """
    with http_errors():
        return await svc.update(item_id, payload)


@router.delete(
    "/bom-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_bom_item",
    responses=WRITE_RESPONSES,
)
async def delete_bom_item(
    item_id: int, svc: BlockService[BomItemRead] = Depends(get_bom_service)
) -> None:
    """Remove a bill-of-materials line.

    Args:
        item_id: The line's primary key.
        svc: Panel A editing.
    """
    with http_errors():
        await svc.delete(item_id)


@router.patch(
    "/required-tools/{item_id}",
    response_model=RequiredToolRead,
    operation_id="update_required_tool",
    responses=WRITE_RESPONSES,
)
async def update_required_tool(
    item_id: int,
    payload: RequiredToolPatch,
    svc: BlockService[RequiredToolRead] = Depends(get_tool_service),
) -> RequiredToolRead:
    """Amend a required tool.

    Args:
        item_id: The tool's primary key.
        payload: Fields to change.
        svc: Panel B editing.

    Returns:
        RequiredToolRead: The updated tool.
    """
    with http_errors():
        return await svc.update(item_id, payload)


@router.delete(
    "/required-tools/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_required_tool",
    responses=WRITE_RESPONSES,
)
async def delete_required_tool(
    item_id: int, svc: BlockService[RequiredToolRead] = Depends(get_tool_service)
) -> None:
    """Remove a required tool.

    Args:
        item_id: The tool's primary key.
        svc: Panel B editing.
    """
    with http_errors():
        await svc.delete(item_id)


@router.patch(
    "/safety-warnings/{item_id}",
    response_model=SafetyWarningRead,
    operation_id="update_safety_warning",
    responses=WRITE_RESPONSES,
)
async def update_safety_warning(
    item_id: int,
    payload: SafetyWarningPatch,
    svc: BlockService[SafetyWarningRead] = Depends(get_warning_service),
) -> SafetyWarningRead:
    """Amend a safety warning.

    Args:
        item_id: The warning's primary key.
        payload: Fields to change.
        svc: Panel C editing.

    Returns:
        SafetyWarningRead: The updated warning.
    """
    with http_errors():
        return await svc.update(item_id, payload)


@router.delete(
    "/safety-warnings/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_safety_warning",
    responses=WRITE_RESPONSES,
)
async def delete_safety_warning(
    item_id: int, svc: BlockService[SafetyWarningRead] = Depends(get_warning_service)
) -> None:
    """Remove a safety warning.

    Args:
        item_id: The warning's primary key.
        svc: Panel C editing.
    """
    with http_errors():
        await svc.delete(item_id)
