"""Bubble layout: the piece that decides whether a strip reads well.

The pipeline, for one panel:

1. **Measure.** Every line is measured with the font that will actually draw
   it. Nothing is estimated, because a bubble sized from an estimate is a
   bubble that clips its own text on someone else's machine.
2. **Break.** Greedy wrapping to a target width, honouring explicit newlines.
   Oval breaking — short lines top and bottom, long ones in the middle — is
   what makes a bubble stop looking machine-made, and lands in v0.2.
3. **Size.** The text block is wrapped in the smallest ellipse that contains
   it, plus padding.
4. **Place.** Bubbles are packed into the reserved band in reading order:
   greedily into rows, then each row is solved horizontally so every bubble
   sits as close as it can to its own speaker without ever swapping places
   with a neighbour.
5. **Point.** A tail leaves the ellipse on the bearing of the speaker's mouth
   and curves to it.

Collision resolution against faces and panel edges, and dropping a font size to
make room, are v0.2. What exists here refuses to hide a problem: when the
dialogue does not fit the space reserved for it, the panel says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from inkpy.geometry import Rect, Vec2
from inkpy.layout.actors import Placement
from inkpy.layout.scene import Bubble, Mark, Tail, TextLine
from inkpy.model.enums import BubbleType
from inkpy.model.script import Dialogue, Panel
from inkpy.styles.theme import PanelStyle
from inkpy.styles.typeface import Typeface

SOLVE_PASSES = 3
"""Left-then-right sweeps over a row. Three converges for four bubbles."""

MAX_BAND = 0.6
"""The largest share of a panel bubbles may claim before the panel complains.
Past this there is no picture left under the words."""

TAIL_BASE = 0.55
"""Width of a tail where it meets the bubble, as a fraction of the font size."""

TAIL_BOW = 0.14
"""How far a tail bows sideways, as a fraction of its length."""



@dataclass(frozen=True, slots=True)
class BubbleLayout:
    bubbles: tuple[Bubble, ...]
    marks: tuple[Mark, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BubblePlan:
    """Bubbles measured and grouped into rows, before they have positions.

    Its reason to exist is the composition order: the height bubbles need has
    to be known *before* characters are placed, and that height depends only
    on the text, the style, and which speaker stands where — never on how tall
    the characters ended up.
    """

    drafts: tuple[_Draft, ...]
    rows: tuple[tuple[_Draft, ...], ...]
    required_height: float


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------


def wrap_text(text: str, face: Typeface, size: float, max_width: float) -> list[str]:
    """Break a string into lines no wider than ``max_width`` pixels.

    Explicit newlines are the author's, and are always honoured. A single word
    too long for the measure is split rather than allowed to overflow: a
    clipped word is worse than an ugly break.
    """
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = f"{current} {word}" if current else word
            if current and face.width(candidate, size) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
            while face.width(current, size) > max_width and len(current) > 1:
                head, current = _split_oversized(current, face, size, max_width)
                lines.append(head)
        lines.append(current)
    return lines


def _split_oversized(
    word: str, face: Typeface, size: float, max_width: float
) -> tuple[str, str]:
    """Cut a word at the last character that still fits."""
    cut = 1
    while cut < len(word) and face.width(word[: cut + 1], size) <= max_width:
        cut += 1
    return word[:cut], word[cut:]


def shape_text(
    text: str,
    face: Typeface,
    size: float,
    max_width: float,
    line_height: float,
    padding: float,
) -> tuple[list[str], float, float]:
    """Break a string to an oval, and return the ellipse that fits it.

    Breaking and sizing are one decision, not two. Fixed-width wrapping
    produces a rectangle of text, and a rectangle of text in a round bubble is
    the clearest tell that nobody drew it — but it is also expensive, because
    the ellipse around a rectangle is √2 wider *and* √2 taller than the
    rectangle itself, and every wasted corner is paid for in panel space.

    So several shapes are tried — the fewest lines the text can occupy, and a
    couple more — each broken to the ellipse's own profile, each measured. The
    one whose bubble is smallest wins. Adding a line often shrinks the bubble,
    which is exactly the trade a fixed-width wrapper can never find.

    Returns the chosen lines and the ellipse's half-axes, padding included.
    """
    candidates = _line_candidates(text, face, size, max_width)
    best: tuple[list[str], float, float] | None = None
    for lines in candidates:
        half_width, half_height = _fit_ellipse(lines, face, size, line_height, padding)
        if best is None or half_width * half_height < best[1] * best[2]:
            best = (lines, half_width, half_height)
    assert best is not None
    return best


def wrap_oval(text: str, face: Typeface, size: float, max_width: float) -> list[str]:
    """The line breaking alone, for callers that only want the lines."""
    return _line_candidates(text, face, size, max_width)[0]


def _line_candidates(
    text: str, face: Typeface, size: float, max_width: float
) -> list[list[str]]:
    """Every plausible way to break this text, fewest lines first.

    Explicit newlines are the author's: when there are any, there is nothing
    to choose.
    """
    if "\n" in text:
        return [wrap_text(text, face, size, max_width)]

    words = text.split()
    if not words:
        return [[""]]

    floor = len(wrap_text(text, face, size, max_width))
    # A line carrying one word is a fragment, not a line: "Until / the next /
    # mug." packs into a smaller ellipse than one line does, and looks fussy
    # doing it. Two words per line on average is the floor of good manners,
    # and it never overrides what the text genuinely needs.
    ceiling = max(floor, len(words) // 2)
    candidates = [
        placed
        for count in range(floor, min(floor + 3, ceiling) + 1)
        if (placed := _fill_to_measures(words, face, size, _oval_measures(count, max_width)))
        is not None
    ]
    return candidates or [wrap_text(text, face, size, max_width)]


def _oval_measures(count: int, max_width: float) -> list[float]:
    """The width available on each of ``count`` lines stacked in an ellipse.

    Line ``i`` sits at the centre of its own horizontal band; the ellipse's
    half-chord there is ``√(1 - t²)`` for ``t`` the band's offset from the
    middle. One line gets the full measure, two get 87% each, three get
    75/100/75, and so on.
    """
    measures = []
    for index in range(count):
        offset = (2 * index + 1) / count - 1
        measures.append(max_width * math.sqrt(max(0.0, 1.0 - offset * offset)))
    return measures


def _fill_to_measures(
    words: list[str], face: Typeface, size: float, measures: list[float]
) -> list[str] | None:
    """Break words across lines of the given widths, as evenly as possible.

    Greedy filling would work and would look wrong: it packs every line to its
    limit and dumps the remainder on the last one, which is how you get an
    oval with a two-word line hanging off the bottom. Each line is instead
    scored by how much of its own measure it wastes, squared, and the split
    minimising the total is chosen — the same idea as a paragraph breaker,
    over a handful of words and at most six lines.

    ``None`` when the words cannot fit these measures at all, which is the
    caller's signal to try one more line.
    """
    count = len(measures)
    total = len(words)
    if total < count:
        return None

    widths = [face.width(word, size) for word in words]
    space = face.width(" ", size)

    def run_width(start: int, stop: int) -> float:
        return sum(widths[start:stop]) + space * (stop - start - 1)

    # cost[k][i]: best total badness for words[i:] laid out on lines k..count-1.
    cost = [[math.inf] * (total + 1) for _ in range(count + 1)]
    split = [[0] * (total + 1) for _ in range(count + 1)]
    cost[count][total] = 0.0

    for line in range(count - 1, -1, -1):
        measure = measures[line]
        for start in range(total):
            for stop in range(start + 1, total + 1):
                width = run_width(start, stop)
                if width > measure:
                    break
                rest = cost[line + 1][stop]
                if rest == math.inf:
                    continue
                slack = measure - width
                if slack * slack + rest < cost[line][start]:
                    cost[line][start] = slack * slack + rest
                    split[line][start] = stop

    if cost[0][0] == math.inf:
        return None

    lines: list[str] = []
    start = 0
    for line in range(count):
        stop = split[line][start]
        lines.append(" ".join(words[start:stop]))
        start = stop
    return lines


def _fit_ellipse(
    lines: list[str],
    face: Typeface,
    size: float,
    line_height: float,
    padding: float,
) -> tuple[float, float]:
    """Half-axes of the smallest ellipse containing a set of stacked lines.

    Not the ellipse around their bounding box — the ellipse around the lines
    themselves. For oval-broken text the two differ substantially, and that
    difference is exactly what the breaking was for.

    The shape has one free parameter: how tall to make it relative to the text.
    Taller lets the sides come in, wider lets it get shorter, and the minimum
    area sits somewhere between. It is found by trying a fixed ladder of
    ratios rather than solving analytically — a closed form exists, but a
    deterministic sweep of eighty candidates is exact enough at these sizes
    and impossible to get subtly wrong.
    """
    count = len(lines)
    half_text = count * line_height / 2
    widths = [face.width(line, size) / 2 for line in lines]

    best: tuple[float, float] | None = None
    for step in range(1, 81):
        half_height = half_text * (1.0 + step * 0.025)
        half_width = 0.0
        for index, half_line in enumerate(widths):
            # The outer corner of this line's box, measured from the centre.
            corner_y = abs((index - (count - 1) / 2) * line_height) + line_height / 2
            slack = 1.0 - (corner_y / half_height) ** 2
            if slack <= 0.0:
                half_width = math.inf
                break
            half_width = max(half_width, half_line / math.sqrt(slack))
        if best is None or half_width * half_height < best[0] * best[1]:
            best = (half_width, half_height)

    assert best is not None and math.isfinite(best[0])
    return best[0] + padding, best[1] + padding


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _Draft:
    """A measured, not yet placed, bubble."""

    line: Dialogue
    order: int
    lines: list[str]
    width: float
    height: float
    desired_x: float
    """Where its centre would ideally sit: above its speaker."""

    font_size: float = 0.0
    narrowing: float = 1.0
    """How much of its allowed width this bubble has given up, after a
    collision it could not shift its way out of."""

    escalation: int = 0
    """How many resolution strategies have been spent on this bubble."""

    x: float = 0.0
    top: float = 0.0

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.top - self.height, self.width, self.height)


def plan_bubbles(
    panel: Panel,
    rect: Rect,
    placement: Placement,
    style: PanelStyle,
) -> BubblePlan:
    """Measure a panel's dialogue and group it into rows.

    Called before characters are placed, to find out how much height the
    bubbles are going to need.
    """
    drafts = [
        _measure(line, order, rect, placement, style)
        for order, line in enumerate(panel.dialogue)
    ]
    rows = _pack_into_rows(drafts, rect.width, style.bubble_gap)
    heights = [max(draft.height for draft in row) for row in rows]
    required = sum(heights) + style.bubble_gap * (len(rows) - 1) if rows else 0.0
    return BubblePlan(
        drafts=tuple(drafts),
        rows=tuple(tuple(row) for row in rows),
        required_height=required,
    )


def band_for(plan: BubblePlan, rect: Rect, style: PanelStyle) -> Rect:
    """The band to reserve: the style's share, or more if the text needs it.

    The style's ``bubble_band`` is a floor, not a ceiling. Holding it as a hard
    limit would only mean bubbles quietly spilling over the artwork instead.
    """
    height = max(style.band_height, plan.required_height)
    return Rect(rect.x, rect.top - height, rect.width, height)


def layout_bubbles(
    panel: Panel,
    rect: Rect,
    placement: Placement,
    style: PanelStyle,
    band: Rect | None = None,
) -> BubbleLayout:
    """Lay out every bubble of a panel inside the band reserved for them."""
    if not panel.dialogue:
        return BubbleLayout(bubbles=(), marks=(), warnings=())

    plan = plan_bubbles(panel, rect, placement, style)
    warnings: list[str] = []
    drafts = list(plan.drafts)
    state = _Arrangement(
        rows=[list(row) for row in plan.rows],
        band=band_for(plan, rect, style) if band is None else band,
    )

    _arrange(state, rect, style)
    warnings.extend(_resolve_collisions(panel, rect, placement, style, state))

    if plan.required_height > MAX_BAND * rect.height:
        warnings.append(
            f"panel {panel.id}: the dialogue needs "
            f"{plan.required_height / rect.height:.0%} of the panel's height, "
            f"leaving almost no picture under it. Shorten the lines or split "
            f"them across panels."
        )
    warnings.extend(_reading_order_warnings(panel, drafts))

    bubbles = tuple(_finish(draft, placement, style) for draft in drafts)
    marks = tuple(
        Mark(kind="bubble", label=_label(bubble), rect=bubble.rect) for bubble in bubbles
    ) + tuple(
        Mark(kind="tail", label=_label(bubble), at=bubble.tail.tip)
        for bubble in bubbles
        if bubble.tail is not None
    )
    return BubbleLayout(bubbles=bubbles, marks=marks, warnings=tuple(warnings))


def _measure(
    line: Dialogue,
    order: int,
    rect: Rect,
    placement: Placement,
    style: PanelStyle,
    narrowing: float = 1.0,
    font_size: float | None = None,
) -> _Draft:
    style = style if font_size is None else style.at_font_size(font_size)
    face = style.typeface
    # Work back from the bubble's outer limit to the width the text may use:
    # the ellipse and its padding take their cut first. The √2 is the starting
    # guess, not the answer — oval breaking usually beats it, so the fitted
    # ellipse is measured and the guess narrowed until the bubble really fits.
    floor_width = face.width("mm", style.font_size)
    allowed = style.max_bubble_width * narrowing
    text_limit = max(floor_width, allowed - 2 * style.padding)
    for _ in range(5):
        lines, half_width, half_height = shape_text(
            line.text,
            face,
            style.font_size,
            text_limit,
            style.line_height,
            style.padding,
        )
        if 2 * half_width <= allowed or text_limit <= floor_width:
            break
        text_limit = max(floor_width, text_limit * 0.85)

    if line.type is BubbleType.THOUGHT:
        # A cloud's valleys are what has to clear the text. Inflate so the
        # renderer's peaks land exactly on the rectangle the IR reports.
        bloom = 1.0 - style.style.thought_bloom
        half_width /= bloom
        half_height /= bloom

    speaker = placement.actor(line.speaker) if line.speaker else None
    if speaker is not None:
        desired = speaker.mouth.x
    elif line.type is BubbleType.NARRATION:
        # A caption belongs in a corner, not floating in the middle of the sky.
        # Asking for the left edge is enough: the row solver clamps it there,
        # and the row stacker has already put it at the top when it comes
        # first, which is where captions almost always come.
        desired = rect.left + half_width
    else:
        desired = rect.center.x

    return _Draft(
        line=line,
        order=order,
        lines=lines,
        width=2 * half_width,
        height=2 * half_height,
        desired_x=desired,
        font_size=style.font_size,
        narrowing=narrowing,
    )


def _pack_into_rows(
    drafts: list[_Draft], available: float, gap: float
) -> list[list[_Draft]]:
    """Greedily fill rows, in reading order. Order is never rearranged.

    A row is also broken when the next speaker stands to the *left* of the
    previous one. Side by side, those two bubbles would have to be read
    left-to-right while their tails ran the other way and crossed — the classic
    unreadable panel. Stacked instead, each bubble sits above its own speaker
    and reading order becomes top-to-bottom, which is unambiguous.
    """
    rows: list[list[_Draft]] = []
    current: list[_Draft] = []
    used = 0.0
    for draft in drafts:
        needed = draft.width if not current else used + gap + draft.width
        crosses = bool(current) and draft.desired_x < current[-1].desired_x
        if current and (needed > available or crosses):
            rows.append(current)
            current = [draft]
            used = draft.width
        else:
            current.append(draft)
            used = needed
    if current:
        rows.append(current)
    return rows


def _stack_rows(
    rows: list[list[_Draft]], band: Rect, gap: float, lift: float = 0.0
) -> float:
    """Stack rows against the *bottom* of the band. Returns the height used.

    Reading order still runs top to bottom; what changes is that the block as
    a whole sits as low as the reservation allows, right above the heads.
    Hanging it from the top instead would leave a strip of empty sky and drag
    every tail across the panel to reach its speaker.

    ``lift`` pushes the whole block back up, which collision resolution spends
    to get a bubble off a face.
    """
    heights = [max(draft.height for draft in row) for row in rows]
    used = sum(heights) + gap * (len(rows) - 1) if rows else 0.0

    top = min(band.top, band.bottom + used + max(0.0, lift))
    for row, height in zip(rows, heights):
        for draft in row:
            draft.top = top
        top -= height + gap
    return used


def _solve_row(row: list[_Draft], left: float, right: float, gap: float) -> None:
    """Place a row's bubbles near their speakers, in order, without overlap.

    Alternating sweeps: push right off the previous neighbour, then push left
    off the next one, then clamp to the panel. Order is preserved by
    construction, so a bubble can never end up before the one that should be
    read first.
    """
    for draft in row:
        draft.x = draft.desired_x - draft.width / 2

    for _ in range(SOLVE_PASSES):
        edge = left
        for draft in row:
            draft.x = max(draft.x, edge)
            edge = draft.x + draft.width + gap

        edge = right
        for draft in reversed(row):
            draft.x = min(draft.x, edge - draft.width)
            edge = draft.x - gap

    # A row wider than the band cannot satisfy both clamps; keeping the left
    # edge honest at least preserves reading order.
    edge = left
    for draft in row:
        draft.x = max(draft.x, edge)
        edge = draft.x + draft.width + gap


@dataclass(slots=True)
class _Arrangement:
    """The mutable state of a panel's bubbles while collisions are resolved."""

    rows: list[list[_Draft]]
    band: Rect
    lift: float = 0.0
    """How far the whole block has been pushed up inside the band.

    Panel-level rather than per-bubble: rows are stacked against the bottom of
    the band to keep tails short, and lifting one bubble out of a row would
    only put it on top of its neighbour.
    """

    def content_height(self, gap: float) -> float:
        if not self.rows:
            return 0.0
        return sum(max(d.height for d in row) for row in self.rows) + gap * (
            len(self.rows) - 1
        )

    def slack(self, gap: float) -> float:
        """Room the band has beyond what the bubbles occupy."""
        return self.band.height - self.content_height(gap)


