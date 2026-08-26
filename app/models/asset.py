"""Stored binary assets, sketch-redraw jobs, and render records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import SCHEMA_NAME, Base
from app.models.mixins import TimestampedMixin, fk
from app.schemas.enums import AssetKind, SketchJobStatus


class Asset(TimestampedMixin, Base):
    """A file on the asset volume.

    Bytes live on disk, content-addressed by sha256; the row holds only the relative path.
    Nothing is stored as a database blob, matching the sibling services' idiom.
    """

    __tablename__ = "assets"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[AssetKind] = mapped_column(
        Enum(AssetKind, native_enum=False, length=16), nullable=False
    )
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SketchJob(TimestampedMixin, Base):
    """One attempt to redraw a hand-drawn sketch in the house style.

    The row is the source of truth, not the in-process task: a job left ``RUNNING`` by a
    restart is re-queued at startup rather than being lost.
    """

    __tablename__ = "sketch_jobs"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_id: Mapped[int] = mapped_column(
        ForeignKey(fk("steps"), ondelete="CASCADE"), nullable=False, index=True
    )
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey(fk("assets"), ondelete="RESTRICT"), nullable=False
    )
    # Populated on success. Deliberately NOT copied onto the step — a human promotes it.
    result_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey(fk("assets"), ondelete="SET NULL"), nullable=True
    )
    status: Mapped[SketchJobStatus] = mapped_column(
        Enum(SketchJobStatus, native_enum=False, length=16),
        nullable=False,
        default=SketchJobStatus.PENDING,
        index=True,
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which house-style prompt produced this drawing, so we know what predates a restyle.
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Render(Base):
    """A produced PDF, tied to the revision *and* the template that made it."""

    __tablename__ = "renders"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey(fk("guide_revisions"), ondelete="CASCADE"), nullable=False, index=True
    )
    pdf_asset_id: Mapped[int] = mapped_column(
        ForeignKey(fk("assets"), ondelete="RESTRICT"), nullable=False
    )
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rendered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
