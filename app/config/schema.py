"""Configuration interface for the rest of the application.

These frozen dataclasses are the only config types anything outside ``app/config/`` may
depend on. They know nothing about how their values are sourced — that is
``app/config/settings.py``'s job, and ``pydantic-settings`` must not leak past it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Narrowed to what the SDKs actually accept. A free-form string here fails deep inside
# logfire or the Anthropic client at runtime, long after the typo was made.
Effort = Literal["low", "medium", "high", "xhigh", "max"]
LogLevel = Literal["trace", "debug", "info", "notice", "warn", "warning", "error", "fatal"]


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection settings for the Postgres instance that owns guide content.

    Attributes:
        url: SQLAlchemy async URL, e.g. ``postgresql+asyncpg://user@host/guides``.
        pool_size: Number of connections kept open in the pool.
        max_overflow: Extra connections allowed above ``pool_size`` under load.
        pool_timeout: Seconds to wait for a free connection before failing.
        require_migration_head: Refuse to boot unless the DB is at the alembic head.
    """

    url: str
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: int = 30
    require_migration_head: bool = True


@dataclass(frozen=True)
class StorageConfig:
    """Where binary assets live on disk.

    Assets are content-addressed by sha256 under ``asset_root``; the database stores only
    the relative path. Nothing is kept as a database blob.

    Attributes:
        asset_root: Directory holding every stored asset.
        max_upload_bytes: Hard ceiling on a single uploaded file.
    """

    asset_root: Path
    max_upload_bytes: int = 20 * 1024 * 1024


@dataclass(frozen=True)
class SketchConfig:
    """Settings for the Claude-backed sketch redraw.

    Attributes:
        enabled: When false, redraw endpoints return 503 rather than calling out.
        api_key: Anthropic API key. ``None`` lets the SDK resolve its own credentials.
        model: Model id. Opus 5 is the default; it has vision input and writes the SVG.
        effort: ``output_config.effort`` — low | medium | high | xhigh | max.
        max_tokens: Output ceiling. SVG line art is long, so this is generous.
        timeout_seconds: Per-request timeout handed to the SDK.
        prompt_version: Identifier for the house-style prompt in use, recorded on each job.
    """

    enabled: bool = True
    api_key: str | None = None
    model: str = "claude-opus-5"
    effort: Effort = "high"
    max_tokens: int = 32000
    timeout_seconds: float = 300.0
    prompt_version: str = "blueprint-v1"


@dataclass(frozen=True)
class SymbolLegendEntry:
    """One row of the sheet's symbols legend.

    Attributes:
        kind: ``glyph`` prints ``glyph`` as text; ``index`` draws a numbered bubble;
            ``hatch`` draws a hatched swatch. The latter two have no text equivalent.
        meaning: The short description printed beside it.
        glyph: The character to print when ``kind`` is ``glyph``.
    """

    kind: str
    meaning: str
    glyph: str = ""


@dataclass(frozen=True)
class SheetStyleConfig:
    """House style for the printed sheet.

    Everything here is a property of the *design*, not of any one guide. Putting the
    footer note on the guide table would mean editing every guide to change a footer.

    Attributes:
        organisation: First segment of the page-1 eyebrow.
        department: Second segment of the eyebrow.
        document_kind: Third segment, e.g. "Procedure Sheet".
        logo_path: Absolute path to a transparent PNG or SVG logo, if any.
        frame_weight: Outer sheet frame width — ``hairline`` | ``standard`` | ``heavy``.
        plate_grid: Draw the graph-paper grid inside drawing plates.
        registration_marks: Draw the four corner registration marks.
        footer_note: Left-hand footer line, e.g. "UNCONTROLLED WHEN PRINTED".
        retention_note: Footer line on the record page.
        support_url_template: ``str.format``-style template taking ``doc_number``; the QR
            encodes the result. Empty disables the QR panel.
        symbols: The symbols legend rows.
    """

    organisation: str = "Eldritch County"
    department: str = "Metrology Standards Office"
    document_kind: str = "Procedure Sheet"
    logo_path: Path | None = None
    frame_weight: str = "standard"
    plate_grid: bool = True
    registration_marks: bool = True
    footer_note: str = "HATCHED PANELS DENOTE SAFETY-CRITICAL CONTENT · DO NOT REDRAW BY HAND"
    retention_note: str = "RETAIN COMPLETED SHEET 7 YEARS · UNCONTROLLED WHEN PRINTED"
    support_url_template: str = ""
    # The centre-distance mark is `Ø↔`, not the U+2300 DIAMETER SIGN `⌀` the browser
    # mockup used: neither Archivo Narrow nor IBM Plex Mono has a glyph for U+2300, so on
    # the canvas a system fallback font quietly supplied it while the PDF would have
    # printed tofu. Any glyph added here must exist in the vendored fonts —
    # tests/unit/test_font_coverage.py enforces that.
    symbols: tuple[SymbolLegendEntry, ...] = field(
        default_factory=lambda: (
            SymbolLegendEntry(kind="glyph", glyph="Ø", meaning="diameter"),
            SymbolLegendEntry(kind="glyph", glyph="±", meaning="tolerance band"),
            SymbolLegendEntry(kind="glyph", glyph="Ø↔", meaning="centre distance"),
            SymbolLegendEntry(kind="index", meaning="callout index"),
            SymbolLegendEntry(kind="hatch", meaning="section hatch"),
        )
    )


# Frame weights the template understands, mapped to the CSS border width the canvas used.
FRAME_WEIGHTS: dict[str, str] = {
    "hairline": "1.5px",
    "standard": "2.5px",
    "heavy": "4px",
}


@dataclass(frozen=True)
class RenderConfig:
    """PDF rendering settings.

    Attributes:
        template_version: Recorded on every render so a PDF in the wild is traceable to
            the template that produced it, not just to the revision.
        page_size: A CSS ``@page size`` value. The design is drawn for US Letter.
        style: The house style applied to every sheet.
    """

    template_version: str = "blueprint-1.0"
    page_size: str = "letter"
    style: SheetStyleConfig = field(default_factory=SheetStyleConfig)


@dataclass(frozen=True)
class LoggingConfig:
    """Logfire and console logging settings.

    Attributes:
        env: Deployment environment name reported to Logfire.
        log_level: Minimum level sent to Logfire.
        console_log_level: Minimum level printed locally.
        logfire_token: Write token. Absent means "do not send", not "fail".
        service_version: Version string reported alongside spans.
        logfire_for_sqlalchemy: Instrument the SQLAlchemy engine as well.
    """

    env: str = "development"
    log_level: LogLevel = "info"
    console_log_level: LogLevel = "info"
    logfire_token: str | None = None
    service_version: str = "0.0.0+unknown"
    logfire_for_sqlalchemy: bool = False


@dataclass(frozen=True)
class AppConfig:
    """The whole application's configuration.

    Attributes:
        debug: Enables developer-facing behaviour such as verbose error detail.
        database: Postgres settings.
        storage: Asset storage settings.
        sketch: Sketch-redraw settings.
        render: PDF rendering settings.
        logging: Observability settings.
    """

    debug: bool
    database: DatabaseConfig
    storage: StorageConfig
    sketch: SketchConfig
    render: RenderConfig
    logging: LoggingConfig