def _arrange(state: _Arrangement, rect: Rect, style: PanelStyle) -> None:
    """Re-derive the band, stack the rows and settle each one horizontally."""
    state.band = _reserve(state.rows, rect, style)
    _stack_rows(state.rows, state.band, style.bubble_gap, lift=state.lift)
    for row in state.rows:
        _solve_row(row, state.band.left, state.band.right, style.bubble_gap)


def _resolve_collisions(
    panel: Panel,
    rect: Rect,
    placement: Placement,
    style: PanelStyle,
    state: _Arrangement,
) -> list[str]:
    """Get bubbles off the faces they are covering.

    Characters have already yielded what they could: they were placed against
    the space the bubbles claimed, and shrank to clear it. What is left here is
    the residue — a character that hit its minimum size and still reaches up,
    or a bubble that drifted while the mouths moved under it.

    Strategies, in the order the README sets out, cheapest first:

    1. **shift horizontally** — free, and usually enough;
    2. **narrow the bubble**, making it taller — costs vertical room;
    3. **move up** into whatever slack the band has left;
    4. **drop the font one step** — last, because it breaks the page's voice,
       and never below the style's floor.

    Each attempt re-settles the whole panel, since moving one bubble moves its
    neighbours. Escalation is bounded: four strategies per bubble, and a bubble
    that exhausts them says so rather than being quietly left on a face.
    """
    warnings: list[str] = []
    obstacles = tuple(
        actor.head_box for actor in placement.actors if actor.head_box.area > 0
    )
    if not obstacles:
        return warnings

    for _ in range(4 * sum(len(row) for row in state.rows) + 1):
        offender = _first_collision(state.rows, obstacles)
        if offender is None:
            break
        row, draft = offender
        if _escalate(draft, row, state, rect, placement, style, obstacles):
            _arrange(state, rect, style)
            continue
        warnings.append(
            f"panel {panel.id}: the bubble for "
            f"{draft.line.speaker or 'the caption'} covers a face and cannot "
            f"be moved clear. Move the characters apart, shorten the line, or "
            f"give the panel more room."
        )
        # Say it once. Retiring the bubble from the search stops the loop
        # rediscovering the same unsolvable overlap on every pass.
        draft.escalation = RETIRED

    return warnings


