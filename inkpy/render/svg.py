"""Scene to SVG.

This backend makes no decisions. Every position, every size, every line break
was settled by the layout engine; what happens here is transcription. That is
the whole point of having an intermediate representation: if a bubble is in the
wrong place, the bug is upstream, and this file is never a suspect.

Two conventions are reconciled here, and only here:

*Y direction.* The engine works bottom-left, y up. SVG works top-left, y down.
The whole document is emitted inside one flipping group, so no coordinate is
ever converted by hand. Images, which would come out upside down in a flipped
frame, carry a local counter-flip — which is also where mirroring lives, since
both are the same kind of transform.

*Self-containment.* Sprites are embedded as data URIs and text is embedded as
outlines. The resulting file depends on no font, no image path and no renderer
setting, which is what makes "same input, same output" true off this machine.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from xml.sax.saxutils import quoteattr

from inkpy import __version__
from inkpy.assets.library import Sprite
from inkpy.geometry import Rect, Vec2
from inkpy.layout.scene import Bubble, PanelScene, Scene, SpriteDraw, Strokes, Tail
from inkpy.model.enums import BubbleType

ELLIPSE_SEGMENTS = 120
"""Segments per bubble outline.

An arc command would be shorter, but its two flags read differently depending
on which way the enclosing frame points, and the frame here is flipped. A
polyline has no orientation ambiguity, cuts a gap for the tail with a slice,
and is smooth well past print resolution.
"""

TAIL_HALF_ANGLE = 0.30
"""Half-width of the tail's opening on the bubble, in radians."""


@dataclass(frozen=True, slots=True)
class SvgOptions:
    embed_assets: bool = True
    """Inline sprites as data URIs. Off, the SVG references files on disk."""

    wireframe: bool = False
    """Draw the debug overlay on top of the render."""

    artwork: bool = True
    """Draw the artwork itself. Off with ``wireframe``, gives a bare diagram."""


def render_svg(scene: Scene, options: SvgOptions | None = None) -> str:
    """Serialise a scene as a standalone SVG document."""
    options = options or SvgOptions()
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{scene.width}" height="{scene.height}" '
        f'viewBox="0 0 {scene.width} {scene.height}">',
        _metadata(scene),
        f'<rect x="0" y="0" width="{scene.width}" height="{scene.height}" '
        f"fill={quoteattr(scene.background_colour)}/>",
        # One flip for the whole document: everything below is y-up.
        f'<g transform="translate(0,{_n(scene.height)}) scale(1,-1)">',
    ]
    parts.extend(_defs(scene))
    for panel in scene.panels:
        parts.append(_panel(panel, scene, options))
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(part for part in parts if part)


# --------------------------------------------------------------------------
# Document furniture
# --------------------------------------------------------------------------


def _metadata(scene: Scene) -> str:
    """Provenance, so a render can be traced back to what produced it."""
    return (
        "<metadata>"
        f"<inkpy:render xmlns:inkpy=\"https://inkpy.dev/ns\" "
        f"version={quoteattr(__version__)} "
        f"title={quoteattr(scene.title)} "
        f"style={quoteattr(scene.style.name)} "
        f"assets={quoteattr(scene.asset_fingerprint)}/>"
        "</metadata>"
    )


def _defs(scene: Scene) -> list[str]:
    """A clip path per panel. Artwork may overflow; panels never do."""
    clips = [
        f'<clipPath id="panel-{panel.id}-clip">{_rect(panel.rect)}</clipPath>'
        for panel in scene.panels
    ]
    return ["<defs>", *clips, "</defs>"]


# --------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------


