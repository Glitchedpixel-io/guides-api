"""Schemas for steps and their drawing-plate callouts."""

from __future__ import annotations

from pydantic import Field

from app.schemas.base import IDMixin, TimestampsMixin, UTCBaseModel
from app.schemas.enums import LeaderDir, PlateLayout


class CalloutAttrs(UTCBaseModel):
    """A numbered bubble and leader line over a step's drawing plate."""

    index: int = Field(ge=1, description="The number printed in the bubble.")
    x_pct: float = Field(ge=0.0, le=100.0, description="Bubble centre, % of plate width.")
    y_pct: float = Field(ge=0.0, le=100.0, description="Bubble centre, % of plate height.")
    leader_dir: LeaderDir = LeaderDir.RIGHT
    leader_length_pct: float = Field(default=18.0, ge=0.0, le=100.0)
    label: str = ""


class CalloutCreate(CalloutAttrs):
    """Request body for adding a callout to a step."""


class CalloutCreateInternal(CalloutAttrs):
    """What the repository accepts when creating a callout."""

    step_id: int


class CalloutRead(CalloutAttrs, IDMixin):
    """A callout as returned by the API."""

    step_id: int


class CalloutPatch(UTCBaseModel):
    """Request body for updating a callout."""

    index: int | None = Field(default=None, ge=1)
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    leader_dir: LeaderDir | None = None
    leader_length_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    label: str | None = None


class CalloutPatchInternal(CalloutPatch):
    """What the repository accepts when updating a callout."""


class StepAttrs(UTCBaseModel):
    """The authored content of one step."""

    title: str = Field(min_length=1, max_length=200)
    instructions: str = ""
    est_minutes: int | None = Field(default=None, ge=0)
    plate_layout: PlateLayout = PlateLayout.HALF
    side_note: str = ""


class StepCreate(StepAttrs):
    """Request body for adding a step.

    ``position`` is omitted: a new step is appended, and reordering is its own endpoint so
    the renumber happens in one transaction rather than as a race between two writers.
    """


class StepCreateInternal(StepAttrs):
    """What the repository accepts when creating a step."""

    revision_id: int
    position: int


class StepRead(StepAttrs, IDMixin, TimestampsMixin):
    """A step as returned by the API, with its callouts."""

    revision_id: int
    position: int
    image_asset_id: int | None
    callouts: list[CalloutRead] = Field(default_factory=list)


class StepPatch(UTCBaseModel):
    """Request body for updating a step.

    ``position`` is absent — use the reorder endpoint. ``image_asset_id`` is absent —
    images arrive by upload or by promoting a finished sketch redraw.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = None
    est_minutes: int | None = Field(default=None, ge=0)
    plate_layout: PlateLayout | None = None
    side_note: str | None = None


class StepPatchInternal(StepPatch):
    """What the repository accepts when updating a step."""

    position: int | None = None
    image_asset_id: int | None = None
