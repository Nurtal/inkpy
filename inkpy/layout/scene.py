"""The intermediate representation.

A ``Scene`` is what the layout engine produces and what every backend consumes:
resolved geometry in absolute pixels, with nothing left to decide. No asset is
looked up here, no text is measured here, no font is chosen here — all of that
happened upstream.

This is the layer the test suite asserts against. "No bubble covers a face" is
a question about rectangles, answerable in microseconds; asked of a PNG it
becomes an unmaintainable pixel diff.

Convention, as everywhere upstream of the backends: origin bottom-left, y up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from inkpy.assets.library import Sprite
from inkpy.geometry import Rect, Vec2
from inkpy.model.enums import BubbleType, EffectKind
from inkpy.styles.theme import Style


class DrawKind(str, Enum):
    """What a sprite is, for z-ordering ties and for debug output."""

    BACKGROUND = "background"
    BODY = "body"
    FACE = "face"
    OBJECT = "object"


@dataclass(frozen=True, slots=True)
class SpriteDraw:
    """One sprite, placed and sized. Backends only translate and scale it."""

    sprite: Sprite
    rect: Rect
    kind: DrawKind
    label: str
    """Human-readable origin, e.g. ``cat/sitting``. Debug output only."""

    z: int = 0
    flip: bool = False
    order: int = 0
    """Position in the strip file. Breaks z ties so sorting stays stable."""

    @property
    def sort_key(self) -> tuple[int, int]:
        return (self.z, self.order)


@dataclass(frozen=True, slots=True)
class TextLine:
    """One line of dialogue, already broken and already positioned.

    ``baseline`` is where the run starts; ``width`` is what it measured. The
    backend converts this to outlines without making a single decision.
    """

    text: str
    baseline: Vec2
    width: float


@dataclass(frozen=True, slots=True)
class Tail:
    """A bubble's pointer, as a quadratic Bézier with a base of some width."""

    root: Vec2
    """Midpoint of the tail's base, on the bubble outline."""

    tip: Vec2
    """Where it points: the speaker's mouth."""

    control: Vec2
    base_width: float


@dataclass(frozen=True, slots=True)
class Bubble:
    """A placed bubble: its box, its lines, and where it points."""

    kind: BubbleType
    rect: Rect
    lines: tuple[TextLine, ...]
    font_size: float
    speaker: str | None = None
    tail: Tail | None = None
    order: int = 0
    """Index in the panel's dialogue array, i.e. reading order."""


@dataclass(frozen=True, slots=True)
class Strokes:
    """A bundle of ruled lines: an effect, already resolved to endpoints.

    The backend draws these and nothing more. Whatever an effect means — speed,
    impact, attention — was turned into line segments upstream, which keeps
    "add an effect" a layout change rather than a rendering one.
    """

    kind: EffectKind
    lines: tuple[tuple[Vec2, Vec2], ...]
    width: float
    z: int = 0
    order: int = 0


@dataclass(frozen=True, slots=True)
class Mark:
    """A debug annotation. Carried in the IR so ``--wireframe`` is a pure
    backend, with no second layout pass that could disagree with the first."""

    kind: str
    label: str
    at: Vec2 | None = None
    rect: Rect | None = None


@dataclass(frozen=True, slots=True)
class PanelScene:
    """One panel, fully resolved."""

    id: int
    rect: Rect
    draws: tuple[SpriteDraw, ...] = ()
    """Already sorted back to front."""

    effects: tuple[Strokes, ...] = ()
    """Drawn over the artwork and under the bubbles, sorted among themselves.

    Composition step 4 is "objects and effects", and effects land at the end of
    it: a speed line in front of the character it belongs to. Putting them in
    the same z stream as sprites would let one hide behind a body, which is
    worth having one day and is not worth a second sort order today.
    """

    bubbles: tuple[Bubble, ...] = ()
    marks: tuple[Mark, ...] = ()
    warnings: tuple[str, ...] = ()
    frame_weight: float = 1.0
    """Multiplier on the style's panel stroke. Zero means no frame at all."""

    def draws_of(self, kind: DrawKind) -> tuple[SpriteDraw, ...]:
        return tuple(draw for draw in self.draws if draw.kind is kind)

    def mark(self, kind: str, label: str | None = None) -> Mark | None:
        for candidate in self.marks:
            if candidate.kind == kind and (label is None or candidate.label == label):
                return candidate
        return None

    def bubble_of(self, speaker: str) -> Bubble | None:
        for bubble in self.bubbles:
            if bubble.speaker == speaker:
                return bubble
        return None


@dataclass(frozen=True, slots=True)
class Scene:
    """A whole page, resolved. The only thing a backend ever sees."""

    title: str
    width: int
    height: int
    style: Style
    panels: tuple[PanelScene, ...]
    engine_version: str
    asset_fingerprint: str
    """Hash of every sprite that went into this scene, for ``inkpy verify``."""

    script_fingerprint: str
    """Hash of the strip that produced it, likewise. Both halves are needed:
    the assets answer "is the artwork still what it was", this one answers
    "is this still what the strip says", and a render is stale if either has
    moved."""

    background_colour: str = "#ffffff"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def page(self) -> Rect:
        return Rect(0.0, 0.0, float(self.width), float(self.height))

    def panel(self, panel_id: int) -> PanelScene:
        for candidate in self.panels:
            if candidate.id == panel_id:
                return candidate
        available = ", ".join(str(p.id) for p in self.panels)
        raise KeyError(f"no panel with id {panel_id} in scene. Available: {available}.")

    def all_warnings(self) -> tuple[str, ...]:
        """Page-level warnings followed by each panel's, in panel order."""
        collected = list(self.warnings)
        for panel in self.panels:
            collected.extend(panel.warnings)
        return tuple(collected)
