"""The single source of truth for wiring sessions, repositories, and services."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import RenderConfig, SketchConfig, StorageConfig
from app.config.settings import get_render_config, get_sketch_config, get_storage_config
from app.database import AsyncSessionLocal
from app.repositories.asset_repo import (
    SQLAlchemyAssetRepository,
    SQLAlchemyRenderRepository,
    SQLAlchemySketchJobRepository,
)
from app.repositories.block_repo import (
    SQLAlchemyBomItemRepository,
    SQLAlchemyRequiredToolRepository,
    SQLAlchemySafetyWarningRepository,
)
from app.repositories.guide_repo import SQLAlchemyGuideRepository, SQLAlchemyRevisionRepository
from app.repositories.protocols import (
    AssetRepository,
    GuideRepository,
    RenderRepository,
    RevisionRepository,
    SketchJobRepository,
    StepRepository,
)
from app.repositories.step_repo import SQLAlchemyStepRepository
from app.schemas.blocks import (
    BomItemCreateInternal,
    BomItemPatchInternal,
    BomItemRead,
    RequiredToolCreateInternal,
    RequiredToolPatchInternal,
    RequiredToolRead,
    SafetyWarningCreateInternal,
    SafetyWarningPatchInternal,
    SafetyWarningRead,
)
from app.services.asset_service import AssetService
from app.services.content_service import BlockService, StepService
from app.services.document_service import DocumentService
from app.services.guide_service import GuideService, RevisionService
from app.services.render_service import RenderService
from app.services.sketch_service import SketchService
from app.sketch.client import SketchRedrawClient
from app.storage import AssetStore

# session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield one session per request.

    Yields:
        AsyncSession: A session closed when the request ends.
    """
    async with AsyncSessionLocal() as session:
        yield session


# repositories
# These exist mainly as named, introspectable nodes in the dependency graph. A service
# needing more than one repository takes the *session* instead and builds them itself —
# chaining Depends(get_*_repository) would open a separate session per repository and
# silently break transactional consistency.


def get_guide_repository(db: AsyncSession = Depends(get_db)) -> GuideRepository:
    """Build the guide repository.

    Args:
        db: The request's session.

    Returns:
        GuideRepository: Storage for guide identities.
    """
    return SQLAlchemyGuideRepository(db)


def get_revision_repository(db: AsyncSession = Depends(get_db)) -> RevisionRepository:
    """Build the revision repository.

    Args:
        db: The request's session.

    Returns:
        RevisionRepository: Storage for revisions.
    """
    return SQLAlchemyRevisionRepository(db)


def get_step_repository(db: AsyncSession = Depends(get_db)) -> StepRepository:
    """Build the step repository.

    Args:
        db: The request's session.

    Returns:
        StepRepository: Storage for steps and callouts.
    """
    return SQLAlchemyStepRepository(db)


def get_asset_repository(db: AsyncSession = Depends(get_db)) -> AssetRepository:
    """Build the asset repository.

    Args:
        db: The request's session.

    Returns:
        AssetRepository: Storage for asset metadata.
    """
    return SQLAlchemyAssetRepository(db)


def get_sketch_job_repository(db: AsyncSession = Depends(get_db)) -> SketchJobRepository:
    """Build the sketch-job repository.

    Args:
        db: The request's session.

    Returns:
        SketchJobRepository: Storage for redraw jobs.
    """
    return SQLAlchemySketchJobRepository(db)


def get_render_repository(db: AsyncSession = Depends(get_db)) -> RenderRepository:
    """Build the render repository.

    Args:
        db: The request's session.

    Returns:
        RenderRepository: Storage for produced PDFs.
    """
    return SQLAlchemyRenderRepository(db)


# services


def get_guide_service(repo: GuideRepository = Depends(get_guide_repository)) -> GuideService:
    """Build the guide service.

    Args:
        repo: Storage for guide identities.

    Returns:
        GuideService: Guide business logic.
    """
    return GuideService(repo)


def get_revision_service(db: AsyncSession = Depends(get_db)) -> RevisionService:
    """Build the revision service on one shared session.

    Args:
        db: The request's session.

    Returns:
        RevisionService: Revision business logic.
    """
    return RevisionService(SQLAlchemyGuideRepository(db), SQLAlchemyRevisionRepository(db))


def get_step_service(db: AsyncSession = Depends(get_db)) -> StepService:
    """Build the step service on one shared session.

    Args:
        db: The request's session.

    Returns:
        StepService: Step and callout business logic.
    """
    return StepService(
        SQLAlchemyStepRepository(db),
        RevisionService(SQLAlchemyGuideRepository(db), SQLAlchemyRevisionRepository(db)),
    )