def _panel(panel: PanelScene, scene: Scene, options: SvgOptions) -> str:
    style = scene.style
    stroke = style.panel_stroke * min(scene.width, scene.height) * panel.frame_weight

    parts = [f'<g id="panel-{panel.id}">']
    if options.artwork:
        parts.append(_rect(panel.rect, fill=style.panel_fill))
        # 1 to 4: everything that can overflow, clipped to the panel.
        parts.append(f'<g clip-path="url(#panel-{panel.id}-clip)">')
        parts.extend(_draw(draw, options) for draw in panel.draws)
        parts.extend(_strokes(effect, style) for effect in panel.effects)
        parts.append("</g>")
        # 5: bubbles, deliberately outside the clip is not wanted either —
        # a bubble crossing the frame reads as an error, not as a flourish.
        parts.append(f'<g clip-path="url(#panel-{panel.id}-clip)">')
        parts.extend(_bubble(bubble, scene) for bubble in panel.bubbles)
        parts.append("</g>")

    # 6: the frame, last, so it sits over everything it contains. A panel with
    # 'frame: none' has no border at all and bleeds into the page.
    if stroke > 0:
        parts.append(
            _rect(
                panel.rect,
                fill="none",
                stroke=style.panel_stroke_colour,
                stroke_width=stroke,
            )
        )
    if options.wireframe:
        from inkpy.render.wireframe import wireframe_overlay

        parts.append(wireframe_overlay(panel, scene))
    parts.append("</g>")
    return "".join(parts)


def _draw(draw: SpriteDraw, options: SvgOptions) -> str:
    """Place one sprite, counter-flipping it out of the y-up frame."""
    rect = draw.rect
    href = _href(draw.sprite, options.embed_assets)
    if draw.flip:
        # Mirror and un-flip in one transform: the sprite's own top-left goes
        # to the rectangle's top-right.
        transform = f"translate({_n(rect.right)},{_n(rect.top)}) scale(-1,-1)"
    else:
        transform = f"translate({_n(rect.left)},{_n(rect.top)}) scale(1,-1)"
    return (
        f'<g transform="{transform}">'
        f'<image x="0" y="0" width="{_n(rect.width)}" height="{_n(rect.height)}" '
        f'xlink:href={quoteattr(href)} '
        f'preserveAspectRatio="none"/>'
        f"</g>"
    )


def _strokes(effect: Strokes, style) -> str:
    """Ruled lines, exactly as the layout engine placed them."""
    paths = "".join(
        f"M{_n(start.x)},{_n(start.y)}L{_n(end.x)},{_n(end.y)}"
        for start, end in effect.lines
    )
    return (
        f'<path class="effect {effect.kind.value}" d="{paths}" fill="none" '
        f"stroke={quoteattr(style.panel_stroke_colour)} "
        f'stroke-width="{_n(effect.width)}" stroke-linecap="round"/>'
    )


