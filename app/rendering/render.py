"""Turn a revision into the printed sheet.

HTML assembly is a pure function of its inputs — no database, no filesystem, no network —
so the layout can be tested without WeasyPrint and rendered without either. Only
:func:`render_pdf` touches the PDF engine.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import segno
import weasyprint
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from app.config.schema import RenderConfig
from app.schemas.assets import RevisionDocument
from app.schemas.steps import CalloutRead

TEMPLATE_DIR = Path(__file__).parent / "templates"
CSS_PATH = TEMPLATE_DIR / "blueprint.css"

# Content types that go into the plate as inline vector markup rather than as an <img>.
SVG_CONTENT_TYPE = "image/svg+xml"

# Sheet geometry, in inches. These are the numbers the design is drawn to.
FRAME_INSET = 0.3  # outer rule, from the paper edge
REG_INSET = 0.09  # registration marks, from the paper edge
REG_SIZE = 0.2
CONTENT_INSET = 0.59  # where the frame's inner padding ends
HEADER_BAND = 0.72  # running header, inside the frame
FOOTER_BAND = 0.95  # scale bar and title block, inside the frame

MARGIN_TOP = CONTENT_INSET + HEADER_BAND
MARGIN_BOTTOM = CONTENT_INSET + FOOTER_BAND
MARGIN_SIDE = CONTENT_INSET

# Paper sizes, in inches. The key is what goes into the CSS `size` descriptor.
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "letter": (8.5, 11.0),
    "legal": (8.5, 14.0),
    "a4": (8.2677, 11.6929),
    "a3": (11.6929, 16.5354),
}


class UnknownPageSizeError(ValueError):
    """The configured page size is not one the sheet geometry knows how to lay out."""


@dataclass(frozen=True)
class FrameGeometry:
    """Where the fixed sheet furniture sits, in inches.

    WeasyPrint lays a ``position: fixed`` box out against each page's *content* area, not
    against the paper, so every offset here is measured from the content origin and is
    negative where the furniture sits out in the page margin. That also means the page
    margins must be identical on every page — a ``@page :first`` margin override would
    slide the frame on page 1 only. The margins are emitted from here for that reason.

    Attributes:
        top: Frame's top edge, from the content origin.
        left: Frame's left edge, from the content origin.
        width: Frame's outer width.
        height: Frame's outer height.
        reg_top: Top row of registration marks.
        reg_bottom: Bottom row of registration marks.
        reg_left: Left column of registration marks.
        reg_right: Right column of registration marks.
        margin_top: Page margin, emitted so CSS and Python cannot drift.
        margin_right: Page margin.
        margin_bottom: Page margin.
        margin_left: Page margin.
        header_band: Height of the running-header band inside the frame.
    """

    top: float
    left: float
    width: float
    height: float
    reg_top: float
    reg_bottom: float
    reg_left: float
    reg_right: float
    margin_top: float
    margin_right: float
    margin_bottom: float
    margin_left: float
    header_band: float


def page_geometry(page_size: str) -> FrameGeometry:
    """Compute the fixed-furniture offsets for a paper size.

    Args:
        page_size: A key of :data:`PAGE_SIZES`, e.g. ``letter``.

    Returns:
        FrameGeometry: Offsets in inches, relative to the page content origin.

    Raises:
        UnknownPageSizeError: If the size is not one we have dimensions for. Guessing
            would put the frame in the wrong place on every sheet without any error.
    """
    key = page_size.strip().lower()
    if key not in PAGE_SIZES:
        raise UnknownPageSizeError(
            f"{page_size!r} is not a known page size; use one of {sorted(PAGE_SIZES)}"
        )
    width, height = PAGE_SIZES[key]
    return FrameGeometry(
        top=round(FRAME_INSET - MARGIN_TOP, 4),
        left=round(FRAME_INSET - MARGIN_SIDE, 4),
        width=round(width - 2 * FRAME_INSET, 4),
        height=round(height - 2 * FRAME_INSET, 4),
        reg_top=round(REG_INSET - MARGIN_TOP, 4),
        reg_bottom=round(height - REG_INSET - REG_SIZE - MARGIN_TOP, 4),
        reg_left=round(REG_INSET - MARGIN_SIDE, 4),
        reg_right=round(width - REG_INSET - REG_SIZE - MARGIN_SIDE, 4),
        margin_top=MARGIN_TOP,
        margin_right=MARGIN_SIDE,
        margin_bottom=MARGIN_BOTTOM,
        margin_left=MARGIN_SIDE,
        header_band=HEADER_BAND,
    )


@dataclass(frozen=True)
class StepArt:
    """The drawing to place in one step's plate.

    Attributes:
        content_type: MIME type of the stored asset.
        data: The asset's bytes. SVG is inlined; anything else becomes a data URI.
    """

    content_type: str
    data: bytes


@dataclass(frozen=True)
class StepView:
    """One step, prepared for the template.

    Attributes:
        position: The step's 1-based order on the sheet.
        title: The step's heading.
        instructions: The prose body.
        est_minutes: Estimated duration, or ``None`` to omit the badge.
        plate_layout: How tall the drawing plate is.
        side_note: Free text printed beside the instructions.
        callouts: Numbered annotations over the plate.
        art_svg: Inline SVG markup, already sanitised.
        art_src: A ``data:`` URI for raster art.
    """

    position: int
    title: str
    instructions: str
    est_minutes: int | None
    plate_layout: object
    side_note: str
    callouts: list[CalloutRead] = field(default_factory=list)
    art_svg: Markup | None = None
    art_src: str | None = None


def split_title(title: str, break_after: int | None) -> list[str]:
    """Split the masthead title into its printed lines.

    WeasyPrint ignores ``text-wrap: balance``, and the reference design hard-codes its own
    line break, so where the title breaks is authored data rather than a guess.

    Args:
        title: The full title.
        break_after: Word index (1-based) to break after, or ``None`` for one line.

    Returns:
        list[str]: One or two lines.
    """
    words = title.split()
    if not break_after or break_after >= len(words) or break_after < 1:
        return [title]
    return [" ".join(words[:break_after]), " ".join(words[break_after:])]


def data_uri(content_type: str, data: bytes) -> str:
    """Encode bytes as a ``data:`` URI.

    Embedding rather than linking is what keeps the rendered HTML self-contained, so the
    PDF never depends on a file still being where it was at render time.

    Args:
        content_type: The MIME type to declare.
        data: The raw bytes.

    Returns:
        str: A base64 ``data:`` URI.
    """
    encoded = base64.standard_b64encode(data).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


@lru_cache
def _environment() -> Environment:
    """Build the Jinja environment.

    ``StrictUndefined`` is deliberate: a typo in a template variable should fail the
    render rather than print an empty cell on a safety document.

    Returns:
        Environment: The cached environment.
    """
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=False,
    )


@lru_cache
def _stylesheet() -> str:
    """Read the house stylesheet.

    Returns:
        str: The CSS source.
    """
    return CSS_PATH.read_text(encoding="utf-8")


def _build_steps(document: RevisionDocument, art: dict[int, StepArt]) -> list[StepView]:
    """Prepare each step for the template, embedding its drawing.

    Args:
        document: The assembled revision.
        art: Drawings keyed by step id. Steps with no entry render an empty plate.

    Returns:
        list[StepView]: Steps in order, ready to render.
    """
    views: list[StepView] = []
    for step in document.steps:
        drawing = art.get(step.id)
        art_svg: Markup | None = None
        art_src: str | None = None
        if drawing is not None:
            if drawing.content_type == SVG_CONTENT_TYPE:
                # Safe to mark up: every stored SVG has already been through the
                # sanitiser, which is the only path by which one can reach the database.
                art_svg = Markup(drawing.data.decode("utf-8"))
            else:
                art_src = data_uri(drawing.content_type, drawing.data)
        views.append(
            StepView(
                position=step.position,
                title=step.title,
                instructions=step.instructions,
                est_minutes=step.est_minutes,
                plate_layout=step.plate_layout,
                side_note=step.side_note,
                callouts=sorted(step.callouts, key=lambda c: c.index),
                art_svg=art_svg,
                art_src=art_src,
            )
        )
    return views


def _qr(url: str) -> Markup | None:
    """Render a support QR as inline SVG.

    Args:
        url: The URL to encode. Empty disables the panel.

    Returns:
        Markup | None: Inline SVG, or ``None`` when there is no URL.
    """
    if not url:
        return None
    code = segno.make(url, error="m")
    return Markup(code.svg_inline(dark="#14140f", light=None, border=0))


def render_html(
    document: RevisionDocument,
    config: RenderConfig,
    art: dict[int, StepArt] | None = None,
    logo: StepArt | None = None,
) -> str:
    """Assemble the complete, self-contained sheet HTML.

    Args:
        document: The revision and everything printed on its sheet.
        config: Render settings, including the house style.
        art: Step drawings keyed by step id.
        logo: The organisation logo, if one is configured.

    Returns:
        str: A single HTML document with no external references.
    """
    style = config.style
    support_url = (
        style.support_url_template.format(doc_number=document.guide.doc_number)
        if style.support_url_template
        else ""
    )

    template = _environment().get_template("sheet.html.j2")
    return template.render(
        css=Markup(_stylesheet()),
        page_size=config.page_size.strip().lower(),
        frame=page_geometry(config.page_size),
        style=style,
        guide=document.guide,
        revision=document.revision,
        title_lines=split_title(document.guide.title, document.guide.title_break_after),
        steps=_build_steps(document, art or {}),
        bom_items=document.bom_items,
        required_tools=document.required_tools,
        safety_warnings=document.safety_warnings,
        history=document.history,
        logo_src=data_uri(logo.content_type, logo.data) if logo else None,
        qr_svg=_qr(support_url),
        support_url=support_url,
    )


@dataclass(frozen=True)
class RenderedPdf:
    """A produced PDF.

    Attributes:
        data: The PDF bytes.
        page_count: How many pages it came to.
    """

    data: bytes
    page_count: int


def render_pdf(html: str) -> RenderedPdf:
    """Rasterise assembled HTML into a PDF.

    Args:
        html: A self-contained HTML document.

    Returns:
        RenderedPdf: The bytes and the page count.
    """
    # `base_url` is the template directory so the stylesheet's relative @font-face URLs
    # resolve to the vendored files. Nothing else in the document is a relative reference.
    document = weasyprint.HTML(string=html, base_url=str(TEMPLATE_DIR)).render()
    return RenderedPdf(data=document.write_pdf(), page_count=len(document.pages))
