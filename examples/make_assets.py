"""Draw the example asset library.

The strip in this directory needs artwork, and shipping PNGs in a repository
means shipping files nobody can review in a diff. So the examples are drawn by
this script instead: original geometric characters, no third-party artwork, and
a manifest generated from the very constants used to draw the sprites — a head
anchor cannot drift away from the head it points at if both come from the same
number.

Run it from the repository root::

    python examples/make_assets.py

InkPy itself never does this. The engine draws nothing; this is an author's
job, and this script is standing in for an author with a pen.
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent / "assets"
SS = 4
"""Supersampling factor. Drawing large and shrinking is the cheapest
antialiasing there is, and it is deterministic."""

INK = (34, 34, 42, 255)
LINE = 5

CAT_FUR = (168, 176, 190, 255)
CAT_BELLY = (214, 219, 228, 255)
HUMAN_SKIN = (232, 194, 166, 255)
HUMAN_SHIRT = (196, 122, 106, 255)
HUMAN_TROUSERS = (86, 96, 122, 255)


class Pen:
    """A drawing surface that hides the supersampling."""

    def __init__(self, width: int, height: int, background=(0, 0, 0, 0)) -> None:
        self.width = width
        self.height = height
        self.image = Image.new("RGBA", (width * SS, height * SS), background)
        self.draw = ImageDraw.Draw(self.image)

    def _box(self, box) -> tuple[float, float, float, float]:
        return tuple(value * SS for value in box)

    def _points(self, points) -> list[tuple[float, float]]:
        return [(x * SS, y * SS) for x, y in points]

    def ellipse(self, box, fill=None, outline=INK, width=LINE) -> None:
        self.draw.ellipse(self._box(box), fill=fill, outline=outline, width=width * SS)

    def polygon(self, points, fill=None, outline=INK) -> None:
        self.draw.polygon(self._points(points), fill=fill, outline=outline, width=LINE * SS)

    def line(self, points, fill=INK, width=LINE) -> None:
        self.draw.line(self._points(points), fill=fill, width=width * SS, joint="curve")

    def rounded(self, box, radius, fill=None, outline=INK, width=LINE) -> None:
        self.draw.rounded_rectangle(
            self._box(box), radius=radius * SS, fill=fill, outline=outline, width=width * SS
        )

    def arc(self, box, start, end, fill=INK, width=LINE) -> None:
        self.draw.arc(self._box(box), start, end, fill=fill, width=width * SS)

    def tail(self, points, fill, thickness=26) -> None:
        """A stroked limb: the outline underneath, the fill on top of it."""
        self.line(points, fill=INK, width=thickness + LINE * 2)
        self.line(points, fill=fill, width=thickness)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.resize((self.width, self.height), Image.LANCZOS).save(path)


# --------------------------------------------------------------------------
# Cat
# --------------------------------------------------------------------------

CAT_IDLE = (300, 520)
CAT_IDLE_HEAD = (150, 108)
CAT_IDLE_HEAD_R = 84

CAT_SITTING = (340, 420)
CAT_SITTING_HEAD = (170, 100)
CAT_SITTING_HEAD_R = 84

CAT_FACE = (200, 200)


def cat_head(pen: Pen, cx: float, cy: float, r: float) -> None:
    """Ears first, so the skull's outline closes over their bases."""
    for sign in (-1, 1):
        base_x = cx + sign * r * 0.62
        pen.polygon(
            [
                (base_x - sign * r * 0.30, cy - r * 0.62),
                (base_x + sign * r * 0.16, cy - r * 1.42),
                (base_x + sign * r * 0.40, cy - r * 0.42),
            ],
            fill=CAT_FUR,
        )
    pen.ellipse((cx - r, cy - r * 0.92, cx + r, cy + r * 0.86), fill=CAT_FUR)


