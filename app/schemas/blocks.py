"""Schemas for the three optional front-matter blocks."""

from __future__ import annotations

from pydantic import Field

from app.schemas.base import IDMixin, UTCBaseModel
from app.schemas.enums import Severity


class BomItemAttrs(UTCBaseModel):
    """One line of the bill of materials."""

    description: str = Field(min_length=1, max_length=240)
    quantity: str | None = Field(default=None, max_length=32)
    unit: str | None = Field(default=None, max_length=32)
    part_number: str | None = Field(default=None, max_length=64)


class BomItemCreate(BomItemAttrs):
    """Request body for adding a BOM line."""


class BomItemCreateInternal(BomItemAttrs):
    """What the repository accepts when creating a BOM line."""

    revision_id: int
    position: int


class BomItemRead(BomItemAttrs, IDMixin):
    """A BOM line as returned by the API."""

    revision_id: int
    position: int


class BomItemPatch(UTCBaseModel):
    """Request body for updating a BOM line."""

    description: str | None = Field(default=None, min_length=1, max_length=240)
    quantity: str | None = Field(default=None, max_length=32)
    unit: str | None = Field(default=None, max_length=32)
    part_number: str | None = Field(default=None, max_length=64)


class BomItemPatchInternal(BomItemPatch):
    """What the repository accepts when updating a BOM line."""

    position: int | None = None


class RequiredToolAttrs(UTCBaseModel):
    """One line of the required-tools list."""

    name: str = Field(min_length=1, max_length=240)
    spec: str | None = Field(default=None, max_length=240)


class RequiredToolCreate(RequiredToolAttrs):
    """Request body for adding a required tool."""


class RequiredToolCreateInternal(RequiredToolAttrs):
    """What the repository accepts when creating a required tool."""

    revision_id: int
    position: int


class RequiredToolRead(RequiredToolAttrs, IDMixin):
    """A required tool as returned by the API."""

    revision_id: int
    position: int


class RequiredToolPatch(UTCBaseModel):
    """Request body for updating a required tool."""

    name: str | None = Field(default=None, min_length=1, max_length=240)
    spec: str | None = Field(default=None, max_length=240)


class RequiredToolPatchInternal(RequiredToolPatch):
    """What the repository accepts when updating a required tool."""

    position: int | None = None


class SafetyWarningAttrs(UTCBaseModel):
    """One safety warning, with its ANSI Z535 signal word."""

    severity: Severity = Severity.CAUTION
    text: str = Field(min_length=1)


class SafetyWarningCreate(SafetyWarningAttrs):
    """Request body for adding a safety warning."""


class SafetyWarningCreateInternal(SafetyWarningAttrs):
    """What the repository accepts when creating a safety warning."""

    revision_id: int
    position: int


class SafetyWarningRead(SafetyWarningAttrs, IDMixin):
    """A safety warning as returned by the API."""

    revision_id: int
    position: int


class SafetyWarningPatch(UTCBaseModel):
    """Request body for updating a safety warning."""

    severity: Severity | None = None
    text: str | None = Field(default=None, min_length=1)


class SafetyWarningPatchInternal(SafetyWarningPatch):
    """What the repository accepts when updating a safety warning."""

    position: int | None = None