RETIRED = 99
"""Escalation value for a bubble that has been reported and left alone."""


def _first_collision(
    rows: list[list[_Draft]], obstacles: tuple[Rect, ...]
) -> tuple[list[_Draft], _Draft] | None:
    for row in rows:
        for draft in row:
            if draft.escalation > 4:
                continue
            if any(draft.rect.intersects(obstacle) for obstacle in obstacles):
                return row, draft
    return None


def _reserve(rows: list[list[_Draft]], rect: Rect, style: PanelStyle) -> Rect:
    """The band the current drafts need. Recomputed as they change shape."""
    heights = [max(draft.height for draft in row) for row in rows]
    required = sum(heights) + style.bubble_gap * (len(rows) - 1) if rows else 0.0
    height = max(style.band_height, required)
    return Rect(rect.x, rect.top - height, rect.width, height)


def _escalate(
    draft: _Draft,
    row: list[_Draft],
    state: _Arrangement,
    rect: Rect,
    placement: Placement,
    style: PanelStyle,
    obstacles: tuple[Rect, ...],
) -> bool:
    """Apply this bubble's next strategy. ``False`` when they are spent."""
    draft.escalation += 1

    if draft.escalation == 1:
        return _try_shift(draft, row, state.band, style, obstacles)

    if draft.escalation == 2:
        return _remeasure(draft, rect, placement, style, narrowing=NARROWED)

    if draft.escalation == 3:
        # Lift the whole block, using whatever room the band's floor left over.
        # Tails get longer, which is the price of not covering a face.
        slack = state.slack(style.bubble_gap) - state.lift
        if slack <= style.bubble_gap:
            return False
        state.lift += slack
        return True

    if draft.escalation == 4:
        smaller = max(style.min_font_size, draft.font_size * FONT_STEP)
        if smaller >= draft.font_size:
            return False
        return _remeasure(
            draft,
            rect,
            placement,
            style,
            narrowing=draft.narrowing,
            font_size=smaller,
        )

    return False