def cat_idle() -> Pen:
    pen = Pen(*CAT_IDLE)
    cx, cy = CAT_IDLE_HEAD
    # Tail, behind everything.
    pen.tail([(226, 436), (274, 392), (282, 312), (250, 272)], CAT_FUR)
    # Body and legs. The body reaches up behind the skull so the two read as
    # one animal rather than as a head resting on a bag.
    pen.rounded((78, 150, 222, 470), radius=86, fill=CAT_FUR)
    pen.ellipse((112, 300, 188, 466), fill=CAT_BELLY, outline=None)
    for x in (96, 168):
        pen.rounded((x, 420, x + 40, 486), radius=18, fill=CAT_FUR)
    cat_head(pen, cx, cy, CAT_IDLE_HEAD_R)
    return pen


def cat_sitting() -> Pen:
    pen = Pen(*CAT_SITTING)
    cx, cy = CAT_SITTING_HEAD
    pen.tail([(256, 360), (308, 332), (314, 266), (284, 240)], CAT_FUR)
    # A seated cat is a triangle with a rounded base.
    pen.polygon(
        [(170, 130), (272, 372), (68, 372)],
        fill=CAT_FUR,
    )
    pen.rounded((66, 300, 274, 380), radius=40, fill=CAT_FUR)
    pen.ellipse((128, 250, 212, 372), fill=CAT_BELLY, outline=None)
    for x in (96, 208):
        pen.ellipse((x, 344, x + 40, 380), fill=CAT_FUR)
    cat_head(pen, cx, cy, CAT_SITTING_HEAD_R)
    return pen


def cat_face(expression: str) -> Pen:
    """Eyes, muzzle and whiskers on transparency, centred on the head anchor."""
    pen = Pen(*CAT_FACE)
    cx, cy = 100, 100
    left, right = cx - 34, cx + 34
    eye_y = cy - 16

    if expression == "neutral":
        for x in (left, right):
            pen.ellipse((x - 16, eye_y - 18, x + 16, eye_y + 18), fill=(250, 250, 250, 255))
            pen.ellipse((x - 6, eye_y - 12, x + 6, eye_y + 12), fill=INK, outline=None)
    elif expression == "bored":
        for x in (left, right):
            pen.ellipse((x - 16, eye_y - 18, x + 16, eye_y + 18), fill=(250, 250, 250, 255))
            pen.ellipse((x - 6, eye_y - 4, x + 6, eye_y + 12), fill=INK, outline=None)
            # Heavy lids: half the eye, and all of the mood.
            pen.polygon(
                [(x - 18, eye_y - 20), (x + 18, eye_y - 20), (x + 18, eye_y - 2), (x - 18, eye_y - 2)],
                fill=CAT_FUR,
                outline=None,
            )
            pen.line([(x - 18, eye_y - 2), (x + 18, eye_y - 2)], width=4)
    elif expression == "annoyed":
        for x, direction in ((left, 1), (right, -1)):
            pen.ellipse((x - 16, eye_y - 14, x + 16, eye_y + 18), fill=(250, 250, 250, 255))
            pen.ellipse((x - 6, eye_y - 6, x + 6, eye_y + 10), fill=INK, outline=None)
            pen.line(
                [(x - 20 * direction, eye_y - 30), (x + 20 * direction, eye_y - 16)], width=5
            )

    # Muzzle: nose, mouth, whiskers.
    pen.polygon(
        [(cx - 9, cy + 24), (cx + 9, cy + 24), (cx, cy + 34)],
        fill=(214, 140, 150, 255),
    )
    if expression == "annoyed":
        pen.line([(cx - 16, cy + 50), (cx, cy + 42), (cx + 16, cy + 50)], width=4)
    else:
        pen.arc((cx - 20, cy + 30, cx, cy + 50), 0, 150, width=4)
        pen.arc((cx, cy + 30, cx + 20, cy + 50), 30, 180, width=4)
    for sign in (-1, 1):
        for offset in (-8, 2, 12):
            pen.line(
                [(cx + sign * 14, cy + 30 + offset), (cx + sign * 60, cy + 22 + offset * 1.6)],
                width=3,
            )
    return pen


# --------------------------------------------------------------------------
# Human
# --------------------------------------------------------------------------

HUMAN_IDLE = (300, 760)
HUMAN_IDLE_HEAD = (150, 96)
HUMAN_IDLE_HEAD_R = 74

HUMAN_FACE = (180, 180)


