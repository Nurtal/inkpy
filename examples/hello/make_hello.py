"""Draw the smallest asset library a strip can be rendered from.

``examples/make_assets.py`` draws a cast; this draws the minimum: one
character, one pose, one expression, one background. It exists so that the
smoke test in the README — the four commands someone runs on a fresh clone to
find out whether the engine works at all — depends on as little as possible.

Run it from anywhere::

    python examples/hello/make_hello.py             # → examples/hello/assets
    python examples/hello/make_hello.py /tmp/lib    # → somewhere else

As in the larger generator, the manifest is computed from the very constants
used to draw the sprite: a head anchor cannot drift away from the head it
points at when both come from the same number.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

DEFAULT_ROOT = Path(__file__).parent / "assets"

SS = 4
"""Supersampling factor. Drawing large and shrinking is the cheapest
antialiasing there is, and it is deterministic."""

INK = (34, 34, 42, 255)
LINE = 5
SKIN = (232, 200, 168, 255)
SHIRT = (104, 138, 172, 255)
TROUSERS = (74, 82, 104, 255)

BODY = (260, 460)
"""Canvas of the body sprite, in pixels. Feet at the bottom edge: the anchor
is the ground under them, so any margin below would lift the character off it."""

HEAD = (130, 92)
"""Centre of the head on the body sprite, y down as Pillow counts it."""

HEAD_R = 72
MOUTH_DROP = 30
"""How far below the head's centre the mouth sits. A tail aims here."""

FACE = (176, 176)


class Pen:
    """A drawing surface that hides the supersampling."""

    def __init__(self, width: int, height: int, background=(0, 0, 0, 0)) -> None:
        self.size = (width, height)
        self.image = Image.new("RGBA", (width * SS, height * SS), background)
        self.draw = ImageDraw.Draw(self.image)

    def _box(self, box):
        return tuple(value * SS for value in box)

    def ellipse(self, box, fill=None, outline=INK, width=LINE) -> None:
        self.draw.ellipse(self._box(box), fill=fill, outline=outline, width=width * SS)

    def rounded(self, box, radius, fill=None, outline=INK, width=LINE) -> None:
        self.draw.rounded_rectangle(
            self._box(box), radius=radius * SS, fill=fill, outline=outline, width=width * SS
        )

    def line(self, points, fill=INK, width=LINE) -> None:
        self.draw.line(
            [(x * SS, y * SS) for x, y in points], fill=fill, width=width * SS, joint="curve"
        )

    def arc(self, box, start, end, fill=INK, width=LINE) -> None:
        self.draw.arc(self._box(box), start, end, fill=fill, width=width * SS)

    def limb(self, points, fill, thickness=22) -> None:
        """A stroked limb: the outline underneath, the fill on top of it."""
        self.line(points, fill=INK, width=thickness + LINE * 2)
        self.line(points, fill=fill, width=thickness)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.resize(self.size, Image.LANCZOS).save(path)


def body() -> Pen:
    """One standing pose. The face layer goes on top of the blank head."""
    pen = Pen(*BODY)
    cx, cy = HEAD
    pen.limb([(112, 340), (108, 452)], TROUSERS, thickness=30)
    pen.limb([(148, 340), (152, 452)], TROUSERS, thickness=30)
    pen.limb([(90, 220), (58, 316)], SHIRT, thickness=20)
    pen.limb([(170, 220), (202, 316)], SHIRT, thickness=20)
    pen.rounded((78, 178, 182, 356), radius=44, fill=SHIRT)
    pen.limb([(cx, 160), (cx, 190)], SKIN, thickness=26)  # neck
    pen.ellipse((cx - HEAD_R, cy - HEAD_R, cx + HEAD_R, cy + HEAD_R), fill=SKIN)
    return pen


def face() -> Pen:
    """One expression, drawn on its own canvas and pinned to the head anchor."""
    pen = Pen(*FACE)
    cx = cy = FACE[0] / 2
    for x in (cx - 26, cx + 26):
        pen.ellipse((x - 7, cy - 22, x + 7, cy - 4), fill=INK, outline=None)
    pen.arc((cx - 30, cy + 4, cx + 30, cy + 44), 20, 160, width=5)
    return pen


def background() -> Pen:
    """A room, reduced to a floor line and a picture on the wall."""
    pen = Pen(800, 600, background=(238, 233, 224, 255))
    pen.draw.rectangle((0, 430 * SS, 800 * SS, 600 * SS), fill=(206, 194, 176, 255))
    pen.line([(0, 430), (800, 430)], width=6)
    pen.rounded((520, 120, 700, 260), radius=6, fill=(196, 214, 222, 255), width=7)
    pen.line([(540, 230), (600, 170), (650, 230)], width=6)
    return pen


def anchor(point: tuple[float, float], canvas: tuple[int, int]) -> list[float]:
    """A pixel position on a sprite, as the engine wants it.

    Sprites are drawn top-left, y down; manifests are bottom-left, y up. Doing
    the conversion here, next to the drawing, is what keeps the two honest.
    """
    x, y = point
    width, height = canvas
    return [round(x / width, 4), round(1 - y / height, 4)]


def manifest() -> dict:
    return {
        "name": "blob",
        "anchor": "feet",
        # Short enough to stand under the bubble band without being scaled
        # down for it: the smoke test should come out silent, so that any
        # warning it ever prints is worth reading.
        "default_height": 0.55,
        "flippable": True,
        "poses": {
            "idle": {
                "head_anchor": anchor(HEAD, BODY),
                "mouth_offset": anchor((HEAD[0], HEAD[1] + MOUTH_DROP), BODY),
            }
        },
        "expressions": ["neutral"],
    }


def build(root: Path) -> Path:
    """Write the whole library under ``root``. Returns where it landed."""
    character = root / "characters" / "blob"
    body().save(character / "body" / "idle.png")
    face().save(character / "face" / "neutral.png")
    character.mkdir(parents=True, exist_ok=True)
    (character / "character.yaml").write_text(
        "# Generated by examples/hello/make_hello.py — edit that, not this.\n"
        + yaml.safe_dump(manifest(), sort_keys=False),
        encoding="utf-8",
    )
    background().save(root / "backgrounds" / "room.png")
    return root


def main(argv: list[str]) -> None:
    root = Path(argv[1]) if len(argv) > 1 else DEFAULT_ROOT
    written = build(root)
    try:  # Say it the way the README says it, when run from the repository.
        written = written.relative_to(Path.cwd())
    except ValueError:
        pass
    print(f"wrote the hello library to {written}")


if __name__ == "__main__":
    main(sys.argv)
