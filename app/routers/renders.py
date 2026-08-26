"""Rendering and download endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api_responses import COMMON_RESPONSES, WRITE_RESPONSES, http_errors
from app.dependencies import get_asset_service, get_render_service
from app.routers.base import QuietClientErrorRoute
from app.schemas.assets import AssetRead, RenderRead
from app.services.asset_service import AssetService
from app.services.render_service import RenderService

router = APIRouter(route_class=QuietClientErrorRoute)


@router.post(
    "/revisions/{revision_id}/render",
    response_model=RenderRead,
    operation_id="render_revision",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
async def render_revision(
    revision_id: int, svc: RenderService = Depends(get_render_service)
) -> RenderRead:
    """Render a revision to a stored PDF.

    Args:
        revision_id: The revision to render.
        svc: PDF production.

    Returns:
        RenderRead: The recorded render, naming the stored PDF asset.
    """
    with http_errors():
        return await svc.render(revision_id)


@router.get(
    "/revisions/{revision_id}/renders",
    response_model=list[RenderRead],
    operation_id="list_renders",
    responses=COMMON_RESPONSES,
)
async def list_renders(
    revision_id: int, svc: RenderService = Depends(get_render_service)
) -> list[RenderRead]:
    """List a revision's renders, newest first.

    Args:
        revision_id: The revision's primary key.
        svc: PDF production.

    Returns:
        list[RenderRead]: The recorded renders.
    """
    with http_errors():
        return await svc.list_for_revision(revision_id)


@router.get(
    "/revisions/{revision_id}/preview.html",
    operation_id="preview_revision_html",
    response_class=Response,
    responses={**COMMON_RESPONSES, 200: {"content": {"text/html": {}}}},
)
async def preview_revision_html(
    revision_id: int, svc: RenderService = Depends(get_render_service)
) -> Response:
    """Return the assembled sheet as HTML, without producing a PDF.

    Useful when iterating on the template: the HTML is exactly what WeasyPrint is handed,
    so a layout problem visible here is a layout problem in the PDF.

    Args:
        revision_id: The revision to lay out.
        svc: PDF production.

    Returns:
        Response: The self-contained HTML document.
    """
    with http_errors():
        html = await svc.build_html(revision_id)
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get(
    "/revisions/{revision_id}/sheet.pdf",
    operation_id="download_latest_sheet",
    response_class=Response,
    responses={**COMMON_RESPONSES, 200: {"content": {"application/pdf": {}}}},
)
async def download_latest_sheet(
    revision_id: int,
    renders: RenderService = Depends(get_render_service),
    assets: AssetService = Depends(get_asset_service),
) -> Response:
    """Download a revision's most recent PDF.

    Args:
        revision_id: The revision's primary key.
        renders: PDF production.
        assets: Asset reads.

    Returns:
        Response: The PDF bytes.

    Raises:
        HTTPException: 404 if the revision has never been rendered.
    """
    with http_errors():
        latest = await renders.latest(revision_id)
        if latest is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"revision {revision_id} has not been rendered yet",
            )
        asset, data = await assets.read(latest.pdf_asset_id)

    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f'inline; filename="{asset.original_filename or "sheet.pdf"}"')
        },
    )


@router.get(
    "/assets/{asset_id}",
    response_model=AssetRead,
    operation_id="get_asset",
    responses=COMMON_RESPONSES,
)
async def get_asset(asset_id: int, svc: AssetService = Depends(get_asset_service)) -> AssetRead:
    """Fetch an asset's metadata.

    Args:
        asset_id: The asset's primary key.
        svc: Asset reads.

    Returns:
        AssetRead: The stored asset.
    """
    with http_errors():
        return await svc.get(asset_id)


@router.get(
    "/assets/{asset_id}/content",
    operation_id="download_asset",
    response_class=Response,
    responses=COMMON_RESPONSES,
)
async def download_asset(asset_id: int, svc: AssetService = Depends(get_asset_service)) -> Response:
    """Download an asset's bytes.

    Args:
        asset_id: The asset's primary key.
        svc: Asset reads.

    Returns:
        Response: The file contents, with its recorded content type.
    """
    with http_errors():
        asset, data = await svc.read(asset_id)
    return Response(content=data, media_type=asset.content_type)
