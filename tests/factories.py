"""Fixture builders shared across the test tiers.

These construct schema objects directly rather than going through the database, so unit
and rendering tests need no Postgres.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.schemas.assets import RevisionDocument, RevisionHistoryEntry
from app.schemas.blocks import BomItemRead, RequiredToolRead, SafetyWarningRead
from app.schemas.enums import LeaderDir, PlateLayout, RevisionStatus, Severity
from app.schemas.guides import GuideRead, RevisionRead
from app.schemas.steps import CalloutRead, StepRead

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)

# A minimal, valid drawing in the house style — one square and a circle.
SAMPLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">'
    '<rect x="10" y="10" width="180" height="100" fill="none" stroke="#14140f" stroke-width="2.8"/>'
    '<circle cx="60" cy="60" r="18" fill="none" stroke="#14140f" stroke-width="1.8"/>'
    '<circle cx="140" cy="60" r="18" fill="none" stroke="#14140f" stroke-width="1.8"/>'
    '<line x1="60" y1="60" x2="140" y2="60" stroke="#14140f" stroke-width="1" '
    'stroke-dasharray="6 4"/>'
    "</svg>"
)


def make_guide(**overrides: object) -> GuideRead:
    """Build a guide read model.

    Args:
        **overrides: Field values to replace.

    Returns:
        GuideRead: The fixture guide.
    """
    data: dict[str, object] = {
        "id": 1,
        "slug": "hole-pattern-measurement",
        "doc_number": "MSO-114",
        "title": "Hole Pattern Measurement Chevron Plate Flat Steel",
        "title_break_after": 3,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return GuideRead(**data)  # type: ignore[arg-type]


def make_revision(**overrides: object) -> RevisionRead:
    """Build a revision read model.

    Args:
        **overrides: Field values to replace.

    Returns:
        RevisionRead: The fixture revision.
    """
    data: dict[str, object] = {
        "id": 10,
        "guide_id": 1,
        "rev_label": "C",
        "revision_date": date(2026, 8, 26),
        "status": RevisionStatus.PUBLISHED,
        "change_note": "Added A->C check span; tolerance tightened to +/-0.05.",
        "author_byline": "R. Vane",
        "approved_by": "K. Ashdown",
        "purpose": (
            "Determine the diameter of three drilled holes in an existing chevron-form "
            "steel plate and the centre-to-centre distances between them."
        ),
        "units": "mm",
        "scale": "1:1",
        "tolerance": "+/-0.05",
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return RevisionRead(**data)  # type: ignore[arg-type]


def make_step(position: int, **overrides: object) -> StepRead:
    """Build a step read model with two callouts.

    Args:
        position: The step's order on the sheet.
        **overrides: Field values to replace.

    Returns:
        StepRead: The fixture step.
    """
    data: dict[str, object] = {
        "id": 100 + position,
        "revision_id": 10,
        "position": position,
        "title": f"Measurement stage {position}",
        "instructions": (
            "Degrease both faces. Break every hole edge with the deburring tool until a "
            "fingernail no longer catches. Lay the plate flat, burr side up, on the "
            "surface plate and press each corner in turn - rock must be nil."
        ),
        "est_minutes": 6 + position,
        "plate_layout": PlateLayout.HALF,
        "side_note": "",
        "image_asset_id": 500 + position,
        "created_at": NOW,
        "updated_at": NOW,
        "callouts": [
            CalloutRead(
                id=200 + position * 2,
                step_id=100 + position,
                index=1,
                x_pct=22.0,
                y_pct=18.0,
                leader_dir=LeaderDir.RIGHT,
                leader_length_pct=20.0,
                label="Burr side up.",
            ),
            CalloutRead(
                id=201 + position * 2,
                step_id=100 + position,
                index=2,
                x_pct=78.0,
                y_pct=72.0,
                leader_dir=LeaderDir.LEFT,
                leader_length_pct=18.0,
                label="Max shim gap 0.10 mm.",
            ),
        ],
    }
    data.update(overrides)
    return StepRead(**data)  # type: ignore[arg-type]


def make_document(step_count: int = 3, **overrides: object) -> RevisionDocument:
    """Build a complete renderable revision.

    Args:
        step_count: How many steps to include.
        **overrides: Top-level fields to replace.

    Returns:
        RevisionDocument: The fixture document.
    """
    data: dict[str, object] = {
        "guide": make_guide(),
        "revision": make_revision(),
        "steps": [make_step(i) for i in range(1, step_count + 1)],
        "bom_items": [
            BomItemRead(
                id=1,
                revision_id=10,
                position=1,
                description="Chevron plate specimen",
                quantity="1",
                unit="off",
                part_number=None,
            ),
            BomItemRead(
                id=2,
                revision_id=10,
                position=2,
                description="Layout dye, blue",
                quantity=None,
                unit=None,
                part_number="LD-2201",
            ),
            BomItemRead(
                id=3,
                revision_id=10,
                position=3,
                description="Pin gauge set, 3-14 mm",
                quantity="1",
                unit="set",
                part_number=None,
            ),
        ],
        "required_tools": [
            RequiredToolRead(
                id=1, revision_id=10, position=1, name="Caliper, digital", spec="0.01 mm"
            ),
            RequiredToolRead(
                id=2, revision_id=10, position=2, name="Bore gauge", spec="telescoping"
            ),
            RequiredToolRead(
                id=3, revision_id=10, position=3, name="Surface plate", spec="grade B"
            ),
        ],
        "safety_warnings": [
            SafetyWarningRead(
                id=1,
                revision_id=10,
                position=1,
                severity=Severity.WARNING,
                text="Sheared edges cut. Cut-resistant gloves until deburred.",
            ),
            SafetyWarningRead(
                id=2,
                revision_id=10,
                position=2,
                severity=Severity.CAUTION,
                text="No compressed air on chips.",
            ),
            SafetyWarningRead(
                id=3,
                revision_id=10,
                position=3,
                severity=Severity.NOTICE,
                text="Caliper is a measuring instrument, not a pry bar.",
            ),
        ],
        "history": [
            RevisionHistoryEntry(
                rev_label="A",
                revision_date=date(2025, 11, 4),
                change_note="Issued for use.",
                author_byline="R. Vane",
            ),
            RevisionHistoryEntry(
                rev_label="B",
                revision_date=date(2026, 3, 19),
                change_note="Bore gauge method replaces caliper-in-bore.",
                author_byline="R. Vane",
            ),
            RevisionHistoryEntry(
                rev_label="C",
                revision_date=date(2026, 8, 26),
                change_note="Added A->C check span; tolerance tightened.",
                author_byline="K. Ashdown",
            ),
        ],
    }
    data.update(overrides)
    return RevisionDocument(**data)  # type: ignore[arg-type]
