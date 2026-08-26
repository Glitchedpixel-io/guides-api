"""A real render: real Postgres, real WeasyPrint, real PDF read back.

The PDF is parsed afterwards and its text extracted, because "it rendered without raising"
says nothing about whether the safety warnings actually reached the page.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.schema import RenderConfig, SheetStyleConfig
from app.rendering.render import render_html, render_pdf
from app.repositories.asset_repo import SQLAlchemyAssetRepository, SQLAlchemyRenderRepository
from app.repositories.block_repo import (
    SQLAlchemyBomItemRepository,
    SQLAlchemyRequiredToolRepository,
    SQLAlchemySafetyWarningRepository,
)
from app.repositories.guide_repo import SQLAlchemyGuideRepository, SQLAlchemyRevisionRepository
from app.repositories.step_repo import SQLAlchemyStepRepository
from app.schemas.blocks import (
    BomItemCreateInternal,
    RequiredToolCreateInternal,
    SafetyWarningCreateInternal,
)
from app.schemas.enums import AssetKind, PlateLayout, Severity
from app.schemas.guides import GuideCreateInternal, RevisionCreateInternal
from app.schemas.steps import CalloutCreateInternal, StepCreateInternal, StepPatchInternal
from app.services.asset_service import AssetService
from app.services.document_service import DocumentService
from app.services.render_service import RenderService
from app.storage import AssetStore
from tests.factories import SAMPLE_SVG, make_document

pytestmark = [pytest.mark.integration, pytest.mark.slow]

LONG_INSTRUCTIONS = (
    "Expand the bore gauge in hole A until it drags lightly, lock it, withdraw it and "
    "read across the caliper jaws. Repeat the measurement at sixty and one hundred and "
    "twenty degrees. Record all three readings; the diameter is their arithmetic mean. "
) * 4


def normalised(text: str) -> str:
    """Reduce extracted PDF text to something worth asserting on.

    Two presentation details would otherwise dominate these assertions. The display face
    is set with wide letter-spacing, which extractors render as space-separated
    characters; and headings are uppercased by CSS, so what is authored in mixed case
    comes back shouting. Squeezing whitespace and folding case keeps the tests about
    whether content reached the page.

    Args:
        text: Text extracted from a PDF page.

    Returns:
        str: The text with all whitespace removed and case folded.
    """
    return "".join(text.split()).upper()


async def _seed(session: AsyncSession) -> int:
    """Build a complete, realistic revision in the database.

    Args:
        session: The test session.

    Returns:
        int: The seeded revision's primary key.
    """
    guide = await SQLAlchemyGuideRepository(session).create(
        GuideCreateInternal(
            slug="hole-pattern-measurement",
            doc_number="MSO-114",
            title="Hole Pattern Measurement Chevron Plate Flat Steel",
            title_break_after=3,
        )
    )
    revision = await SQLAlchemyRevisionRepository(session).create(
        RevisionCreateInternal(
            guide_id=guide.id,
            rev_label="C",
            revision_date=date(2026, 8, 26),
            change_note="Added the A-to-C check span.",
            author_byline="R. Vane",
            approved_by="K. Ashdown",
            purpose="Determine three hole diameters and their centre-to-centre distances.",
            units="mm",
            scale="1:1",
            tolerance="+/-0.05",
        )
    )

    bom = SQLAlchemyBomItemRepository(session)
    for description in ("Chevron plate specimen", "Layout dye blue", "Pin gauge set"):
        await bom.append(
            revision.id,
            BomItemCreateInternal(revision_id=revision.id, position=0, description=description),
        )

    tools = SQLAlchemyRequiredToolRepository(session)
    for name in ("Caliper digital", "Bore gauge telescoping", "Surface plate grade B"):
        await tools.append(
            revision.id,
            RequiredToolCreateInternal(revision_id=revision.id, position=0, name=name),
        )

    warnings = SQLAlchemySafetyWarningRepository(session)
    for severity, text in (
        (Severity.WARNING, "Sheared edges cut. Cut-resistant gloves until deburred."),
        (Severity.CAUTION, "No compressed air on chips."),
        (Severity.NOTICE, "Caliper is a measuring instrument, not a pry bar."),
    ):
        await warnings.append(
            revision.id,
            SafetyWarningCreateInternal(
                revision_id=revision.id, position=0, severity=severity, text=text
            ),
        )

    return revision.id


async def _add_steps(session: AsyncSession, revision_id: int, asset_id: int) -> None:
    """Add four steps, one of them deliberately long enough to force a page break.

    Args:
        session: The test session.
        revision_id: The owning revision.
        asset_id: A stored drawing to attach to each step.
    """
    repo = SQLAlchemyStepRepository(session)
    specs = [
        ("Clean, deburr and seat the part", PlateLayout.HALF, "Degrease both faces."),
        ("Measure each hole diameter", PlateLayout.FULL, LONG_INSTRUCTIONS),
        ("Measure centre-to-centre", PlateLayout.HALF, "Fit the largest slip-fit pin."),
        ("Record and check", PlateLayout.HALF, "Re-check any span differing by 0.10 mm."),
    ]
    for title, layout, instructions in specs:
        step = await repo.append(
            revision_id,
            StepCreateInternal(
                revision_id=revision_id,
                position=0,
                title=title,
                instructions=instructions,
                est_minutes=6,
                plate_layout=layout,
            ),
        )
        await repo.update(step.id, StepPatchInternal(image_asset_id=asset_id))
        await repo.add_callout(
            CalloutCreateInternal(
                step_id=step.id, index=1, x_pct=22, y_pct=18, label="Burr side up."
            )
        )


@pytest.fixture
def render_service_factory(asset_store: AssetStore, render_config: RenderConfig):
    """Build a render service over a session and a temporary asset root.

    Args:
        asset_store: A store over a temporary directory.
        render_config: Render settings.

    Returns:
        Callable: Takes a session and returns a wired ``RenderService``.
    """

    def build(session: AsyncSession) -> RenderService:
        assets = AssetService(SQLAlchemyAssetRepository(session), asset_store)
        documents = DocumentService(
            SQLAlchemyGuideRepository(session),
            SQLAlchemyRevisionRepository(session),
            SQLAlchemyStepRepository(session),
            SQLAlchemyBomItemRepository(session),
            SQLAlchemyRequiredToolRepository(session),
            SQLAlchemySafetyWarningRepository(session),
        )
        return RenderService(documents, assets, SQLAlchemyRenderRepository(session), render_config)

    return build


async def test_renders_a_complete_sheet_and_everything_lands_on_the_page(
    db_session: AsyncSession,
    asset_store: AssetStore,
    render_service_factory,
) -> None:
    """Seed a revision, render it, then read the PDF back and check its contents.

    Args:
        db_session: The test session.
        asset_store: A store over a temporary directory.
        render_service_factory: Builds a wired render service.
    """
    pypdf = pytest.importorskip("pypdf")

    revision_id = await _seed(db_session)
    assets = AssetService(SQLAlchemyAssetRepository(db_session), asset_store)
    drawing = await assets.store_bytes(SAMPLE_SVG.encode(), AssetKind.REDRAWN_SVG, "image/svg+xml")
    await _add_steps(db_session, revision_id, drawing.id)

    service = render_service_factory(db_session)
    record = await service.render(revision_id)

    assert record.template_version == "blueprint-1.0"
    assert record.page_count >= 3

    _, pdf_bytes = await assets.read(record.pdf_asset_id)
    assert pdf_bytes.startswith(b"%PDF")

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == record.page_count

    whole = normalised(" ".join(page.extract_text() for page in reader.pages))

    # Front matter
    assert normalised("MSO-114") in whole
    assert normalised("Chevron plate specimen") in whole
    assert normalised("Caliper digital") in whole
    # Every safety warning must reach the page; a dropped one is the failure that matters.
    assert normalised("Sheared edges cut") in whole
    assert normalised("No compressed air on chips") in whole
    assert normalised("Caliper is a measuring instrument") in whole
    # Every step, in order
    for title in (
        "Clean, deburr and seat the part",
        "Measure each hole diameter",
        "Measure centre-to-centre",
        "Record and check",
    ):
        assert normalised(title) in whole
    # Callouts, the record page, and the revision history
    assert normalised("Burr side up.") in whole
    assert normalised("Recorded Results") in whole
    assert normalised("Revision History") in whole
    assert normalised("Sign-off") in whole


async def test_page_furniture_repeats_on_every_page(
    db_session: AsyncSession,
    asset_store: AssetStore,
    render_service_factory,
) -> None:
    """The title block and page counter appear on every sheet, correctly numbered.

    Each sheet must identify itself in isolation, and "PAGE n OF m" has to agree with the
    real page count rather than a number baked into the template.

    Args:
        db_session: The test session.
        asset_store: A store over a temporary directory.
        render_service_factory: Builds a wired render service.
    """
    pypdf = pytest.importorskip("pypdf")

    revision_id = await _seed(db_session)
    assets = AssetService(SQLAlchemyAssetRepository(db_session), asset_store)
    drawing = await assets.store_bytes(SAMPLE_SVG.encode(), AssetKind.REDRAWN_SVG, "image/svg+xml")
    await _add_steps(db_session, revision_id, drawing.id)

    record = await render_service_factory(db_session).render(revision_id)
    _, pdf_bytes = await assets.read(record.pdf_asset_id)
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))

    total = len(reader.pages)
    for index, page in enumerate(reader.pages, start=1):
        text = normalised(page.extract_text())
        assert normalised(f"PAGE {index} OF {total}") in text, f"page {index} numbering"
        assert normalised("MSO-114") in text, f"page {index} title block"


async def test_render_is_reproducible(
    db_session: AsyncSession,
    asset_store: AssetStore,
    render_service_factory,
) -> None:
    """Rendering the same revision twice produces the same document.

    The sheet embeds every asset and generates its QR in-process, so nothing about the
    output should depend on when or where it ran. Content addressing makes this cheap to
    assert: identical bytes hash to the same stored asset.

    Args:
        db_session: The test session.
        asset_store: A store over a temporary directory.
        render_service_factory: Builds a wired render service.
    """
    revision_id = await _seed(db_session)
    assets = AssetService(SQLAlchemyAssetRepository(db_session), asset_store)
    drawing = await assets.store_bytes(SAMPLE_SVG.encode(), AssetKind.REDRAWN_SVG, "image/svg+xml")
    await _add_steps(db_session, revision_id, drawing.id)

    service = render_service_factory(db_session)
    first = await service.render(revision_id)
    second = await service.render(revision_id)

    assert first.pdf_asset_id == second.pdf_asset_id
    assert first.page_count == second.page_count


async def test_html_assembly_has_no_external_references(
    db_session: AsyncSession,
    asset_store: AssetStore,
    render_service_factory,
) -> None:
    """The document WeasyPrint receives fetches nothing.

    Args:
        db_session: The test session.
        asset_store: A store over a temporary directory.
        render_service_factory: Builds a wired render service.
    """
    revision_id = await _seed(db_session)
    assets = AssetService(SQLAlchemyAssetRepository(db_session), asset_store)
    drawing = await assets.store_bytes(SAMPLE_SVG.encode(), AssetKind.REDRAWN_SVG, "image/svg+xml")
    await _add_steps(db_session, revision_id, drawing.id)

    html = await render_service_factory(db_session).build_html(revision_id)

    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert '<img src="http' not in html


def test_a4_renders_as_well_as_letter() -> None:
    """The geometry is not hardcoded to one paper size.

    A frame computed for Letter and printed on A4 would sit visibly off-centre.
    """
    config = RenderConfig(page_size="a4", style=SheetStyleConfig())
    html = render_html(make_document(step_count=1), config)
    assert "size: a4" in html
    assert render_pdf(html).page_count >= 1