NARROWED = 0.72
"""How much of its measure a bubble keeps when narrowing to dodge a face."""

FONT_STEP = 0.85
"""One step down the type ladder, the last resort before giving up."""


def _try_shift(
    draft: _Draft,
    row: list[_Draft],
    band: Rect,
    style: PanelStyle,
    obstacles: tuple[Rect, ...],
) -> bool:
    """Slide sideways to the nearest clear spot, without leaving the row.

    Candidates are the positions flush against each obstacle's left and right
    edges — a bubble only ever needs to clear an obstacle, never to land
    somewhere in between — plus the band's own edges. The one nearest the
    speaker wins, so the tail stays as short as it can.
    """
    index = row.index(draft)
    left_limit = band.left
    if index > 0:
        left_limit = row[index - 1].rect.right + style.bubble_gap
    right_limit = band.right
    if index + 1 < len(row):
        right_limit = row[index + 1].rect.left - style.bubble_gap

    candidates = [band.left, right_limit - draft.width]
    for obstacle in obstacles:
        candidates.append(obstacle.left - draft.width)
        candidates.append(obstacle.right)

    original = draft.x
    best: float | None = None
    for candidate in sorted(candidates):
        if candidate < left_limit or candidate + draft.width > right_limit:
            continue
        trial = Rect(candidate, draft.top - draft.height, draft.width, draft.height)
        if any(trial.intersects(obstacle) for obstacle in obstacles):
            continue
        distance = abs(candidate + draft.width / 2 - draft.desired_x)
        if best is None or distance < abs(best + draft.width / 2 - draft.desired_x):
            best = candidate

    if best is None:
        draft.x = original
        return False
    draft.x = best
    draft.desired_x = best + draft.width / 2
    return True