def _href(sprite: Sprite, embed: bool) -> str:
    if not embed:
        return sprite.path.as_uri()
    payload = base64.b64encode(sprite.path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


# --------------------------------------------------------------------------
# Bubbles
# --------------------------------------------------------------------------


def _bubble(bubble: Bubble, scene: Scene) -> str:
    style = scene.style
    stroke = style.bubble_stroke * min(scene.width, scene.height)

    if bubble.kind is BubbleType.NARRATION:
        outline = _rect_path(bubble.rect)
    else:
        outline = _bubble_path(bubble, style.thought_bloom)

    # Classes are for whoever opens the SVG — the outline of a bubble and the
    # outline of a letter are both just <path>, and telling them apart by
    # their curve commands is nobody's idea of a good time.
    parts: list[str] = []
    if bubble.kind is BubbleType.THOUGHT:
        # Puffs first: they run under the bubble, so the trail appears to come
        # out from behind it rather than to be glued on.
        parts.append(_thought_puffs(bubble, stroke, style))
    parts.append(
        f'<path class="bubble {bubble.kind.value}" d="{outline}" '
        f"fill={quoteattr(style.bubble_fill)} "
        f"stroke={quoteattr(style.bubble_stroke_colour)} "
        f'stroke-width="{_n(stroke)}" '
        f'stroke-linejoin="{"miter" if bubble.kind is BubbleType.SHOUT else "round"}"/>'
    )
    face = style.typeface()
    for line in bubble.lines:
        if not line.text:
            continue
        data = face.text_path(
            line.text, bubble.font_size, line.baseline.x, line.baseline.y
        )
        if data:
            parts.append(
                f'<path class="text" d="{data}" fill={quoteattr(style.text_colour)}/>'
            )
    return "".join(parts)


CLOUD_LOBES = 7
"""Scallops around a thought bubble. Odd, so no two sit opposite each other."""

SHOUT_SPIKES = 11
SHOUT_PEAK = 1.16
SHOUT_VALLEY = 0.86

THOUGHT_PUFFS = 3
"""Bubbles in the trail that replaces a thought bubble's tail."""


def _bubble_path(bubble: Bubble, bloom: float) -> str:
    """The bubble outline and its tail, as one closed path.

    One path rather than two shapes: an ellipse drawn over a separate tail
    leaves its own outline running across the tail's neck, which is precisely
    how a machine-made bubble announces itself. The same reasoning gives a
    shout its tail for free — a shout's tail *is* one of its spikes, drawn
    longer, so the outline never has to be interrupted at all.
    """
    if bubble.kind is BubbleType.SHOUT:
        return _shout_path(bubble)
    if bubble.kind is BubbleType.THOUGHT:
        return _closed_outline(bubble, _cloud_radius(bloom))
    return _speech_path(bubble)


def _polar(bubble: Bubble, angle: float, radius: float = 1.0) -> Vec2:
    """A point on the bubble's ellipse, scaled outward by ``radius``."""
    centre = bubble.rect.center
    return Vec2(
        centre.x + bubble.rect.width / 2 * radius * math.cos(angle),
        centre.y + bubble.rect.height / 2 * radius * math.sin(angle),
    )


def _cloud_radius(bloom: float):
    """A radius function whose peaks reach 1 and whose valleys sit at 1-bloom.

    Peaking at exactly 1 is what keeps the drawn cloud inside the rectangle
    the layout engine reserved for it.
    """

    def radius(angle: float) -> float:
        # |sin| rather than sin: the cusps between lobes are what make it read
        # as a cloud instead of a flower.
        return (1.0 - bloom) + bloom * abs(math.sin(CLOUD_LOBES * angle))

    return radius


def _bearing(bubble: Bubble) -> float:
    """The direction of this bubble's tail, in the ellipse's own parameter."""
    assert bubble.tail is not None
    centre = bubble.rect.center
    return math.atan2(
        (bubble.tail.root.y - centre.y) / (bubble.rect.height / 2),
        (bubble.tail.root.x - centre.x) / (bubble.rect.width / 2),
    )


def _closed_outline(bubble: Bubble, radius) -> str:
    """A full turn around the bubble, with no gap cut for a tail."""
    points = [
        _polar(bubble, angle := 2 * math.pi * index / ELLIPSE_SEGMENTS, radius(angle))
        for index in range(ELLIPSE_SEGMENTS)
    ]
    return _polyline(points) + "Z"


def _speech_path(bubble: Bubble) -> str:
    if bubble.tail is None:
        return _closed_outline(bubble, lambda _: 1.0)

    # Start just past the tail's opening and go all the way round to its other
    # lip, leaving the gap the tail fills.
    start = _bearing(bubble) + TAIL_HALF_ANGLE
    sweep = 2 * math.pi - 2 * TAIL_HALF_ANGLE
    points = [
        _polar(bubble, start + sweep * index / ELLIPSE_SEGMENTS)
        for index in range(ELLIPSE_SEGMENTS + 1)
    ]
    return _polyline(points) + _tail_path(bubble.tail, points[0]) + "Z"


def _shout_path(bubble: Bubble) -> str:
    """A ring of spikes, one of which is stretched out to the speaker.

    Comic shouts do not have a tail bolted to a round bubble; they have one
    spike longer than the rest. Building it that way means the outline is a
    single unbroken polygon, and the tail cannot be drawn out of register
    with it.
    """
    count = SHOUT_SPIKES * 2
    bearing = _bearing(bubble) if bubble.tail is not None else None

    points: list[Vec2] = []
    speaking_spike = None
    if bearing is not None:
        # The peak nearest the mouth becomes the tail. Peaks are the even
        # vertices, so round the bearing to one of those.
        step = 2 * math.pi / count
        speaking_spike = round(bearing / (2 * step)) * 2 % count

    for index in range(count):
        angle = 2 * math.pi * index / count
        if index == speaking_spike and bubble.tail is not None:
            points.append(bubble.tail.tip)
            continue
        points.append(_polar(bubble, angle, SHOUT_PEAK if index % 2 == 0 else SHOUT_VALLEY))
    return _polyline(points) + "Z"


def _thought_puffs(bubble: Bubble, stroke: float, style) -> str:
    """The shrinking trail that carries a thought back to its thinker."""
    tail = bubble.tail
    if tail is None:
        return ""
    parts = []
    for index in range(1, THOUGHT_PUFFS + 1):
        along = index / (THOUGHT_PUFFS + 1)
        # Ease outward so the puffs crowd near the bubble, as drawn ones do,
        # and the trail reads as leaving the cloud rather than floating free.
        eased = along**1.5
        centre_x = tail.root.x + (tail.tip.x - tail.root.x) * eased
        centre_y = tail.root.y + (tail.tip.y - tail.root.y) * eased
        radius = tail.base_width * (1.15 - along * 0.6)
        parts.append(
            f'<circle class="puff" cx="{_n(centre_x)}" cy="{_n(centre_y)}" '
            f'r="{_n(radius)}" fill={quoteattr(style.bubble_fill)} '
            f"stroke={quoteattr(style.bubble_stroke_colour)} "
            f'stroke-width="{_n(stroke)}"/>'
        )
    return "".join(parts)


def _polyline(points: list[Vec2]) -> str:
    commands = [f"M{_n(points[0].x)},{_n(points[0].y)}"]
    commands.extend(f"L{_n(point.x)},{_n(point.y)}" for point in points[1:])
    return "".join(commands)


def _tail_path(tail: Tail, lip_in: Vec2) -> str:
    """From the far lip of the gap, out to the tip, and back to ``lip_in``.

    The caller has already drawn the outline up to one lip; this continues from
    there. Both sides bow through the same control point, which keeps the tail
    slender near the tip and full at the base without any extra parameters.
    """
    return (
        f"Q{_n(tail.control.x)},{_n(tail.control.y)} "
        f"{_n(tail.tip.x)},{_n(tail.tip.y)} "
        f"Q{_n(tail.control.x)},{_n(tail.control.y)} "
        f"{_n(lip_in.x)},{_n(lip_in.y)}"
    )


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


def _rect(
    rect: Rect,
    fill: str = "none",
    stroke: str | None = None,
    stroke_width: float = 0.0,
    dash: str | None = None,
    opacity: float | None = None,
) -> str:
    attrs = [
        f'x="{_n(rect.x)}"',
        f'y="{_n(rect.y)}"',
        f'width="{_n(rect.width)}"',
        f'height="{_n(rect.height)}"',
        f"fill={quoteattr(fill)}",
    ]
    if stroke is not None:
        attrs.append(f"stroke={quoteattr(stroke)}")
        attrs.append(f'stroke-width="{_n(stroke_width)}"')
    if dash is not None:
        attrs.append(f"stroke-dasharray={quoteattr(dash)}")
    if opacity is not None:
        attrs.append(f'opacity="{_n(opacity)}"')
    return f"<rect {' '.join(attrs)}/>"


def _rect_path(rect: Rect) -> str:
    return (
        f"M{_n(rect.left)},{_n(rect.bottom)}"
        f"L{_n(rect.right)},{_n(rect.bottom)}"
        f"L{_n(rect.right)},{_n(rect.top)}"
        f"L{_n(rect.left)},{_n(rect.top)}Z"
    )


def _n(value: float) -> str:
    """Fixed precision. Identical geometry has to produce identical bytes."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text