def human_idle() -> Pen:
    pen = Pen(*HUMAN_IDLE)
    cx, cy = HUMAN_IDLE_HEAD
    r = HUMAN_IDLE_HEAD_R
    # Legs, then torso over their tops, then arms, then head.
    for x in (108, 156):
        pen.rounded((x, 470, x + 38, 736), radius=18, fill=HUMAN_TROUSERS)
    pen.rounded((92, 210, 208, 500), radius=44, fill=HUMAN_SHIRT)
    pen.rounded((62, 240, 100, 452), radius=18, fill=HUMAN_SHIRT)
    pen.rounded((200, 240, 238, 452), radius=18, fill=HUMAN_SHIRT)
    pen.ellipse((62, 430, 100, 470), fill=HUMAN_SKIN)
    pen.ellipse((200, 430, 238, 470), fill=HUMAN_SKIN)
    # The neck runs from inside the skull to under the collar. Any gap at
    # either end and the head reads as detached; too much showing between
    # them and it reads as a lollipop.
    pen.rounded((132, 140, 168, 225), radius=14, fill=HUMAN_SKIN)
    pen.ellipse((cx - r, cy - r, cx + r, cy + r), fill=HUMAN_SKIN)
    # Hair sits on the skull rather than replacing it, and stops well above
    # the eyes — the face sprite pins its features to this same centre.
    pen.polygon(
        [
            (cx - r - 2, cy - 30),
            (cx - r * 0.7, cy - r - 14),
            (cx + r * 0.7, cy - r - 14),
            (cx + r + 2, cy - 30),
        ],
        fill=(72, 58, 52, 255),
    )
    return pen


def human_face(expression: str) -> Pen:
    pen = Pen(*HUMAN_FACE)
    cx, cy = 90, 90
    left, right = cx - 26, cx + 26
    eye_y = cy - 6

    for x in (left, right):
        if expression == "sleepy":
            pen.arc((x - 15, eye_y - 12, x + 15, eye_y + 12), 200, 340, width=5)
        else:
            pen.ellipse((x - 8, eye_y - 9, x + 8, eye_y + 9), fill=INK, outline=None)

    if expression == "happy":
        pen.arc((cx - 30, cy + 8, cx + 30, cy + 50), 20, 160, width=5)
    elif expression == "sleepy":
        pen.ellipse((cx - 12, cy + 22, cx + 12, cy + 48), fill=(120, 70, 70, 255))
    else:
        pen.line([(cx - 22, cy + 34), (cx + 22, cy + 34)], width=5)
    return pen


# --------------------------------------------------------------------------
# Objects and backgrounds
# --------------------------------------------------------------------------


def mug() -> Pen:
    pen = Pen(140, 150)
    pen.arc((88, 44, 136, 100), 270, 90, width=9)
    pen.rounded((18, 30, 104, 138), radius=14, fill=(226, 226, 232, 255))
    pen.ellipse((18, 18, 104, 46), fill=(198, 128, 92, 255))
    for x, phase in ((44, 0.0), (66, 1.2)):
        points = [
            (x + math.sin(phase + step / 3.0) * 7, 14 - step * 4) for step in range(5)
        ]
        pen.line(points, fill=(214, 214, 220, 255), width=4)
    return pen


def kitchen() -> Pen:
    pen = Pen(1400, 1000, background=(238, 234, 224, 255))
    pen.draw.rectangle((0, 0, 1400 * SS, 520 * SS), fill=(226, 220, 206, 255))
    # Tiles above the counter.
    for x in range(0, 1400, 100):
        pen.line([(x, 300), (x, 520)], fill=(212, 205, 190, 255), width=3)
    for y in range(300, 521, 55):
        pen.line([(0, y), (1400, y)], fill=(212, 205, 190, 255), width=3)
    # Window.
    pen.rounded((120, 90, 520, 330), radius=8, fill=(196, 222, 234, 255), width=7)
    pen.line([(320, 90), (320, 330)], width=6)
    pen.line([(120, 210), (520, 210)], width=6)
    # Counter and cupboards.
    pen.draw.rectangle((0, 520 * SS, 1400 * SS, 560 * SS), fill=(150, 122, 96, 255))
    pen.draw.rectangle((0, 560 * SS, 1400 * SS, 1000 * SS), fill=(206, 198, 184, 255))
    for x in range(60, 1400, 220):
        pen.rounded((x, 600, x + 180, 900), radius=6, fill=(196, 187, 172, 255), width=4)
        pen.line([(x + 150, 640), (x + 150, 700)], width=6)
    pen.line([(0, 520), (1400, 520)], width=6)
    pen.line([(0, 560), (1400, 560)], width=6)
    return pen


