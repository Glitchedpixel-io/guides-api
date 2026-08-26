"""Persistence layer.

Services depend on the protocols; ``dependencies.py`` is the only module that names an
implementation.
"""

# protocols
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

# errors
from app.repositories.errors import (
    DatabaseLockedError,
    DuplicateEntityError,
    InvalidDataError,
    NotFoundError,
    RepositoryError,
    RequiredFieldError,
)

# implementations
from app.repositories.guide_repo import SQLAlchemyGuideRepository, SQLAlchemyRevisionRepository
from app.repositories.protocols import (
    AssetRepository,
    BomItemRepository,
    GuideRepository,
    RenderRepository,
    RequiredToolRepository,
    RevisionRepository,
    SafetyWarningRepository,
    SketchJobRepository,
    StepRepository,
)
from app.repositories.step_repo import SQLAlchemyStepRepository

__all__ = [
    # protocols
    "AssetRepository",
    "BomItemRepository",
    "GuideRepository",
    "RenderRepository",
    "RequiredToolRepository",
    "RevisionRepository",
    "SafetyWarningRepository",
    "SketchJobRepository",
    "StepRepository",
    # implementations
    "SQLAlchemyAssetRepository",
    "SQLAlchemyBomItemRepository",
    "SQLAlchemyGuideRepository",
    "SQLAlchemyRenderRepository",
    "SQLAlchemyRequiredToolRepository",
    "SQLAlchemyRevisionRepository",
    "SQLAlchemySafetyWarningRepository",
    "SQLAlchemySketchJobRepository",
    "SQLAlchemyStepRepository",
    # errors
    "DatabaseLockedError",
    "DuplicateEntityError",
    "InvalidDataError",
    "NotFoundError",
    "RepositoryError",
    "RequiredFieldError",
]
