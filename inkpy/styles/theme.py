"""Styles: the handful of numbers and colours that give a strip its look.

Every length is stored as a ratio, never as pixels. A style has to hold up on a
600px thumbnail and on a 4000px print without the author touching anything, so
the only absolute quantity in the system is the page size, and each panel
resolves the style against its own rectangle via :class:`PanelStyle`.
"""

from __future__ import annotations

from dataclasses import dataclass

from inkpy.errors import RenderError, did_you_mean
from inkpy.geometry import Rect
from inkpy.styles.typeface import Typeface, load_typeface


@dataclass(frozen=True, slots=True)
class Style:
    """A named theme. Ratios are relative to the panel unless stated."""

    name: str

    # Type
    font: str = "DejaVuSans.ttf"
    font_size: float = 0.048
    """Fraction of the panel height.

    Deliberately modest, because a round bubble costs area faster than it
    costs type: the ellipse around a block of text is √2 times its width and
    √2 times its height. Until v0.2 breaks lines to an oval and earns that
    back, a smaller face is what keeps a bubble from eating its own panel.
    """
    min_font_size: float = 0.038
    """Floor when a bubble has to shrink to fit. Below this, legibility goes."""
    line_spacing: float = 1.1

    # Bubbles
    bubble_padding: float = 0.45
    """Fraction of the font size, applied inside the bubble on all sides."""
    bubble_band: float = 0.35
    """Fraction of the panel height reserved for bubbles before placement."""
    max_bubble_width: float = 0.62
    """Fraction of the panel width a single bubble may occupy."""
    bubble_gap: float = 0.35
    """Minimum space between two bubbles, as a fraction of the font size."""
    tail_length: float = 0.9
    """How far a tail reaches, as a fraction of the font size, when the
    speaker's mouth is unknown."""

    thought_bloom: float = 0.10
    """How much of a thought bubble's radius its scallops occupy.

    Layout has to know: the cloud's *valleys* are what must clear the text, so
    the bubble is inflated by this much and the renderer draws the peaks out to
    the edge of the rectangle the IR reports. Otherwise the IR would describe a
    smaller shape than the one on the page, and every assertion made against it
    would be off by exactly this margin."""

    # Strokes, as a fraction of the page's shorter side
    panel_stroke: float = 0.0032
    bubble_stroke: float = 0.0022

    # Colours
    page_colour: str = "#ffffff"
    panel_fill: str = "#f4f4f2"
    panel_stroke_colour: str = "#1b1b1b"
    bubble_fill: str = "#ffffff"
    bubble_stroke_colour: str = "#1b1b1b"
    text_colour: str = "#111111"

    def typeface(self) -> Typeface:
        return load_typeface(self.font)


DEFAULT = Style(name="default")

_STYLES: dict[str, Style] = {
    "default": DEFAULT,
    # A denser variant: smaller type, tighter bubbles, heavier frames.
    "compact": Style(
        name="compact",
        font_size=0.046,
        min_font_size=0.032,
        line_spacing=1.05,
        bubble_padding=0.38,
        bubble_band=0.30,
        max_bubble_width=0.7,
        panel_stroke=0.004,
    ),
}


def get_style(name: str) -> Style:
    try:
        return _STYLES[name]
    except KeyError:
        raise RenderError(
            f"Unknown style '{name}'. {did_you_mean(name, list(_STYLES))}"
        ) from None


def style_names() -> list[str]:
    return sorted(_STYLES)


@dataclass(frozen=True, slots=True)
class PanelStyle:
    """A style resolved against one panel: everything in absolute pixels."""

    style: Style
    typeface: Typeface
    panel: Rect
    font_size: float
    min_font_size: float
    line_height: float
    padding: float
    bubble_gap: float
    max_bubble_width: float
    band_height: float
    tail_length: float
    panel_stroke: float
    bubble_stroke: float

    @classmethod
    def resolve(cls, style: Style, panel: Rect, page_side: float) -> PanelStyle:
        face = style.typeface()
        font_size = style.font_size * panel.height
        return cls(
            style=style,
            typeface=face,
            panel=panel,
            font_size=font_size,
            min_font_size=style.min_font_size * panel.height,
            line_height=face.line_height(font_size, style.line_spacing),
            padding=style.bubble_padding * font_size,
            bubble_gap=style.bubble_gap * font_size,
            max_bubble_width=style.max_bubble_width * panel.width,
            band_height=style.bubble_band * panel.height,
            tail_length=style.tail_length * font_size,
            panel_stroke=style.panel_stroke * page_side,
            bubble_stroke=style.bubble_stroke * page_side,
        )

    def at_font_size(self, font_size: float) -> PanelStyle:
        """The same style with a different type size, for shrink-to-fit."""
        return PanelStyle(
            style=self.style,
            typeface=self.typeface,
            panel=self.panel,
            font_size=font_size,
            min_font_size=self.min_font_size,
            line_height=self.typeface.line_height(font_size, self.style.line_spacing),
            padding=self.style.bubble_padding * font_size,
            bubble_gap=self.style.bubble_gap * font_size,
            max_bubble_width=self.max_bubble_width,
            band_height=self.band_height,
            tail_length=self.style.tail_length * font_size,
            panel_stroke=self.panel_stroke,
            bubble_stroke=self.bubble_stroke,
        )

    @property
    def band(self) -> Rect:
        """The strip of panel reserved for bubbles, before any placement."""
        return Rect(
            self.panel.x,
            self.panel.top - self.band_height,
            self.panel.width,
            self.band_height,
        )
