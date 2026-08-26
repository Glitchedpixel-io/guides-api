"""Enumerations shared by the ORM models, the API schemas, and the renderer."""

from __future__ import annotations

from enum import StrEnum


class RevisionStatus(StrEnum):
    """Lifecycle of a guide revision.

    A revision is editable only while ``DRAFT``. Publishing freezes its content so the PDF
    someone is holding can always be reproduced from the database.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Severity(StrEnum):
    """Safety-warning severity, following the ANSI Z535 signal words.

    The order here is descending severity, which is also the order the C panel prints in.
    """

    DANGER = "danger"
    WARNING = "warning"
    CAUTION = "caution"
    NOTICE = "notice"


class PlateLayout(StrEnum):
    """How much vertical space a step's drawing plate claims.

    ``FULL`` gives roughly one step per page; ``HALF`` lets two steps share a page, which
    is what page 2 of the reference sheet does.
    """

    FULL = "full"
    HALF = "half"


class LeaderDir(StrEnum):
    """Which side of a callout bubble its leader line extends towards."""

    LEFT = "left"
    RIGHT = "right"


class AssetKind(StrEnum):
    """What a stored asset is, which determines how the renderer embeds it."""

    SKETCH = "sketch"
    REDRAWN_SVG = "redrawn_svg"
    PHOTO = "photo"
    PDF = "pdf"
    LOGO = "logo"


class SketchJobStatus(StrEnum):
    """Lifecycle of a sketch-redraw job.

    ``SUCCEEDED`` means an SVG was produced and stored, not that anyone accepted it — a
    human still has to promote the result onto the step.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