def _remeasure(
    draft: _Draft,
    rect: Rect,
    placement: Placement,
    style: PanelStyle,
    narrowing: float,
    font_size: float | None = None,
) -> bool:
    """Re-shape a bubble at a tighter measure, keeping where it wants to be."""
    fresh = _measure(
        draft.line,
        draft.order,
        rect,
        placement,
        style,
        narrowing=narrowing,
        font_size=font_size,
    )
    if fresh.width >= draft.width:
        return False
    draft.lines = fresh.lines
    draft.width = fresh.width
    draft.height = fresh.height
    draft.font_size = fresh.font_size
    draft.narrowing = narrowing
    return True


def _reading_order_warnings(panel: Panel, drafts: list[_Draft]) -> list[str]:
    """Check that visual order still matches array order.

    Packing preserves it by construction; this catches the case the README
    warns about, where the requested positions make it geometrically
    impossible, rather than trusting the invariant silently.
    """
    warnings: list[str] = []
    for previous, current in zip(drafts, drafts[1:]):
        same_row = previous.top == current.top
        if same_row and current.x < previous.x:
            warnings.append(
                f"panel {panel.id}: bubble {current.order + 1} sits left of "
                f"bubble {previous.order + 1} on the same line, so they will "
                f"be read out of order."
            )
        elif not same_row and current.top > previous.top:
            warnings.append(
                f"panel {panel.id}: bubble {current.order + 1} sits above "
                f"bubble {previous.order + 1}, so they will be read out of "
                f"order."
            )
    return warnings


