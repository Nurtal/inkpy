"""The debug overlay.

Indispensable from day one, and cheap because the layout engine already put
everything it decided into the IR. This module invents nothing: it draws the
marks a panel is carrying. If the wireframe and the render disagree, they were
never computed twice — the disagreement is in how one of them was drawn.

Colour code:

    magenta   panel frame
    cyan      the band reserved for bubbles, before anything was placed
    orange    an actor's bounding box, and the face box bubbles must avoid
    green     anchors: feet, head, mouth
    blue      bubble boxes, and where each tail points
"""

from __future__ import annotations

from xml.sax.saxutils import quoteattr

from inkpy.geometry import Rect, Vec2
from inkpy.layout.scene import Mark, PanelScene, Scene

COLOURS = {
    "panel": "#ff00aa",
    "band": "#00b7c2",
    "actor": "#ff8a00",
    "head": "#ff8a00",
    "object": "#8a5cff",
    "mouth": "#00a844",
    "feet": "#00a844",
    "bubble": "#2b6cff",
    "tail": "#2b6cff",
}

DASHED = {"panel", "band", "actor", "head", "object", "bubble"}
POINTS = {"mouth", "feet", "tail", "head"}


def wireframe_overlay(panel: PanelScene, scene: Scene) -> str:
    """An SVG fragment drawing one panel's debug marks."""
    unit = min(scene.width, scene.height) / 500.0
    parts = ['<g class="wireframe" fill="none">']
    for mark in panel.marks:
        parts.append(_mark(mark, unit, scene))
    parts.append("</g>")
    return "".join(parts)


def _mark(mark: Mark, unit: float, scene: Scene) -> str:
    colour = COLOURS.get(mark.kind, "#888888")
    parts: list[str] = []

    if mark.rect is not None and mark.rect.area > 0:
        parts.append(
            _rect(
                mark.rect,
                stroke=colour,
                width=unit,
                dash=f"{_n(unit * 4)},{_n(unit * 3)}" if mark.kind in DASHED else None,
            )
        )
    if mark.at is not None and mark.kind in POINTS:
        parts.append(_crosshair(mark.at, colour, unit))
    if mark.kind in ("actor", "object", "bubble", "band"):
        anchor = mark.rect
        if anchor is not None:
            # Inside the box, hanging from its top edge. Above it, a label on
            # the panel's own frame would sit outside the panel entirely.
            parts.append(
                _label(
                    f"{mark.kind}:{mark.label}",
                    anchor.left,
                    anchor.top - unit * 11,
                    colour,
                    unit,
                    scene,
                )
            )
    return "".join(parts)


def _crosshair(point: Vec2, colour: str, unit: float) -> str:
    arm = unit * 4
    return (
        f'<path d="M{_n(point.x - arm)},{_n(point.y)}L{_n(point.x + arm)},{_n(point.y)}'
        f'M{_n(point.x)},{_n(point.y - arm)}L{_n(point.x)},{_n(point.y + arm)}" '
        f"stroke={quoteattr(colour)} stroke-width=\"{_n(unit)}\"/>"
        f'<circle cx="{_n(point.x)}" cy="{_n(point.y)}" r="{_n(unit * 1.5)}" '
        f"fill={quoteattr(colour)}/>"
    )


def _label(
    text: str, x: float, y: float, colour: str, unit: float, scene: Scene
) -> str:
    """Labels go through the same outline path as dialogue.

    Reusing the text engine means a wireframe never needs a system font, and
    so keeps working in the same places the real render does.
    """
    face = scene.style.typeface()
    size = unit * 9
    data = face.text_path(text, size, x + unit * 2, y + unit * 3)
    if not data:
        return ""
    return f'<path d="{data}" fill={quoteattr(colour)} opacity="0.85"/>'


def _rect(rect: Rect, stroke: str, width: float, dash: str | None) -> str:
    attrs = [
        f'x="{_n(rect.x)}"',
        f'y="{_n(rect.y)}"',
        f'width="{_n(rect.width)}"',
        f'height="{_n(rect.height)}"',
        'fill="none"',
        f"stroke={quoteattr(stroke)}",
        f'stroke-width="{_n(width)}"',
    ]
    if dash:
        attrs.append(f"stroke-dasharray={quoteattr(dash)}")
    return f"<rect {' '.join(attrs)}/>"


def _n(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text
