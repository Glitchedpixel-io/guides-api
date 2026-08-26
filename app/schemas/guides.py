"""Schemas for guides and guide revisions."""

from __future__ import annotations

import re
from datetime import date

from pydantic import Field, field_validator

from app.schemas.base import IDMixin, TimestampsMixin, UTCBaseModel
from app.schemas.enums import RevisionStatus

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class GuideAttrs(UTCBaseModel):
    """Fields that identify a guide, independent of any revision."""

    slug: str = Field(max_length=160)
    doc_number: str = Field(max_length=64)
    title: str = Field(min_length=1, max_length=240)
    title_break_after: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Word index the masthead breaks after, for the two-line title. Omit to print "
            "the title on one line."
        ),
    )

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        """Reject slugs that would not survive a URL or a filename.

        Args:
            value: The proposed slug.

        Returns:
            str: The validated slug.

        Raises:
            ValueError: If the slug is not lowercase kebab-case.
        """
        if not SLUG_RE.match(value):
            raise ValueError("slug must be lowercase kebab-case, e.g. 'hole-pattern-measurement'")
        return value


class GuideCreate(GuideAttrs):
    """Request body for creating a guide."""


class GuideCreateInternal(GuideAttrs):
    """What the repository accepts when creating a guide."""


class GuideRead(GuideAttrs, IDMixin, TimestampsMixin):
    """A guide as returned by the API."""


class GuidePatch(UTCBaseModel):
    """Request body for updating a guide. Every field is optional."""

    slug: str | None = Field(default=None, max_length=160)
    doc_number: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    title_break_after: int | None = Field(default=None, ge=1)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        """Apply the slug format rule when a slug is supplied.

        Args:
            value: The proposed slug, or ``None``.

        Returns:
            str | None: The validated slug.

        Raises:
            ValueError: If the slug is not lowercase kebab-case.
        """
        if value is not None and not SLUG_RE.match(value):
            raise ValueError("slug must be lowercase kebab-case, e.g. 'hole-pattern-measurement'")
        return value


class GuidePatchInternal(GuidePatch):
    """What the repository accepts when updating a guide."""


class RevisionAttrs(UTCBaseModel):
    """Fields carried by one issued revision of a guide."""

    rev_label: str = Field(
        min_length=1,
        max_length=32,
        description="Engineering revision letter ('C') or semantic version ('1.2').",
    )
    revision_date: date
    change_note: str = ""
    author_byline: str = Field(min_length=1, max_length=120)
    approved_by: str | None = Field(default=None, max_length=120)
    purpose: str = ""
    units: str | None = Field(default=None, max_length=16)
    scale: str | None = Field(default=None, max_length=16)
    tolerance: str | None = Field(default=None, max_length=32)


class RevisionCreate(RevisionAttrs):
    """Request body for creating a revision. New revisions always start as drafts."""


class RevisionCreateInternal(RevisionAttrs):
    """What the repository accepts when creating a revision."""

    guide_id: int
    status: RevisionStatus = RevisionStatus.DRAFT


class RevisionRead(RevisionAttrs, IDMixin, TimestampsMixin):
    """A revision as returned by the API."""

    guide_id: int
    status: RevisionStatus


class RevisionPatch(UTCBaseModel):
    """Request body for updating a revision.

    ``status`` is absent on purpose: publishing and archiving are transitions with rules,
    exposed as their own endpoints rather than as a field anyone can set.
    """

    rev_label: str | None = Field(default=None, min_length=1, max_length=32)
    revision_date: date | None = None
    change_note: str | None = None
    author_byline: str | None = Field(default=None, min_length=1, max_length=120)
    approved_by: str | None = Field(default=None, max_length=120)
    purpose: str | None = None
    units: str | None = Field(default=None, max_length=16)
    scale: str | None = Field(default=None, max_length=16)
    tolerance: str | None = Field(default=None, max_length=32)


class RevisionPatchInternal(RevisionPatch):
    """What the repository accepts when updating a revision."""

    status: RevisionStatus | None = None