def _finish(draft: _Draft, placement: Placement, style: PanelStyle) -> Bubble:
    """Turn a placed draft into the immutable IR node, text and tail included."""
    # A bubble that dropped a step to dodge a face carries its own size, and
    # everything about it — line height, padding, tail — has to follow.
    style = style if draft.font_size == style.font_size else style.at_font_size(
        draft.font_size
    )
    rect = draft.rect
    face = style.typeface
    metrics = face.measure("", style.font_size)

    block_height = len(draft.lines) * style.line_height
    top = rect.center.y + block_height / 2
    lines = tuple(
        TextLine(
            text=text,
            baseline=Vec2(
                rect.center.x - face.width(text, style.font_size) / 2,
                top - metrics.ascent - index * style.line_height,
            ),
            width=face.width(text, style.font_size),
        )
        for index, text in enumerate(draft.lines)
    )

    tail = None
    if draft.line.type.has_tail and draft.line.speaker:
        speaker = placement.actor(draft.line.speaker)
        if speaker is not None:
            tail = _tail_to(rect, speaker.mouth, style)

    return Bubble(
        kind=draft.line.type,
        rect=rect,
        lines=lines,
        font_size=style.font_size,
        speaker=draft.line.speaker,
        tail=tail,
        order=draft.order,
    )


