"""The SVG sanitiser, exercised against hostile input.

This markup is written by a language model and then embedded into a rendered document, so
the interesting cases are all adversarial. Every rejection here is a rejection of something
that would otherwise reach the renderer.
"""

from __future__ import annotations

import pytest

from app.sketch.svg_sanitiser import SvgRejectedError, sanitise_svg

pytestmark = pytest.mark.unit

VALID = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">'
    '<path d="M0 0 L100 60" stroke="#14140f" fill="none" stroke-width="1.4"/>'
    "</svg>"
)


def test_keeps_allowed_geometry_and_paint() -> None:
    """A plain line drawing survives unchanged in substance."""
    result = sanitise_svg(VALID)
    assert "<path" in result
    assert 'd="M0 0 L100 60"' in result
    assert 'stroke="#14140f"' in result
    assert 'viewBox="0 0 100 60"' in result


@pytest.mark.parametrize(
    ("fragment", "banned"),
    [
        ("<script>alert(1)</script>", "script"),
        ("<foreignObject><b>x</b></foreignObject>", "foreignObject"),
        ('<image href="http://evil/x.png"/>', "image"),
        ('<a href="http://evil">t</a>', "<a"),
        ("<animate attributeName='x' to='9'/>", "animate"),
        ("<style>*{fill:red}</style>", "<style"),
        ("<use href='#x'/>", "use"),
    ],
)
def test_strips_disallowed_elements(fragment: str, banned: str) -> None:
    """Scripting, embedding, and animation elements are removed entirely.

    Args:
        fragment: Markup inserted alongside a valid path.
        banned: A substring that must not survive.
    """
    svg = VALID.replace("</svg>", f"{fragment}</svg>")
    assert banned not in sanitise_svg(svg)


@pytest.mark.parametrize(
    "attribute",
    [
        'onclick="steal()"',
        'onload="steal()"',
        'ONMOUSEOVER="steal()"',
        'style="fill:url(#x)"',
        'href="http://evil"',
    ],
)
def test_strips_dangerous_attributes(attribute: str) -> None:
    """Event handlers, inline style, and references are dropped from kept elements.

    Args:
        attribute: The attribute to smuggle in on a kept element.
    """
    svg = VALID.replace("<path ", f"<path {attribute} ")
    result = sanitise_svg(svg)
    name = attribute.split("=")[0].lower()
    assert name not in result.lower()
    assert "<path" in result


def test_strips_xlink_href() -> None:
    """The classic ``xlink:href`` script vector does not survive."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
        '<path d="M0 0" xlink:href="javascript:alert(1)"/></svg>'
    )
    result = sanitise_svg(svg)
    assert "xlink" not in result
    assert "javascript" not in result


def test_strips_values_that_reference_out_of_document() -> None:
    """An allowed attribute carrying a ``url()`` payload is dropped, not kept."""
    svg = VALID.replace('fill="none"', 'fill="url(#leak)"')
    assert "url(" not in sanitise_svg(svg)


def test_rejects_dtd() -> None:
    """A DTD is refused outright, closing entity expansion and external reads."""
    svg = '<!DOCTYPE svg [<!ENTITY a "b">]>' + VALID
    with pytest.raises(SvgRejectedError, match="DTD or entities"):
        sanitise_svg(svg)


def test_rejects_billion_laughs() -> None:
    """The classic expansion bomb never reaches the parser."""
    bomb = (
        '<!DOCTYPE svg [<!ENTITY a "xxxxxxxxxx">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
        '<path d="&b;"/></svg>'
    )
    with pytest.raises(SvgRejectedError):
        sanitise_svg(bomb)


def test_rejects_non_svg_root() -> None:
    """Markup that is not an SVG document is refused."""
    with pytest.raises(SvgRejectedError, match="expected <svg>"):
        sanitise_svg("<html><body>hello</body></html>")


def test_rejects_malformed_xml() -> None:
    """Unparseable markup is refused with a useful message."""
    with pytest.raises(SvgRejectedError, match="well-formed"):
        sanitise_svg('<svg viewBox="0 0 1 1"')


def test_rejects_missing_viewbox() -> None:
    """Without a viewBox the drawing cannot be scaled into its plate."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
    with pytest.raises(SvgRejectedError, match="viewBox"):
        sanitise_svg(svg)


def test_rejects_drawing_with_nothing_drawable() -> None:
    """A document whose only content was stripped is not a drawing.

    The root ``<svg>`` element must not count towards this, or an SVG containing only a
    ``<script>`` would pass as a valid but empty drawing.
    """
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script/></svg>'
    with pytest.raises(SvgRejectedError, match="no drawable content"):
        sanitise_svg(svg)


def test_rejects_oversized_input() -> None:
    """An absurdly large drawing is refused before parsing."""
    svg = VALID.replace("</svg>", "<desc>" + ("x" * 5_000_000) + "</desc></svg>")
    with pytest.raises(SvgRejectedError, match="bytes"):
        sanitise_svg(svg)


def test_rejects_too_many_elements() -> None:
    """A drawing with an unreasonable element count is refused."""
    body = '<path d="M0 0"/>' * 20_001
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">{body}</svg>'
    with pytest.raises(SvgRejectedError, match="elements"):
        sanitise_svg(svg)


def test_output_is_stable_under_repeat_sanitising() -> None:
    """Sanitising an already-sanitised drawing changes nothing further."""
    once = sanitise_svg(VALID)
    assert sanitise_svg(once) == once
