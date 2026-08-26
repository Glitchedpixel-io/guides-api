"""Liveness and build-identity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config.schema import RenderConfig, SketchConfig
from app.config.settings import get_render_config, get_sketch_config
from app.routers.base import QuietClientErrorRoute
from app.version import get_version

router = APIRouter(route_class=QuietClientErrorRoute)


class HealthRead(BaseModel):
    """Service liveness and the identity of what is running.

    Attributes:
        status: Always ``ok`` when the process is serving.
        version: The package version, derived from the git tag at build time.
        template_version: Which sheet template renders would use.
        sketch_enabled: Whether sketch redraw is available in this environment.
        sketch_model: The model redraws would call.
    """

    status: str
    version: str
    template_version: str
    sketch_enabled: bool
    sketch_model: str


@router.get("/health", response_model=HealthRead, operation_id="get_health")
async def get_health(
    render: RenderConfig = Depends(get_render_config),
    sketch: SketchConfig = Depends(get_sketch_config),
) -> HealthRead:
    """Report liveness and the identity of the running build.

    The template version is included deliberately: two instances on different template
    versions produce visibly different sheets from identical data, and that is otherwise
    invisible.

    Args:
        render: Render settings.
        sketch: Sketch settings.

    Returns:
        HealthRead: The service's status.
    """
    return HealthRead(
        status="ok",
        version=get_version(),
        template_version=render.template_version,
        sketch_enabled=sketch.enabled,
        sketch_model=sketch.model,
    )
