"""Schemas for stored assets, sketch-redraw jobs, and renders."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from app.schemas.base import IDMixin, Timestamp, TimestampsMixin, UTCBaseModel
from app.schemas.blocks import BomItemRead, RequiredToolRead, SafetyWarningRead
from app.schemas.enums import AssetKind, SketchJobStatus
from app.schemas.guides import GuideRead, RevisionRead
from app.schemas.steps import StepRead


class AssetAttrs(UTCBaseModel):
    """Metadata describing a stored file."""

    kind: AssetKind
    content_type: str = Field(max_length=120)
    storage_path: str
    sha256: str = Field(min_length=64, max_length=64)
    byte_size: int = Field(ge=0)
    original_filename: str | None = Field(default=None, max_length=255)


class AssetCreateInternal(AssetAttrs):
    """What the repository accepts when recording a stored file.

    There is no public ``AssetCreate``: assets are only ever created as a side effect of
    an upload or a render, never posted directly.
    """


class AssetRead(AssetAttrs, IDMixin, TimestampsMixin):
    """A stored asset as returned by the API."""


class SketchJobAttrs(UTCBaseModel):
    """State of one sketch-redraw attempt."""

    status: SketchJobStatus
    model: str
    prompt_version: str
    notes: str = ""
    error: str | None = None
    completed_at: Timestamp | None = None


class SketchJobCreateInternal(UTCBaseModel):
    """What the repository accepts when queuing a redraw."""

    step_id: int
    source_asset_id: int
    model: str
    prompt_version: str


class SketchJobRead(SketchJobAttrs, IDMixin, TimestampsMixin):
    """A redraw job as returned by the API."""

    step_id: int
    source_asset_id: int
    result_asset_id: int | None


class SketchJobPatchInternal(UTCBaseModel):
    """What the repository accepts when advancing a redraw job."""

    status: SketchJobStatus | None = None
    result_asset_id: int | None = None
    notes: str | None = None
    error: str | None = None
    completed_at: Timestamp | None = None


class RenderRead(UTCBaseModel, IDMixin):
    """A produced PDF as returned by the API."""

    revision_id: int
    pdf_asset_id: int
    template_version: str
    page_count: int
    rendered_at: Timestamp


class RenderCreateInternal(UTCBaseModel):
    """What the repository accepts when recording a render."""

    revision_id: int
    pdf_asset_id: int
    template_version: str
    page_count: int
    rendered_at: Timestamp


class RevisionHistoryEntry(UTCBaseModel):
    """One row of the sheet's printed revision history.

    Attributes:
        rev_label: The revision letter or version.
        revision_date: The edition date.
        change_note: What changed in that revision.
        author_byline: Who made the change.
    """

    rev_label: str
    revision_date: date
    change_note: str
    author_byline: str


class RevisionDocument(UTCBaseModel):
    """The whole revision, assembled for rendering or for a single API read.

    The renderer takes exactly this and nothing else, which is what makes template tests
    possible without a database.
    """

    guide: GuideRead
    revision: RevisionRead
    steps: list[StepRead] = Field(default_factory=list)
    bom_items: list[BomItemRead] = Field(default_factory=list)
    required_tools: list[RequiredToolRead] = Field(default_factory=list)
    safety_warnings: list[SafetyWarningRead] = Field(default_factory=list)
    history: list[RevisionHistoryEntry] = Field(default_factory=list)
