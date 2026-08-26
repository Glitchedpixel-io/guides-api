"""Guide identity and its versioned revisions."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import SCHEMA_NAME, Base
from app.models.mixins import TimestampedMixin, fk
from app.schemas.enums import RevisionStatus

if TYPE_CHECKING:
    # Import-time these would be circular; the modules import this one for its Base.
    from app.models.blocks import BomItem, RequiredTool, SafetyWarning
    from app.models.step import Step


class Guide(TimestampedMixin, Base):
    """A guide's stable identity, independent of any one revision.

    The title lives here rather than on the revision because it is what the document *is*;
    a change of title is a new guide, not a new revision of this one.
    """

    __tablename__ = "guides"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    doc_number: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    # The masthead sets the title over two lines. WeasyPrint ignores `text-wrap: balance`,
    # and the reference design hard-codes its own <br>, so the break point is authored
    # data rather than something the renderer is left to guess.
    title_break_after: Mapped[int | None] = mapped_column(Integer, nullable=True)

    revisions: Mapped[list["GuideRevision"]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="GuideRevision.revision_date",
    )


class GuideRevision(TimestampedMixin, Base):
    """One issued revision of a guide, and the root every content row hangs off.

    Content is versioned because a printed procedure sheet must be traceable to the
    revision that produced it — and because the sheet prints its own revision history.
    """

    __tablename__ = "guide_revisions"
    __table_args__ = (
        UniqueConstraint("guide_id", "rev_label", name="uq_guide_revisions_guide_rev"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guide_id: Mapped[int] = mapped_column(
        ForeignKey(fk("guides"), ondelete="CASCADE"), nullable=False, index=True
    )
    # Free text so both an engineering revision letter ("C") and a semantic version
    # ("1.2") are expressible; the sheet prints it verbatim next to "Rev".
    rev_label: Mapped[str] = mapped_column(String(32), nullable=False)
    revision_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[RevisionStatus] = mapped_column(
        Enum(RevisionStatus, native_enum=False, length=16),
        nullable=False,
        default=RevisionStatus.DRAFT,
    )
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_byline: Mapped[str] = mapped_column(String(120), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    units: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scale: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tolerance: Mapped[str | None] = mapped_column(String(32), nullable=True)

    guide: Mapped[Guide] = relationship(back_populates="revisions")
    steps: Mapped[list["Step"]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="Step.position",
    )
    bom_items: Mapped[list["BomItem"]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="BomItem.position",
    )
    safety_warnings: Mapped[list["SafetyWarning"]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="SafetyWarning.position",
    )
    required_tools: Mapped[list["RequiredTool"]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="RequiredTool.position",
    )
