"""Application assembly: lifespan, routers, instrumentation."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import logfire
from fastapi import FastAPI

from app.config.schema import AppConfig
from app.database import AsyncSessionLocal
from app.repositories.asset_repo import SQLAlchemySketchJobRepository
from app.routers import blocks, guides, health, renders, revisions, sketches, steps
from app.services.sketch_service import reap_stalled_jobs
from app.version import get_version


async def _reap_stalled_sketch_jobs(config: AppConfig) -> None:
    """Return redraw jobs abandoned by a previous process to the queue.

    Args:
        config: The application configuration.
    """
    if not config.sketch.enabled:
        return
    async with AsyncSessionLocal() as session:
        requeued = await reap_stalled_jobs(SQLAlchemySketchJobRepository(session))
    if requeued:
        logfire.info("re-queued stalled sketch jobs", count=len(requeued))


def get_lifespan(
    config: AppConfig,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build the application lifespan, closed over configuration.

    Args:
        config: The application configuration.

    Returns:
        Callable: An async context manager factory FastAPI can use as ``lifespan``.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Start and stop long-lived state.

        Args:
            app: The FastAPI application.

        Yields:
            None: While the application serves requests.
        """
        # startup
        config.storage.asset_root.mkdir(parents=True, exist_ok=True)
        await _reap_stalled_sketch_jobs(config)
        logfire.info(
            "guides-api started",
            version=get_version(),
            template_version=config.render.template_version,
            sketch_enabled=config.sketch.enabled,
        )

        yield

        # shutdown — the engine is the only long-lived resource this service owns.
        from app.database import get_engine  # noqa: PLC0415 - avoids an import cycle

        await get_engine().dispose()

    return lifespan


def _include_routers(api: FastAPI) -> None:
    """Mount every router under its prefix.

    Args:
        api: The FastAPI application.
    """
    api.include_router(health.router, tags=["health"])
    api.include_router(guides.router, prefix="/api/guides", tags=["guides"])
    api.include_router(revisions.router, prefix="/api/revisions", tags=["revisions"])
    api.include_router(steps.router, prefix="/api/steps", tags=["steps"])
    api.include_router(blocks.router, prefix="/api", tags=["front matter"])
    api.include_router(sketches.router, prefix="/api", tags=["sketch redraw"])
    api.include_router(renders.router, prefix="/api", tags=["rendering"])


def create_app(config: AppConfig) -> FastAPI:
    """Build the application.

    Args:
        config: The application configuration.

    Returns:
        FastAPI: The assembled application.
    """
    api = FastAPI(
        title="guides-api",
        version=get_version(),
        description=(
            "Authoring and PDF rendering for illustrated how-to guides. Content is "
            "versioned per revision; a published revision is frozen so any issued sheet "
            "stays reproducible."
        ),
        lifespan=get_lifespan(config),
    )
    _include_routers(api)

    # Last, so every route is registered before instrumentation wraps them.
    logfire.instrument_fastapi(api)
    return api
