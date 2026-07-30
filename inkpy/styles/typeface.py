"""Text measurement and glyph outlines, from a font shipped with the package.

Two promises meet here.

*Measure with the final font, never estimate.* SVG exposes no text metrics, so
a viewer asked to lay out a ``<text>`` element would make its own decisions
about which font to substitute and where each glyph lands.

*Same input, same output.* The only way to keep that promise across machines is
to stop shipping text as text: every line is converted to an explicit path
built from the packaged font's own outlines. Nothing is resolved from the
system, and no renderer gets a say.

The same ``Typeface`` object answers both questions, so a line can never be
measured with one set of metrics and drawn with another.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

from inkpy.errors import RenderError

FONT_DIR = Path(__file__).parent / "fonts"


@dataclass(frozen=True, slots=True)
class TextMetrics:
    """Measurements of one run of text at a given size, in pixels."""

    width: float
    ascent: float
    descent: float
    """Distance below the baseline, positive."""

    @property
    def height(self) -> float:
        return self.ascent + self.descent


class Typeface:
    """One font file, loaded once, queried in font units and in pixels."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise RenderError(
                f"font not found: {path}. Fonts ship inside the package; the "
                f"installation looks incomplete."
            )
        self.path = path
        try:
            self._font = TTFont(path, lazy=True)
        except Exception as exc:  # fontTools raises a wide range of errors
            raise RenderError(f"cannot read font {path}: {exc}") from exc
        self._cmap = self._font.getBestCmap()
        self._glyphs = self._font.getGlyphSet()
        self._hmtx = self._font["hmtx"]
        head = self._font["head"]
        hhea = self._font["hhea"]
        self.units_per_em: int = head.unitsPerEm
        self.ascender: int = hhea.ascent
        self.descender: int = -hhea.descent  # positive, below the baseline
        self.line_gap: int = hhea.lineGap
        self.family: str = str(path.stem)

    # -- glyph lookup ----------------------------------------------------

    def glyph_name(self, char: str) -> str:
        try:
            return self._cmap[ord(char)]
        except KeyError:
            raise RenderError(
                f"character {char!r} (U+{ord(char):04X}) is not in font "
                f"'{self.family}'. Bubbles are drawn as outlines, so an "
                f"unavailable glyph cannot be substituted silently."
            ) from None

    def supports(self, text: str) -> bool:
        return all(ord(char) in self._cmap for char in text)

    def unsupported(self, text: str) -> list[str]:
        """Distinct characters this face cannot draw, in order of appearance."""
        missing: list[str] = []
        for char in text:
            if ord(char) not in self._cmap and char not in missing:
                missing.append(char)
        return missing

    # -- metrics ---------------------------------------------------------

    def advance_units(self, char: str) -> int:
        return self._hmtx[self.glyph_name(char)][0]

    def measure(self, text: str, size: float) -> TextMetrics:
        """Width of a run and the vertical extent of a line at ``size`` px.

        Ascent and descent come from the face, not from the run: a line of
        text occupies a full line box whether or not it happens to contain a
        descender, otherwise consecutive lines would drift.
        """
        scale = size / self.units_per_em
        total = sum(self.advance_units(char) for char in text)
        return TextMetrics(
            width=total * scale,
            ascent=self.ascender * scale,
            descent=self.descender * scale,
        )

    def width(self, text: str, size: float) -> float:
        return self.measure(text, size).width

    def line_height(self, size: float, spacing: float = 1.0) -> float:
        """Baseline-to-baseline distance."""
        scale = size / self.units_per_em
        natural = (self.ascender + self.descender + self.line_gap) * scale
        return natural * spacing

    # -- outlines --------------------------------------------------------

    def text_path(self, text: str, size: float, x: float, y: float) -> str:
        """SVG path data for a whole run, positioned at a baseline point.

        Every glyph of the run is emitted into a single path, already scaled
        and advanced, so a line of dialogue costs one element. Coordinates come
        out in the engine's space — ``x`` right, ``y`` **up**; the backend
        flips the document once, at the very end.
        """
        scale = size / self.units_per_em
        pen = SVGPathPen(self._glyphs, ntos=_num)
        pen_x = 0.0
        for char in text:
            name = self.glyph_name(char)
            transform = (scale, 0, 0, scale, x + pen_x * scale, y)
            self._glyphs[name].draw(TransformPen(pen, transform))
            pen_x += self._hmtx[name][0]
        return pen.getCommands()


def _num(value: float) -> str:
    """Fixed-precision formatting, so identical geometry yields identical bytes."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


@lru_cache(maxsize=8)
def load_typeface(file_name: str) -> Typeface:
    """Load a packaged font by file name. Cached: fonts are immutable."""
    return Typeface(FONT_DIR / file_name)


def available_fonts() -> list[str]:
    return sorted(path.name for path in FONT_DIR.glob("*.ttf"))