def _tail_to(rect: Rect, mouth: Vec2, style: PanelStyle) -> Tail:
    """Aim a tail from a bubble's outline at a speaker's mouth."""
    centre = rect.center
    half_w = rect.width / 2
    half_h = rect.height / 2

    dx = mouth.x - centre.x
    dy = mouth.y - centre.y
    if dx == 0.0 and dy == 0.0:
        # The mouth is under the bubble's centre: leave straight down.
        dx, dy = 0.0, -1.0

    # Where the bearing to the mouth crosses the ellipse.
    bearing = math.atan2(dy / half_h, dx / half_w)
    root = Vec2(centre.x + half_w * math.cos(bearing), centre.y + half_h * math.sin(bearing))

    span = Vec2(mouth.x - root.x, mouth.y - root.y)
    length = math.hypot(span.x, span.y)
    if length == 0.0:
        control = root
    else:
        # Bow sideways so the tail reads as drawn rather than as a ruler line.
        normal = Vec2(-span.y / length, span.x / length)
        control = Vec2(
            root.x + span.x * 0.55 + normal.x * length * TAIL_BOW,
            root.y + span.y * 0.55 + normal.y * length * TAIL_BOW,
        )

    return Tail(
        root=root,
        tip=mouth,
        control=control,
        base_width=TAIL_BASE * style.font_size,
    )


def _label(bubble: Bubble) -> str:
    return f"{bubble.order + 1}:{bubble.speaker or bubble.kind.value}"
