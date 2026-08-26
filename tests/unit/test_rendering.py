"""Sheet assembly: geometry, title splitting, and the HTML the renderer produces.

These never invoke WeasyPrint. ``render_html`` is a pure function of its inputs, which is
what makes the layout contract testable without a PDF engine or a database.
"""

from __future__ import annotations

import base64

import pytest

from app.config.schema import RenderConfig, SheetStyleConfig
from app.rendering.render import (
    FRAME_INSET,
    MARGIN_SIDE,
    MARGIN_TOP,
    PAGE_SIZES,
    UnknownPageSizeError,
    data_uri,
    page_geometry,
    render_html,
    split_title,
)
from app.rendering.render import StepArt
from app.schemas.enums import PlateLayout, RevisionStatus
from tests.factories import SAMPLE_SVG, make_document, make_revision, make_step

pytestmark = pytest.mark.unit


def body_of(html: str) -> str:
    """Return just the document body.

    The stylesheet is inlined into the page, so every class name appears somewhere in the
    full document. Absence assertions have to be made against the markup, not the CSS.

    Args:
        html: The whole rendered document.

    Returns:
        str: Everything after the opening ``<body>`` tag.
    """
    return html.split("<body>", 1)[1]


class TestSplitTitle:
    """The masthead's two-line title."""

    def test_no_break_point_gives_one_line(self) -> None:
        """Without a break index the title prints on one line."""
        assert split_title("Hole Pattern Measurement", None) == ["Hole Pattern Measurement"]

    def test_breaks_after_the_named_word(self) -> None:
        """The break index counts words, 1-based."""
        assert split_title("A B C D", 2) == ["A B", "C D"]

    @pytest.mark.parametrize("break_after", [0, -1, 4, 99])
    def test_out_of_range_break_falls_back_to_one_line(self, break_after: int) -> None:
        """A break index past the end is ignored rather than producing an empty line.

        Args:
            break_after: An index that cannot split the title.
        """
        assert split_title("A B C D", break_after) == ["A B C D"]


class TestPageGeometry:
    """Fixed-furniture offsets, which are measured from the page content origin."""

    def test_frame_is_inset_from_the_paper_edge(self) -> None:
        """The frame spans the paper less the design's inset on each side."""
        geometry = page_geometry("letter")
        width, height = PAGE_SIZES["letter"]
        assert geometry.width == pytest.approx(width - 2 * FRAME_INSET)
        assert geometry.height == pytest.approx(height - 2 * FRAME_INSET)

    def test_offsets_are_negative_because_the_frame_sits_in_the_margin(self) -> None:
        """WeasyPrint positions fixed boxes from the content origin, not the paper edge.

        The frame is outside the content area, so its offsets must be negative. A
        positive value here would put the frame inside the text column.
        """
        geometry = page_geometry("letter")
        assert geometry.top == pytest.approx(FRAME_INSET - MARGIN_TOP)
        assert geometry.left == pytest.approx(FRAME_INSET - MARGIN_SIDE)
        assert geometry.top < 0
        assert geometry.left < 0

    def test_registration_marks_are_symmetric(self) -> None:
        """The right and bottom marks mirror the left and top ones about the paper."""
        geometry = page_geometry("letter")
        width, height = PAGE_SIZES["letter"]
        assert geometry.reg_left + MARGIN_SIDE == pytest.approx(
            width - (geometry.reg_right + MARGIN_SIDE) - 0.2
        )
        assert geometry.reg_top + MARGIN_TOP == pytest.approx(
            height - (geometry.reg_bottom + MARGIN_TOP) - 0.2
        )

    def test_a4_differs_from_letter(self) -> None:
        """Geometry tracks the paper size rather than being hardcoded."""
        assert page_geometry("a4").width != page_geometry("letter").width

    def test_unknown_size_is_refused(self) -> None:
        """Guessing would misplace the frame on every sheet with no error."""
        with pytest.raises(UnknownPageSizeError, match="not a known page size"):
            page_geometry("tabloid-extra")

    def test_size_is_case_and_space_insensitive(self) -> None:
        """A configured size is normalised rather than rejected on formatting."""
        assert page_geometry("  LETTER ") == page_geometry("letter")


