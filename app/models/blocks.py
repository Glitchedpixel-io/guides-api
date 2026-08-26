"""The three optional front-matter blocks: A · BOM, B · Tools, C · Safety.

Each is a child table rather than a JSON column. The requirement is "an optional *set*",
and a set the API cannot address item-by-item forces a whole-document rewrite on every
edit — which in turn makes concurrent authoring lossy.
"""

from __future__ import annotations

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import SCHEMA_NAME, Base
from app.models.guide import GuideRevision
from app.models.mixins import fk
from app.schemas.enums import Severity


class BomItem(Base):
    """One line of the bill of materials (panel A)."""

    __tablename__ = "bom_items"
    __table_args__ = (
        UniqueConstraint("revision_id", "position", name="uq_bom_items_revision_position"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey(fk("guide_revisions"), ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    revision: Mapped[GuideRevision] = relationship(back_populates="bom_items")


class RequiredTool(Base):
    """One line of the required-tools list (panel B)."""

    __tablename__ = "required_tools"
    __table_args__ = (
        UniqueConstraint("revision_id", "position", name="uq_required_tools_revision_position"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey(fk("guide_revisions"), ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    spec: Mapped[str | None] = mapped_column(String(240), nullable=True)

    revision: Mapped[GuideRevision] = relationship(back_populates="required_tools")


class SafetyWarning(Base):
    """One safety warning (panel C), carrying an ANSI Z535 signal word."""

    __tablename__ = "safety_warnings"
    __table_args__ = (
        UniqueConstraint("revision_id", "position", name="uq_safety_warnings_revision_position"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey(fk("guide_revisions"), ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, native_enum=False, length=16),
        nullable=False,
        default=Severity.CAUTION,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    revision: Mapped[GuideRevision] = relationship(back_populates="safety_warnings")
