"""Closed vocabularies of the strip format.

Everything the author can choose from is enumerated. A closed set is what lets
the engine stay small: no general-purpose layout solver, no free-form styling.
"""

from __future__ import annotations

from enum import Enum


class Layout(str, Enum):
    """Named page templates. Names read ``COLSxROWS``; ``+`` mixes row widths."""

    ONE = "1x1"
    TWO_ACROSS = "2x1"
    TWO_DOWN = "1x2"
    STRIP = "4x1"
    GRID = "2x2"
    ONE_OVER_TWO = "1+2"
    TWO_OVER_ONE = "2+1"

    @property
    def capacity(self) -> int:
        """How many panels this template holds — exactly, not at most."""
        return _CAPACITY[self]


_CAPACITY: dict[Layout, int] = {
    Layout.ONE: 1,
    Layout.TWO_ACROSS: 2,
    Layout.TWO_DOWN: 2,
    Layout.STRIP: 4,
    Layout.GRID: 4,
    Layout.ONE_OVER_TWO: 3,
    Layout.TWO_OVER_ONE: 3,
}


class Camera(str, Enum):
    """Shot distance. Derives sprite scale so authors don't tune numbers."""

    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE = "close"

    @property
    def scale_factor(self) -> float:
        """Multiplier applied to a character's ``default_height``.

        ``medium`` is the reference the manifests are authored against, hence
        exactly 1.0.
        """
        return _CAMERA_SCALE[self]


_CAMERA_SCALE: dict[Camera, float] = {
    Camera.WIDE: 0.62,
    Camera.MEDIUM: 1.0,
    Camera.CLOSE: 1.55,
}


class BubbleType(str, Enum):
    """Bubble silhouette and tail behaviour."""

    SPEECH = "speech"
    THOUGHT = "thought"
    SHOUT = "shout"
    NARRATION = "narration"

    @property
    def has_tail(self) -> bool:
        """A narration caption is not spoken, so it points at nobody."""
        return self is not BubbleType.NARRATION

    @property
    def needs_speaker(self) -> bool:
        return self.has_tail


class Anchor(str, Enum):
    """Reference point of a body sprite."""

    FEET = "feet"
    CENTER = "center"


class Frame(str, Enum):
    """Weight of a panel's border.

    A heavier frame reads as emphasis and a missing one as a panel bleeding
    into the page; both are ordinary comics grammar, and both are one number.
    """

    NONE = "none"
    THIN = "thin"
    NORMAL = "normal"
    BOLD = "bold"

    @property
    def weight(self) -> float:
        """Multiplier on the style's panel stroke."""
        return _FRAME_WEIGHT[self]


_FRAME_WEIGHT: dict[Frame, float] = {
    Frame.NONE: 0.0,
    Frame.THIN: 0.55,
    Frame.NORMAL: 1.0,
    Frame.BOLD: 2.1,
}


class EffectKind(str, Enum):
    """Closed set of drawn effects."""

    SPEED_LINES = "speed_lines"


class Direction(str, Enum):
    """Where an effect points. Screen directions, not compass ones."""

    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"

    @property
    def vector(self) -> tuple[float, float]:
        """Unit vector in engine space: x right, y up."""
        return _DIRECTION[self]


_DIRECTION: dict[Direction, tuple[float, float]] = {
    Direction.LEFT: (-1.0, 0.0),
    Direction.RIGHT: (1.0, 0.0),
    Direction.UP: (0.0, 1.0),
    Direction.DOWN: (0.0, -1.0),
}
