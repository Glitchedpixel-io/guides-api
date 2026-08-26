"""Revision endpoints: lifecycle, content blocks, and steps."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api_responses import COMMON_RESPONSES, WRITE_RESPONSES, http_errors
from app.dependencies import (
    get_bom_service,
    get_document_service,
    get_revision_service,
    get_step_service,
    get_tool_service,
    get_warning_service,
)
from app.routers.base import QuietClientErrorRoute
from app.schemas.assets import RevisionDocument
from app.schemas.base import ReorderRequest
from app.schemas.blocks import (
    BomItemCreate,
    BomItemRead,
    RequiredToolCreate,
    RequiredToolRead,
    SafetyWarningCreate,
    SafetyWarningRead,
)
from app.schemas.guides import RevisionPatch, RevisionRead
from app.schemas.steps import StepCreate, StepRead
from app.services.content_service import BlockService, StepService
from app.services.document_service import DocumentService
from app.services.guide_service import RevisionService

router = APIRouter(route_class=QuietClientErrorRoute)


# ---------------------------------------------------------------- lifecycle ---


@router.get(
    "/{revision_id}",
    response_model=RevisionRead,
    operation_id="get_revision",
    responses=COMMON_RESPONSES,
)
async def get_revision(
    revision_id: int, svc: RevisionService = Depends(get_revision_service)
) -> RevisionRead:
    """Fetch one revision.

    Args:
        revision_id: The revision's primary key.
        svc: Revision business logic.

    Returns:
        RevisionRead: The stored revision.
    """
    with http_errors():
        return await svc.get(revision_id)


@router.patch(
    "/{revision_id}",
    response_model=RevisionRead,
    operation_id="update_revision",
    responses=WRITE_RESPONSES,
)
async def update_revision(
    revision_id: int,
    payload: RevisionPatch,
    svc: RevisionService = Depends(get_revision_service),
) -> RevisionRead:
    """Amend a draft revision.

    Args:
        revision_id: The revision's primary key.
        payload: Fields to change.
        svc: Revision business logic.

    Returns:
        RevisionRead: The updated revision.
    """
    with http_errors():
        return await svc.update(revision_id, payload)


@router.delete(
    "/{revision_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_revision",
    responses=WRITE_RESPONSES,
)
async def delete_revision(
    revision_id: int, svc: RevisionService = Depends(get_revision_service)
) -> None:
    """Delete a draft revision and its content.

    Args:
        revision_id: The revision's primary key.
        svc: Revision business logic.
    """
    with http_errors():
        await svc.delete(revision_id)


@router.post(
    "/{revision_id}/publish",
    response_model=RevisionRead,
    operation_id="publish_revision",
    responses=WRITE_RESPONSES,
)
async def publish_revision(
    revision_id: int, svc: RevisionService = Depends(get_revision_service)
) -> RevisionRead:
    """Freeze a draft revision for issue.

    Args:
        revision_id: The revision's primary key.
        svc: Revision business logic.

    Returns:
        RevisionRead: The published revision.
    """
    with http_errors():
        return await svc.publish(revision_id)


@router.post(
    "/{revision_id}/archive",
    response_model=RevisionRead,
    operation_id="archive_revision",
    responses=WRITE_RESPONSES,
)
async def archive_revision(
    revision_id: int, svc: RevisionService = Depends(get_revision_service)
) -> RevisionRead:
    """Withdraw a published revision from use.

    Args:
        revision_id: The revision's primary key.
        svc: Revision business logic.

    Returns:
        RevisionRead: The archived revision.
    """
    with http_errors():
        return await svc.archive(revision_id)


@router.get(
    "/{revision_id}/document",
    response_model=RevisionDocument,
    operation_id="get_revision_document",
    responses=COMMON_RESPONSES,
)
async def get_revision_document(
    revision_id: int, svc: DocumentService = Depends(get_document_service)
) -> RevisionDocument:
    """Fetch everything the sheet prints, in one read.

    Args:
        revision_id: The revision's primary key.
        svc: Assembles the printable revision.

    Returns:
        RevisionDocument: The whole document.
    """
    with http_errors():
        return await svc.build(revision_id)


# -------------------------------------------------------------------- steps ---


@router.get(
    "/{revision_id}/steps",
    response_model=list[StepRead],
    operation_id="list_steps",
    responses=COMMON_RESPONSES,
)
async def list_steps(
    revision_id: int, svc: StepService = Depends(get_step_service)
) -> list[StepRead]:
    """List a revision's steps in strict order.

    Args:
        revision_id: The owning revision.
        svc: Step business logic.

    Returns:
        list[StepRead]: The steps.
    """
    with http_errors():
        return await svc.list_for_revision(revision_id)


@router.post(
    "/{revision_id}/steps",
    response_model=StepRead,
    operation_id="add_step",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
async def add_step(
    revision_id: int, payload: StepCreate, svc: StepService = Depends(get_step_service)
) -> StepRead:
    """Append a step to a revision.

    Args:
        revision_id: The owning revision.
        payload: The step to add.
        svc: Step business logic.

    Returns:
        StepRead: The stored step.
    """
    with http_errors():
        return await svc.add(revision_id, payload)


@router.post(
    "/{revision_id}/steps/reorder",
    response_model=list[StepRead],
    operation_id="reorder_steps",
    responses=WRITE_RESPONSES,
)
async def reorder_steps(
    revision_id: int,
    payload: ReorderRequest,
    svc: StepService = Depends(get_step_service),
) -> list[StepRead]:
    """Renumber a revision's steps in one transaction.

    The request must name every step exactly once. A partial reorder is ambiguous about
    where the omitted steps go, and on a procedure sheet the order is the safety property.

    Args:
        revision_id: The owning revision.
        payload: The complete new ordering.
        svc: Step business logic.

    Returns:
        list[StepRead]: The steps in their new order.
    """
    with http_errors():
        return await svc.reorder(revision_id, payload)


# ------------------------------------------------------------ block: A, BOM ---


@router.get(
    "/{revision_id}/bom",
    response_model=list[BomItemRead],
    operation_id="list_bom_items",
    responses=COMMON_RESPONSES,
)
async def list_bom_items(
    revision_id: int, svc: BlockService[BomItemRead] = Depends(get_bom_service)
) -> list[BomItemRead]:
    """List the bill of materials.

    Args:
        revision_id: The owning revision.
        svc: Panel A editing.

    Returns:
        list[BomItemRead]: The BOM lines in order.
    """
    with http_errors():
        return await svc.list_for_revision(revision_id)


@router.post(
    "/{revision_id}/bom",
    response_model=BomItemRead,
    operation_id="add_bom_item",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
async def add_bom_item(
    revision_id: int,
    payload: BomItemCreate,
    svc: BlockService[BomItemRead] = Depends(get_bom_service),
) -> BomItemRead:
    """Append a bill-of-materials line.

    Args:
        revision_id: The owning revision.
        payload: The line to add.
        svc: Panel A editing.

    Returns:
        BomItemRead: The stored line.
    """
    with http_errors():
        return await svc.add(revision_id, payload)


@router.post(
    "/{revision_id}/bom/reorder",
    response_model=list[BomItemRead],
    operation_id="reorder_bom_items",
    responses=WRITE_RESPONSES,
)
async def reorder_bom_items(
    revision_id: int,
    payload: ReorderRequest,
    svc: BlockService[BomItemRead] = Depends(get_bom_service),
) -> list[BomItemRead]:
    """Renumber the bill of materials.

    Args:
        revision_id: The owning revision.
        payload: The complete new ordering.
        svc: Panel A editing.

    Returns:
        list[BomItemRead]: The lines in their new order.
    """
    with http_errors():
        return await svc.reorder(revision_id, payload)


# ---------------------------------------------------------- block: B, tools ---


@router.get(
    "/{revision_id}/tools",
    response_model=list[RequiredToolRead],
    operation_id="list_required_tools",
    responses=COMMON_RESPONSES,
)
async def list_required_tools(
    revision_id: int, svc: BlockService[RequiredToolRead] = Depends(get_tool_service)
) -> list[RequiredToolRead]:
    """List the required tools.

    Args:
        revision_id: The owning revision.
        svc: Panel B editing.

    Returns:
        list[RequiredToolRead]: The tools in order.
    """
    with http_errors():
        return await svc.list_for_revision(revision_id)


@router.post(
    "/{revision_id}/tools",
    response_model=RequiredToolRead,
    operation_id="add_required_tool",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
async def add_required_tool(
    revision_id: int,
    payload: RequiredToolCreate,
    svc: BlockService[RequiredToolRead] = Depends(get_tool_service),
) -> RequiredToolRead:
    """Append a required tool.

    Args:
        revision_id: The owning revision.
        payload: The tool to add.
        svc: Panel B editing.

    Returns:
        RequiredToolRead: The stored tool.
    """
    with http_errors():
        return await svc.add(revision_id, payload)


@router.post(
    "/{revision_id}/tools/reorder",
    response_model=list[RequiredToolRead],
    operation_id="reorder_required_tools",
    responses=WRITE_RESPONSES,
)
async def reorder_required_tools(
    revision_id: int,
    payload: ReorderRequest,
    svc: BlockService[RequiredToolRead] = Depends(get_tool_service),
) -> list[RequiredToolRead]:
    """Renumber the required tools.

    Args:
        revision_id: The owning revision.
        payload: The complete new ordering.
        svc: Panel B editing.

    Returns:
        list[RequiredToolRead]: The tools in their new order.
    """
    with http_errors():
        return await svc.reorder(revision_id, payload)


# ------------------------------------------------------- block: C, warnings ---


@router.get(
    "/{revision_id}/warnings",
    response_model=list[SafetyWarningRead],
    operation_id="list_safety_warnings",
    responses=COMMON_RESPONSES,
)
async def list_safety_warnings(
    revision_id: int, svc: BlockService[SafetyWarningRead] = Depends(get_warning_service)
) -> list[SafetyWarningRead]:
    """List the safety warnings.

    Args:
        revision_id: The owning revision.
        svc: Panel C editing.

    Returns:
        list[SafetyWarningRead]: The warnings in order.
    """
    with http_errors():
        return await svc.list_for_revision(revision_id)


@router.post(
    "/{revision_id}/warnings",
    response_model=SafetyWarningRead,
    operation_id="add_safety_warning",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
async def add_safety_warning(
    revision_id: int,
    payload: SafetyWarningCreate,
    svc: BlockService[SafetyWarningRead] = Depends(get_warning_service),
) -> SafetyWarningRead:
    """Append a safety warning.

    Args:
        revision_id: The owning revision.
        payload: The warning to add.
        svc: Panel C editing.

    Returns:
        SafetyWarningRead: The stored warning.
    """
    with http_errors():
        return await svc.add(revision_id, payload)


@router.post(
    "/{revision_id}/warnings/reorder",
    response_model=list[SafetyWarningRead],
    operation_id="reorder_safety_warnings",
    responses=WRITE_RESPONSES,
)
async def reorder_safety_warnings(
    revision_id: int,
    payload: ReorderRequest,
    svc: BlockService[SafetyWarningRead] = Depends(get_warning_service),
) -> list[SafetyWarningRead]:
    """Renumber the safety warnings.

    Args:
        revision_id: The owning revision.
        payload: The complete new ordering.
        svc: Panel C editing.

    Returns:
        list[SafetyWarningRead]: The warnings in their new order.
    """
    with http_errors():
        return await svc.reorder(revision_id, payload)
