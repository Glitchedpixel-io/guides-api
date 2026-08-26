"""API-tier fixtures: a real app, faked services, no database.

Services are faked with ``create_autospec(..., spec_set=True)`` so a router calling a
method the service does not have fails the test rather than passing against a permissive
mock.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.app_factory import create_app
from app.config.schema import AppConfig
from app.dependencies import (
    get_asset_service,
    get_bom_service,
    get_document_service,
    get_guide_service,
    get_render_service,
    get_sketch_service,
    get_step_service,
    get_tool_service,
    get_warning_service,
)
from app.services.asset_service import AssetService
from app.services.content_service import BlockService, StepService
from app.services.document_service import DocumentService
from app.services.guide_service import GuideService, RevisionService
from app.services.render_service import RenderService
from app.services.sketch_service import SketchService

# The revision service is reached through its own dependency, imported separately so the
# override map below stays a single readable table.
from app.dependencies import get_revision_service


@pytest.fixture
def guide_service() -> AsyncMock:
    """Faked guide service.

    Returns:
        AsyncMock: Spec'd against ``GuideService``.
    """
    return create_autospec(GuideService, instance=True, spec_set=True)


@pytest.fixture
def revision_service() -> AsyncMock:
    """Faked revision service.

    Returns:
        AsyncMock: Spec'd against ``RevisionService``.
    """
    return create_autospec(RevisionService, instance=True, spec_set=True)


@pytest.fixture
def step_service() -> AsyncMock:
    """Faked step service.

    Returns:
        AsyncMock: Spec'd against ``StepService``.
    """
    return create_autospec(StepService, instance=True, spec_set=True)


@pytest.fixture
def block_service() -> AsyncMock:
    """Faked front-matter block service, shared by all three panels.

    Returns:
        AsyncMock: Spec'd against ``BlockService``.
    """
    return create_autospec(BlockService, instance=True, spec_set=True)


@pytest.fixture
def document_service() -> AsyncMock:
    """Faked document assembler.

    Returns:
        AsyncMock: Spec'd against ``DocumentService``.
    """
    return create_autospec(DocumentService, instance=True, spec_set=True)


@pytest.fixture
def render_service() -> AsyncMock:
    """Faked render service.

    Returns:
        AsyncMock: Spec'd against ``RenderService``.
    """
    return create_autospec(RenderService, instance=True, spec_set=True)


@pytest.fixture
def asset_service() -> AsyncMock:
    """Faked asset service.

    Returns:
        AsyncMock: Spec'd against ``AssetService``.
    """
    return create_autospec(AssetService, instance=True, spec_set=True)


@pytest.fixture
def sketch_service() -> AsyncMock:
    """Faked sketch service.

    Returns:
        AsyncMock: Spec'd against ``SketchService``.
    """
    return create_autospec(SketchService, instance=True, spec_set=True)


@pytest.fixture
def api_app(
    app_config: AppConfig,
    guide_service: AsyncMock,
    revision_service: AsyncMock,
    step_service: AsyncMock,
    block_service: AsyncMock,
    document_service: AsyncMock,
    render_service: AsyncMock,
    asset_service: AsyncMock,
    sketch_service: AsyncMock,
) -> FastAPI:
    """Build the real application with every service faked.

    Args:
        app_config: The test configuration.
        guide_service: Faked guide service.
        revision_service: Faked revision service.
        step_service: Faked step service.
        block_service: Faked block service.
        document_service: Faked document assembler.
        render_service: Faked render service.
        asset_service: Faked asset service.
        sketch_service: Faked sketch service.

    Returns:
        FastAPI: The application, wired to fakes.
    """
    app = create_app(app_config)
    app.dependency_overrides.update(
        {
            get_guide_service: lambda: guide_service,
            get_revision_service: lambda: revision_service,
            get_step_service: lambda: step_service,
            get_bom_service: lambda: block_service,
            get_tool_service: lambda: block_service,
            get_warning_service: lambda: block_service,
            get_document_service: lambda: document_service,
            get_render_service: lambda: render_service,
            get_asset_service: lambda: asset_service,
            get_sketch_service: lambda: sketch_service,
        }
    )
    return app


@pytest.fixture
async def client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Drive the app over an in-process ASGI transport.

    The lifespan is deliberately not run: startup would touch the database and the asset
    volume, and none of the API-tier assertions need either.

    Args:
        api_app: The application under test.

    Yields:
        AsyncClient: A client bound to the app.
    """
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    api_app.dependency_overrides.clear()
