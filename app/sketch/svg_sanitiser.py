"""Reduce arbitrary SVG to an inert, drawable subset.

The redrawn SVG is written by a language model and then embedded directly into a rendered
document. Treating that markup as trusted is how a drawing becomes an incident, so it is
parsed, filtered against an allow-list, and re-serialised — never regex-patched, and never
stored in its original form.

The filter is an allow-list on purpose. A deny-list of known-bad elements is wrong the day
someone adds a new one.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

# Shapes and structure needed for technical line art. Deliberately excluded:
# `script`, `foreignObject`, `image`, `a`, `style`, `use`, and every animation element.
DRAWABLE_ELEMENTS: frozenset[str] = frozenset(
    {
        "path",
        "line",
        "polyline",
        "polygon",
        "rect",
        "circle",
        "ellipse",
        "text",
    }
)

STRUCTURAL_ELEMENTS: frozenset[str] = frozenset({"svg", "g", "defs", "title", "desc", "tspan"})

ALLOWED_ELEMENTS: frozenset[str] = DRAWABLE_ELEMENTS | STRUCTURAL_ELEMENTS

ALLOWED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # geometry
        "d",
        "points",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "width",
        "height",
        "dx",
        "dy",
        "transform",
        "viewBox",
        "preserveAspectRatio",
        # paint
        "fill",
        "stroke",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-miterlimit",
        "fill-rule",
        "clip-rule",
        "opacity",
        "fill-opacity",
        "stroke-opacity",
        "vector-effect",
        "shape-rendering",
        # text
        "font-size",
        "font-family",
        "font-weight",
        "text-anchor",
        "dominant-baseline",
        "letter-spacing",
        # identity
        "id",
        "class",
    }
)

# `style` is absent from the allow-list above on purpose: a style attribute can carry
# `url(...)` and `expression(...)` payloads, and sanitising CSS is a second parser's job.

_DANGEROUS_VALUE = re.compile(r"(?:javascript:|data:text/html|url\s*\(|expression\s*\()", re.I)
_DOCTYPE_OR_ENTITY = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.I)
_MAX_BYTES = 4 * 1024 * 1024
_MAX_ELEMENTS = 20_000


class SvgRejectedError(ValueError):
    """The supplied markup is not usable as a drawing."""


def _local_name(tag: str) -> str:
    """Strip any XML namespace from a tag or attribute name.

    Args:
        tag: A possibly namespaced name, e.g. ``{http://...}path``.

    Returns:
        str: The local part.
    """
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _is_allowed_attribute(name: str) -> bool:
    """Decide whether one attribute survives filtering.

    Args:
        name: The attribute name, possibly namespaced.

    Returns:
        bool: True when the attribute is on the allow-list and carries no reference.
    """
    if name.startswith(f"{{{XLINK_NS}}}"):
        # Every xlink attribute is a reference out of the document. None are needed for
        # line art, and `xlink:href` is the classic SVG script vector.
        return False
    local = _local_name(name)
    if local.lower().startswith("on"):
        return False
    if local in {"href", "xlink:href", "style"}:
        return False
    return local in ALLOWED_ATTRIBUTES


def _filter(element: ET.Element, budget: list[int]) -> ET.Element | None:
    """Recursively rebuild an element, dropping anything not allowed.

    Args:
        element: The parsed element to filter.
        budget: Single-item list used as a mutable element counter.

    Returns:
        ET.Element | None: A cleaned copy, or ``None`` if the element is not allowed.

    Raises:
        SvgRejectedError: If the document exceeds the element budget.
    """
    budget[0] += 1
    if budget[0] > _MAX_ELEMENTS:
        raise SvgRejectedError(f"drawing exceeds {_MAX_ELEMENTS} elements")

    local = _local_name(element.tag)
    if local not in ALLOWED_ELEMENTS:
        return None

    cleaned = ET.Element(f"{{{SVG_NS}}}{local}")
    for name, value in element.attrib.items():
        if not _is_allowed_attribute(name):
            continue
        if _DANGEROUS_VALUE.search(value):
            continue
        cleaned.set(_local_name(name), value)

    cleaned.text = element.text
    cleaned.tail = element.tail
    for child in element:
        kept = _filter(child, budget)
        if kept is not None:
            cleaned.append(kept)
    return cleaned


def sanitise_svg(raw: str) -> str:
    """Parse, filter, and re-serialise an SVG drawing.

    Args:
        raw: The markup as produced by the model.

    Returns:
        str: Inert SVG containing only allow-listed elements and attributes.

    Raises:
        SvgRejectedError: If the input is too large, is not well-formed XML, declares a
            DTD or entities, has a root element other than ``<svg>``, lacks a ``viewBox``,
            or contains no drawable content once filtered.
    """
    if len(raw.encode("utf-8")) > _MAX_BYTES:
        raise SvgRejectedError(f"drawing exceeds {_MAX_BYTES} bytes")

    # Refuse DTDs outright rather than trusting the parser's entity handling. This closes
    # both external-entity reads and the billion-laughs expansion in one check, and no
    # legitimate line drawing needs a DTD.
    if _DOCTYPE_OR_ENTITY.search(raw):
        raise SvgRejectedError("drawing declares a DTD or entities")

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SvgRejectedError(f"drawing is not well-formed XML: {exc}") from exc

    if _local_name(root.tag) != "svg":
        raise SvgRejectedError(f"root element is <{_local_name(root.tag)}>, expected <svg>")

    cleaned = _filter(root, [0])
    if cleaned is None:  # pragma: no cover - unreachable: root tag is checked above
        raise SvgRejectedError("drawing was removed entirely by filtering")

    if "viewBox" not in cleaned.attrib:
        # Without a viewBox the drawing cannot be scaled into a plate box; it would print
        # at whatever intrinsic size it declares and silently overflow the frame.
        raise SvgRejectedError("drawing has no viewBox")

    # Check for a *drawable* element specifically. Asking "is anything left?" would be
    # satisfied by the root <svg> itself, so a document whose only child was a <script>
    # would survive filtering as an empty but valid drawing.
    if not any(_local_name(e.tag) in DRAWABLE_ELEMENTS for e in cleaned.iter()):
        raise SvgRejectedError("drawing contains no drawable content")

    ET.register_namespace("", SVG_NS)
    return ET.tostring(cleaned, encoding="unicode")