def _revision_service(db: AsyncSession) -> RevisionService:
    """Build a revision service from a session.

    Args:
        db: The session to build on.

    Returns:
        RevisionService: Revision business logic.
    """
    return RevisionService(SQLAlchemyGuideRepository(db), SQLAlchemyRevisionRepository(db))


def get_bom_service(db: AsyncSession = Depends(get_db)) -> BlockService[BomItemRead]:
    """Build the bill-of-materials block service.

    Args:
        db: The request's session.

    Returns:
        BlockService[BomItemRead]: Editing for panel A.
    """
    return BlockService(
        SQLAlchemyBomItemRepository(db),
        _revision_service(db),
        BomItemCreateInternal,
        BomItemPatchInternal,
        BomItemRead,
    )


def get_tool_service(db: AsyncSession = Depends(get_db)) -> BlockService[RequiredToolRead]:
    """Build the required-tools block service.

    Args:
        db: The request's session.

    Returns:
        BlockService[RequiredToolRead]: Editing for panel B.
    """
    return BlockService(
        SQLAlchemyRequiredToolRepository(db),
        _revision_service(db),
        RequiredToolCreateInternal,
        RequiredToolPatchInternal,
        RequiredToolRead,
    )


def get_warning_service(db: AsyncSession = Depends(get_db)) -> BlockService[SafetyWarningRead]:
    """Build the safety-warnings block service.

    Args:
        db: The request's session.

    Returns:
        BlockService[SafetyWarningRead]: Editing for panel C.
    """
    return BlockService(
        SQLAlchemySafetyWarningRepository(db),
        _revision_service(db),
        SafetyWarningCreateInternal,
        SafetyWarningPatchInternal,
        SafetyWarningRead,
    )


def get_document_service(db: AsyncSession = Depends(get_db)) -> DocumentService:
    """Build the document assembler on one shared session.

    Args:
        db: The request's session.

    Returns:
        DocumentService: Assembles the printable revision.
    """
    return DocumentService(
        SQLAlchemyGuideRepository(db),
        SQLAlchemyRevisionRepository(db),
        SQLAlchemyStepRepository(db),
        SQLAlchemyBomItemRepository(db),
        SQLAlchemyRequiredToolRepository(db),
        SQLAlchemySafetyWarningRepository(db),
    )


def get_asset_store(config: StorageConfig = Depends(get_storage_config)) -> AssetStore:
    """Build the filesystem asset store.

    Args:
        config: Storage configuration.

    Returns:
        AssetStore: The byte store.
    """
    return AssetStore(config)


def get_asset_service(
    db: AsyncSession = Depends(get_db),
    store: AssetStore = Depends(get_asset_store),
) -> AssetService:
    """Build the asset service.

    Args:
        db: The request's session.
        store: The byte store.

    Returns:
        AssetService: Asset business logic.
    """
    return AssetService(SQLAlchemyAssetRepository(db), store)


def get_render_service(
    db: AsyncSession = Depends(get_db),
    store: AssetStore = Depends(get_asset_store),
    config: RenderConfig = Depends(get_render_config),
) -> RenderService:
    """Build the render service on one shared session.

    Args:
        db: The request's session.
        store: The byte store.
        config: Render settings.

    Returns:
        RenderService: PDF production.
    """
    return RenderService(
        get_document_service(db),
        AssetService(SQLAlchemyAssetRepository(db), store),
        SQLAlchemyRenderRepository(db),
        config,
    )


def get_sketch_client(config: SketchConfig = Depends(get_sketch_config)) -> SketchRedrawClient:
    """Build the Claude-backed redraw client.

    Args:
        config: Sketch settings.

    Returns:
        SketchRedrawClient: The redraw client.
    """
    return SketchRedrawClient(config)


def get_sketch_service(
    db: AsyncSession = Depends(get_db),
    store: AssetStore = Depends(get_asset_store),
    config: SketchConfig = Depends(get_sketch_config),
    client: SketchRedrawClient = Depends(get_sketch_client),
) -> SketchService:
    """Build the sketch service on one shared session.

    Args:
        db: The request's session.
        store: The byte store.
        config: Sketch settings.
        client: The redraw client.

    Returns:
        SketchService: Redraw orchestration.
    """
    return SketchService(
        SQLAlchemySketchJobRepository(db),
        AssetService(SQLAlchemyAssetRepository(db), store),
        get_step_service(db),
        client,
        config,
    )
