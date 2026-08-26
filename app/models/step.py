"""Steps and the numbered callouts that annotate their drawing plates."""

from __future__ import annotations

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import SCHEMA_NAME, Base
from app.models.guide import GuideRevision
from app.models.mixins import TimestampedMixin, fk
from app.schemas.enums import LeaderDir, PlateLayout


class Step(TimestampedMixin, Base):
    """One ordered step: a drawing plate plus its instructions.

    Order is a database constraint rather than a convention. Ordering that lives only in
    application code drifts, and for a procedure sheet the order *is* the safety property.
    """

    __tablename__ = "steps"
    __table_args__ = (
        UniqueConstraint("revision_id", "position", name="uq_steps_revision_position"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey(fk("guide_revisions"), ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    est_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plate_layout: Mapped[PlateLayout] = mapped_column(
        Enum(PlateLayout, native_enum=False, length=8),
        nullable=False,
        default=PlateLayout.HALF,
    )
    image_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey(fk("assets"), ondelete="SET NULL"), nullable=True
    )
    # Free-text panel printed beside the instructions, for a data table or a working note.
    side_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    revision: Mapped[GuideRevision] = relationship(back_populates="steps")
    callouts: Mapped[list["StepCallout"]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="StepCallout.index",
    )


class StepCallout(Base):
    """A numbered bubble and leader line placed over a step's drawing plate.

    Callouts are rows, not markup baked into the SVG. That keeps them editable,
    reorderable and translatable, and lets the renderer draw them from data exactly as the
    reference sheet positions them.
    """

    __tablename__ = "step_callouts"
    __table_args__ = (
        UniqueConstraint("step_id", "index", name="uq_step_callouts_step_index"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_id: Mapped[int] = mapped_column(
        ForeignKey(fk("steps"), ondelete="CASCADE"), nullable=False, index=True
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Position as a percentage of the plate box, so a callout survives any plate size.
    x_pct: Mapped[float] = mapped_column(Float, nullable=False)
    y_pct: Mapped[float] = mapped_column(Float, nullable=False)
    leader_dir: Mapped[LeaderDir] = mapped_column(
        Enum(LeaderDir, native_enum=False, length=8),
        nullable=False,
        default=LeaderDir.RIGHT,
    )
    leader_length_pct: Mapped[float] = mapped_column(Float, nullable=False, default=18.0)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")

    step: Mapped[Step] = relationship(back_populates="callouts")