class TestRenderHtml:
    """The assembled sheet HTML."""

    @pytest.fixture
    def config(self) -> RenderConfig:
        """Build a render config with a support URL.

        Returns:
            RenderConfig: Render settings.
        """
        return RenderConfig(
            style=SheetStyleConfig(support_url_template="https://mso.example.test/{doc_number}")
        )

    def test_contains_every_front_matter_block(self, config: RenderConfig) -> None:
        """The three optional panels all reach the sheet when populated.

        Args:
            config: Render settings.
        """
        html = render_html(make_document(), config)
        assert "Bill of Materials" in html
        assert "Required Tools" in html
        assert "Safety" in html
        assert "Chevron plate specimen" in html
        assert "Sheared edges cut" in html

    def test_omits_panels_that_have_no_content(self, config: RenderConfig) -> None:
        """An empty block prints nothing rather than an empty box.

        Args:
            config: Render settings.
        """
        document = make_document(bom_items=[], required_tools=[], safety_warnings=[])
        body = body_of(render_html(document, config))
        assert "Bill of Materials" not in body
        assert 'class="panels"' not in body

    def test_panel_letters_follow_which_panels_are_present(self, config: RenderConfig) -> None:
        """Letters are assigned in order to the panels that exist.

        With no BOM, the tools panel becomes A rather than leaving a gap at A.
        """
        document = make_document(bom_items=[])
        html = render_html(document, config)
        assert "A · Required Tools" in html
        assert "B · Safety" in html

    def test_every_step_and_callout_reaches_the_sheet(self, config: RenderConfig) -> None:
        """Steps print in order with their callout numbers and labels.

        Args:
            config: Render settings.
        """
        html = render_html(make_document(step_count=3), config)
        for position in (1, 2, 3):
            assert f"STEP {position}" in html
        assert "Burr side up." in html
        assert "Max shim gap 0.10 mm." in html

    def test_callouts_are_positioned_from_data(self, config: RenderConfig) -> None:
        """Bubble coordinates come from the row, not from the drawing.

        Args:
            config: Render settings.
        """
        html = render_html(make_document(step_count=1), config)
        assert "left:22.0%" in html
        assert "top:18.0%" in html

    def test_inline_svg_is_embedded_not_linked(self, config: RenderConfig) -> None:
        """Vector art goes into the document as markup so nothing is fetched later.

        Args:
            config: Render settings.
        """
        document = make_document(step_count=1)
        art = {document.steps[0].id: StepArt("image/svg+xml", SAMPLE_SVG.encode())}
        html = render_html(document, config, art)
        assert "<svg" in html
        assert 'viewBox="0 0 200 120"' in html

    def test_raster_art_becomes_a_data_uri(self, config: RenderConfig) -> None:
        """Bitmap art is embedded too, never referenced by path.

        Args:
            config: Render settings.
        """
        document = make_document(step_count=1)
        art = {document.steps[0].id: StepArt("image/png", b"\x89PNG\r\n\x1a\n")}
        html = render_html(document, config, art)
        assert "data:image/png;base64," in html

    def test_step_without_art_renders_an_empty_plate(self, config: RenderConfig) -> None:
        """A missing drawing does not fail the sheet.

        Args:
            config: Render settings.
        """
        html = render_html(make_document(step_count=1), config, art={})
        assert "No drawing for this step" in html

    def test_has_no_external_references(self, config: RenderConfig) -> None:
        """Nothing in the document is fetched at render time.

        A sheet whose typography or imagery depends on network reachability is not
        reproducible, and production has no egress.
        """
        document = make_document(step_count=2)
        art = {s.id: StepArt("image/svg+xml", SAMPLE_SVG.encode()) for s in document.steps}
        html = render_html(document, config, art)
        assert "https://fonts.googleapis.com" not in html
        assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")

    def test_plate_layout_drives_the_plate_class(self, config: RenderConfig) -> None:
        """A full-page step asks for the taller plate.

        Args:
            config: Render settings.
        """
        document = make_document(step_count=1, steps=[make_step(1, plate_layout=PlateLayout.FULL)])
        assert "plate--full" in render_html(document, config)

    def test_revision_history_is_printed(self, config: RenderConfig) -> None:
        """The sheet carries its own revision history.

        Args:
            config: Render settings.
        """
        html = render_html(make_document(), config)
        assert "Revision History" in html
        assert "Bore gauge method replaces caliper-in-bore." in html

    def test_qr_is_generated_in_process(self, config: RenderConfig) -> None:
        """The support QR is inline SVG, not a fetched image.

        Args:
            config: Render settings.
        """
        html = render_html(make_document(), config)
        assert "https://mso.example.test/MSO-114" in html
        assert "qr-panel" in html

    def test_qr_panel_is_omitted_without_a_support_url(self) -> None:
        """No configured URL means no QR panel rather than an empty box."""
        body = body_of(render_html(make_document(), RenderConfig()))
        assert "qr-panel" not in body

    def test_geometry_is_injected_so_css_and_python_cannot_drift(
        self, config: RenderConfig
    ) -> None:
        """Page margins are emitted from Python, not duplicated in the stylesheet.

        Args:
            config: Render settings.
        """
        html = render_html(make_document(), config)
        assert f"margin: {MARGIN_TOP}in" in html

    def test_draft_status_is_visible_on_the_sheet(self, config: RenderConfig) -> None:
        """A draft prints as such, so an unissued sheet is not mistaken for an issued one.

        Args:
            config: Render settings.
        """
        document = make_document(revision=make_revision(status=RevisionStatus.DRAFT))
        assert "DRAFT" in render_html(document, config)


def test_data_uri_round_trips() -> None:
    """Embedded bytes decode back to what went in."""
    uri = data_uri("image/png", b"hello")
    assert uri.startswith("data:image/png;base64,")
    assert base64.standard_b64decode(uri.split(",", 1)[1]) == b"hello"
