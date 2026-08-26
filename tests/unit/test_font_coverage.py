"""Every character the sheet prints must exist in the vendored fonts.

This exists because of a real near-miss. The Claude Design canvas used ``⌀`` (U+2300
DIAMETER SIGN) in the symbols legend and it looked correct in a browser, where a system
fallback font supplied the glyph. Neither Archivo Narrow nor IBM Plex Mono has it, so the
PDF would have printed tofu — a missing glyph on a metrology sheet's symbol key.

WeasyPrint substitutes silently, so nothing else would have caught it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.schema import SheetStyleConfig
from app.rendering.render import TEMPLATE_DIR

pytestmark = pytest.mark.unit

FONT_DIR = TEMPLATE_DIR.parent / "fonts"

# Characters the templates and default style put on the page beyond plain ASCII.
REQUIRED_CHARACTERS = "·±ØÆ—→"


def _codepoints(path: Path) -> set[int]:
    """Read every codepoint a font can render.

    Args:
        path: Path to a TrueType font.

    Returns:
        set[int]: The codepoints in the font's character map.
    """
    fontTools = pytest.importorskip("fontTools.ttLib", reason="fontTools not installed")
    font = fontTools.TTFont(str(path), fontNumber=0, lazy=True)
    covered: set[int] = set()
    for table in font["cmap"].tables:
        covered |= set(table.cmap)
    font.close()
    return covered


def test_fonts_are_vendored() -> None:
    """The seven static weights are committed, not fetched at render time."""
    found = sorted(p.name for p in FONT_DIR.glob("*.ttf"))
    assert len(found) == 7, f"expected 7 vendored fonts, found {found}"


@pytest.mark.parametrize("font_path", sorted(FONT_DIR.glob("*.ttf")), ids=lambda p: p.name)
def test_font_covers_every_character_the_sheet_prints(font_path: Path) -> None:
    """Each vendored font can render every non-ASCII character the sheet uses.

    Args:
        font_path: One vendored font.
    """
    covered = _codepoints(font_path)
    missing = [c for c in REQUIRED_CHARACTERS if ord(c) not in covered]
    assert not missing, f"{font_path.name} cannot render {missing}"


@pytest.mark.parametrize("font_path", sorted(FONT_DIR.glob("*.ttf")), ids=lambda p: p.name)
def test_font_covers_the_symbols_legend(font_path: Path) -> None:
    """Every glyph in the default symbols legend renders.

    A symbol key that prints a replacement box is worse than no symbol key.

    Args:
        font_path: One vendored font.
    """
    covered = _codepoints(font_path)
    glyphs = "".join(entry.glyph for entry in SheetStyleConfig().symbols)
    missing = [c for c in glyphs if ord(c) not in covered]
    assert not missing, f"{font_path.name} cannot render legend glyph(s) {missing}"


def test_u2300_is_not_used_anywhere() -> None:
    """Guard the specific character that started this.

    U+2300 is absent from both families. If it reappears in the style defaults or the
    templates, it will print as tofu.
    """
    offenders = []
    for path in [*TEMPLATE_DIR.glob("*"), Path(__file__).parents[2] / "app/config/schema.py"]:
        if path.is_file() and "⌀" in path.read_text(encoding="utf-8"):
            # The schema names it once, inside the comment explaining why it is banned.
            if path.name == "schema.py":
                continue
            offenders.append(path.name)
    assert not offenders, f"U+2300 has no glyph in the vendored fonts; found in {offenders}"