def garden() -> Pen:
    pen = Pen(1400, 1000, background=(198, 224, 238, 255))
    pen.draw.rectangle((0, 560 * SS, 1400 * SS, 1000 * SS), fill=(158, 196, 130, 255))
    pen.line([(0, 560), (1400, 560)], width=6)
    for x, radius in ((240, 150), (1080, 190), (700, 110)):
        pen.ellipse((x - radius, 500 - radius, x + radius, 500 + radius), fill=(108, 160, 96, 255))
        pen.rounded((x - 18, 480, x + 18, 620), radius=8, fill=(126, 98, 74, 255))
    for x in range(80, 1400, 190):
        pen.arc((x, 700, x + 120, 780), 200, 340, width=5)
    return pen


# --------------------------------------------------------------------------
# Manifests
# --------------------------------------------------------------------------


def anchor(point: tuple[int, int], canvas: tuple[int, int]) -> list[float]:
    """A pixel position on a sprite, as the engine wants it.

    Sprites are drawn top-left, y down; manifests are bottom-left, y up. Doing
    the conversion here, next to the drawing, is what keeps the two honest.
    """
    x, y = point
    width, height = canvas
    return [round(x / width, 4), round(1 - y / height, 4)]


def cat_manifest() -> dict:
    idle_head = anchor(CAT_IDLE_HEAD, CAT_IDLE)
    sitting_head = anchor(CAT_SITTING_HEAD, CAT_SITTING)
    return {
        "name": "cat",
        "anchor": "feet",
        "default_height": 0.52,
        "flippable": True,
        "poses": {
            "idle": {
                "head_anchor": idle_head,
                # The mouth is a little below the head's centre, on the muzzle.
                "mouth_offset": anchor(
                    (CAT_IDLE_HEAD[0], CAT_IDLE_HEAD[1] + 34), CAT_IDLE
                ),
            },
            "sitting": {
                "head_anchor": sitting_head,
                "mouth_offset": anchor(
                    (CAT_SITTING_HEAD[0], CAT_SITTING_HEAD[1] + 34), CAT_SITTING
                ),
            },
        },
        "expressions": ["neutral", "bored", "annoyed"],
    }


def human_manifest() -> dict:
    return {
        "name": "human",
        "anchor": "feet",
        "default_height": 0.86,
        "flippable": True,
        "poses": {
            "idle": {
                "head_anchor": anchor(HUMAN_IDLE_HEAD, HUMAN_IDLE),
                "mouth_offset": anchor(
                    (HUMAN_IDLE_HEAD[0], HUMAN_IDLE_HEAD[1] + 30), HUMAN_IDLE
                ),
            }
        },
        "expressions": ["neutral", "happy", "sleepy"],
    }


def write_manifest(directory: Path, manifest: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "character.yaml").write_text(
        "# Generated by examples/make_assets.py — edit that, not this.\n"
        + yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )


def main() -> None:
    cat = ROOT / "characters" / "cat"
    cat_idle().save(cat / "body" / "idle.png")
    cat_sitting().save(cat / "body" / "sitting.png")
    for expression in ("neutral", "bored", "annoyed"):
        cat_face(expression).save(cat / "face" / f"{expression}.png")
    write_manifest(cat, cat_manifest())

    human = ROOT / "characters" / "human"
    human_idle().save(human / "body" / "idle.png")
    for expression in ("neutral", "happy", "sleepy"):
        human_face(expression).save(human / "face" / f"{expression}.png")
    write_manifest(human, human_manifest())

    mug().save(ROOT / "objects" / "mug.png")
    kitchen().save(ROOT / "backgrounds" / "kitchen.png")
    garden().save(ROOT / "backgrounds" / "garden.png")

    print(f"wrote the example library to {ROOT}")


if __name__ == "__main__":
    main()
