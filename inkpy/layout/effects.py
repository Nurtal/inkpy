"""Effects resolved into line segments.

The engine draws nothing, and speed lines are the exception that proves the
rule: their entire content is a direction and a count. There is no artwork to
supply, so producing them is arithmetic rather than illustration.

Everything is settled here, in the layout, so that a backend only ever receives
endpoints. Adding an effect is then a change to this file and not to every
renderer that might exist later.
"""

from __future__ import annotations

from inkpy.geometry import Rect, Vec2
from inkpy.layout.scene import Strokes
from inkpy.model.enums import EffectKind
from inkpy.model.script import Effect, Panel

STROKE_WIDTH = 0.0035
"""Line width, as a fraction of the panel's shorter side."""

TAPER = 0.55
"""How much shorter the outermost line is than the middle one.

Ruled lines of identical length read as a barcode. Real ones are longest where
the movement is and peter out at the edges of the sweep, and that single taper
is most of what makes them look drawn.
"""


def place_effects(panel: Panel, rect: Rect) -> tuple[Strokes, ...]:
    """Resolve a panel's effects, sorted among themselves by depth."""
    resolved = [
        _speed_lines(effect, rect, order)
        for order, effect in enumerate(panel.effects)
        if effect.type is EffectKind.SPEED_LINES
    ]
    resolved.sort(key=lambda strokes: (strokes.z, strokes.order))
    return tuple(resolved)


def _speed_lines(effect: Effect, rect: Rect, order: int) -> Strokes:
    """A bundle of parallel lines trailing behind a point of motion.

    ``at`` is where the movement is heading and the lines run back from it,
    which is the convention: they are the record of where the thing has been.
    """
    centre = rect.from_local(Vec2(*effect.at))
    dx, dy = effect.direction.vector

    # Length along the axis of travel, spread across it. Measuring each against
    # the panel dimension it actually runs along keeps an effect looking the
    # same in a wide panel and a tall one.
    horizontal = dx != 0.0
    length = effect.length * (rect.width if horizontal else rect.height)
    spread = effect.spread * (rect.height if horizontal else rect.width)
    across = Vec2(-dy, dx)

    lines: list[tuple[Vec2, Vec2]] = []
    for index in range(effect.count):
        offset = 0.0 if effect.count == 1 else (index / (effect.count - 1) - 0.5)
        reach = length * (1.0 - TAPER * abs(2 * offset))
        base = Vec2(
            centre.x + across.x * offset * spread,
            centre.y + across.y * offset * spread,
        )
        tail = Vec2(base.x - dx * reach, base.y - dy * reach)
        lines.append((tail, base))

    return Strokes(
        kind=effect.type,
        lines=tuple(lines),
        width=STROKE_WIDTH * min(rect.width, rect.height),
        z=effect.z,
        order=order,
    )


def effect_bounds(strokes: Strokes) -> Rect:
    """The box a bundle of lines occupies. Debug output and tests."""
    xs = [point.x for line in strokes.lines for point in line]
    ys = [point.y for line in strokes.lines for point in line]
    if not xs:
        return Rect(0.0, 0.0, 0.0, 0.0)
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
