"""Cut the rat cast out of the character sheets into an InkPy asset library.

The artwork in ``sheets/`` is four sheets of the same four characters, one
sheet per emotion, drawn in pencil on cream paper. Turning that into assets is
three problems, and the third is the one that matters.

**The paper has to go.** A sprite is composited over a panel, so anything that
is not the character must be transparent — but only what is *outside* the
character. The whites inside a hoodie are the hoodie, not background. So the
paper is flooded from the border and everything the flood cannot reach stays
opaque, with the graphite itself feathering the outline so the edge does not
turn into a cut-out.

**The captions have to go.** ``DATA SCIENTIST SENIOR`` is a label on a model
sheet, not part of the character, and the art stops cleanly above it.

**The characters must not change size between sheets.** This is the one that
would quietly ruin every strip. The four sheets were drawn separately, so the
same character stands a few percent taller on one than on another and sits a
few dozen pixels to the side. Composited into consecutive panels, they would
visibly breathe and drift — precisely the inconsistency InkPy exists to
prevent. Each sheet is therefore measured, not trusted: the character's body is
isolated as the connected run of graphite standing on the ground, and every
expression is scaled and shifted so that body lands at exactly the same height
and the same place on a shared canvas. What is left differing between two
sprites of one character is the drawing, which is the whole point.

Effects — the anger bolts, the steam, the surprise marks — ride along with the
body, since they scale and move with it.

The two backdrops at the end of this file are the one thing here that is drawn
rather than cut: the sheets are model sheets and carry no scenery. They are
kept deliberately faint, and on the same paper tone as the sheets, so that they
sit behind the cast instead of competing with it.

Run it from the repository root. The measuring is done with numpy, which the
engine itself does not use, so it comes with the ``examples`` extra::

    pip install -e ".[examples]"
    python examples/rats/make_rats.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SHEETS_DIR = HERE / "sheets"
OUT = HERE / "assets"

SHEETS = ("general", "angry", "rire", "surprise")
"""Sheet file names. Each becomes a pose, because on these sheets the emotion
is drawn into the whole body — fists, folded arms, raised hands — and not into
a face that could be swapped over a common one."""

ART_BOTTOM = 857
"""Row where the artwork stops and the captions begin. The sheets agree on
this to within a couple of pixels; the gap below the feet is 20-odd rows."""

BANDS = ((0, 435), (435, 762), (762, 1140), (1140, 1536))
"""Vertical splits between the four characters, from the empty columns that
separate them on the sheets where nothing bridges the gap."""

INK_FLOOR = 90.0
"""Luminance treated as fully opaque graphite. Below it, alpha is already 1."""

WALL = 0.06
"""Graphite strength that stops the paper flood. Low enough that the faintest
pencil still walls the fill in, high enough that paper grain does not."""

GROUND_BAND = 0.02
"""How far above the lowest graphite still counts as standing on the ground, as
a fraction of the sheet height. Wide enough to span the antialiasing debris
under a shoe, narrow enough that a hand at the character's side is not ground."""

MAX_SCALE = 4.0
"""Largest upscale a sheet may be asked for. The four sheets draw the same
character to within a few percent, so a scale past this is a measurement that
went wrong — and acted on, it is a resize that exhausts memory rather than an
error anyone can read."""


@dataclass(frozen=True)
class Cast:
    """One character, and how tall it stands relative to the others."""

    name: str
    band: tuple[int, int]
    body_fraction: float
    """Height of the *body* as a fraction of the panel, at ``camera: medium``.
    Set from the heights the sheets actually draw, so the senior towers over
    the junior by the same margin on the page as on paper."""

    head_span: float = 0.26
    """Top share of the body that counts as head, for the face anchor."""

    mouth_drop: float = 0.11
    """How far below the head anchor the mouth sits, in head-span units."""

    mouth_shift: float = 0.0
    """Sideways nudge of the mouth, in body widths. Snouts point somewhere."""


CAST = (
    Cast("senior", BANDS[0], body_fraction=0.78, head_span=0.30, mouth_shift=0.10),
    Cast("scientist", BANDS[1], body_fraction=0.63, head_span=0.27),
    Cast("devops", BANDS[2], body_fraction=0.58, head_span=0.30),
    Cast("junior", BANDS[3], body_fraction=0.46, head_span=0.32),
)

MARGIN = 6
"""Breathing room around the union of every expression, in sheet pixels."""


# ---------------------------------------------------------------------------
# Reading a sheet
# ---------------------------------------------------------------------------


def read_sheet(name: str) -> tuple[Image.Image, np.ndarray]:
    """The artwork above the captions, and how hard the graphite presses."""
    rgb = Image.open(SHEETS_DIR / f"{name}.png").convert("RGB")
    rgb = rgb.crop((0, 0, rgb.width, ART_BOTTOM))
    lum = np.asarray(rgb.convert("L")).astype(np.float32)
    values, counts = np.unique(lum.astype(np.uint8), return_counts=True)
    paper = float(values[counts.argmax()])
    strength = np.clip((paper - lum) / (paper - INK_FLOOR), 0.0, 1.0)
    return rgb, strength


def flood(passable: np.ndarray, seeds: list[tuple[int, int]]) -> np.ndarray:
    """Everything reachable from ``seeds`` through ``passable``, 4-connected.

    Written out rather than taken from a library: ``ImageDraw.floodfill`` is a
    no-op on current Pillow, and SciPy would be a dependency the rest of this
    repository does not have. Runs are filled a scanline at a time, so the cost
    tracks the number of spans rather than the number of pixels.
    """
    height, width = passable.shape
    seen = np.zeros_like(passable)
    stack = [seed for seed in seeds if passable[seed]]
    while stack:
        y, x = stack.pop()
        if seen[y, x] or not passable[y, x]:
            continue
        row = passable[y]
        left = x
        while left > 0 and row[left - 1] and not seen[y, left - 1]:
            left -= 1
        right = x
        while right < width - 1 and row[right + 1] and not seen[y, right + 1]:
            right += 1
        seen[y, left : right + 1] = True
        for neighbour in (y - 1, y + 1):
            if not 0 <= neighbour < height:
                continue
            span = passable[neighbour, left : right + 1] & ~seen[neighbour, left : right + 1]
            hits = np.flatnonzero(span)
            if hits.size == 0:
                continue
            breaks = np.flatnonzero(np.diff(hits) > 1)
            for start in np.concatenate(([hits[0]], hits[breaks + 1])):
                stack.append((neighbour, left + int(start)))
    return seen


def opaque_mask(strength: np.ndarray) -> np.ndarray:
    """Which pixels belong to the drawing rather than to the paper."""
    height, width = strength.shape
    padded = np.zeros((height + 2, width + 2), bool)
    padded[1:-1, 1:-1] = strength <= WALL
    padded[0, :] = padded[-1, :] = padded[:, 0] = padded[:, -1] = True
    exterior = flood(padded, [(0, 0)])[1:-1, 1:-1]
    return ~exterior


def body_of(solid: np.ndarray) -> np.ndarray:
    """The character itself: the largest graphite standing on the ground.

    The lowest row of graphite is a shoe, but the lowest *pixel* is not a safe
    seed for it. Where the sole tapers out, antialiasing leaves specks that
    4-connectivity severs from the shoe above them — on the ``general`` sheet
    every character ends in exactly one such orphan pixel. Seeding there
    measures a body one pixel tall, and a one-pixel body asks the sheet to be
    scaled up several hundredfold, which is how this once tried to allocate a
    terabyte.

    So the ground is treated as a band rather than a line: every component
    reaching into it is walked, and the largest is the body. Everything that
    component cannot reach — bolts, steam, sparkles — is an effect, kept in the
    sprite but excluded from the measurement that sets the scale.
    """
    rows = np.flatnonzero(solid.any(axis=1))
    if rows.size == 0:
        raise ValueError("no graphite in this band: nothing to measure.")

    floor = int(rows[-1])
    ceiling = max(0, floor - max(1, round(solid.shape[0] * GROUND_BAND)))

    remaining = solid.copy()
    best: np.ndarray | None = None
    best_size = 0
    for y in range(floor, ceiling - 1, -1):
        for x in np.flatnonzero(remaining[y]):
            if not remaining[y, x]:  # already swallowed by an earlier component
                continue
            component = flood(remaining, [(y, int(x))])
            remaining &= ~component
            size = int(component.sum())
            if size > best_size:
                best, best_size = component, size

    if best is None:
        raise ValueError("no graphite reaches the ground: nothing to measure.")
    return best


def bounds(mask: np.ndarray) -> tuple[int, int, int, int]:
    rows = np.flatnonzero(mask.any(axis=1))
    columns = np.flatnonzero(mask.any(axis=0))
    return int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1


# ---------------------------------------------------------------------------
# Normalising one character across the sheets
# ---------------------------------------------------------------------------


@dataclass
class Measured:
    """One character on one sheet, measured and ready to be put in register."""

    sprite: Image.Image
    """Full band, paper already transparent."""

    body: tuple[int, int, int, int]
    content: tuple[int, int, int, int]
    """Body and everything-including-effects, in band coordinates."""


def measure(cast: Cast, sheet: str, rgb: Image.Image, strength: np.ndarray) -> Measured:
    left, right = cast.band
    band_strength = strength[:, left:right]
    solid = opaque_mask(band_strength)
    alpha = np.where(solid, 1.0, band_strength)
    pixels = np.asarray(rgb).astype(np.uint8)[:, left:right]
    sprite = Image.fromarray(
        np.dstack([pixels, (alpha * 255).round().astype(np.uint8)]), "RGBA"
    )
    return Measured(sprite=sprite, body=bounds(body_of(solid)), content=bounds(solid))


def build(cast: Cast, sheets: dict[str, tuple[Image.Image, np.ndarray]]) -> dict:
    """Put every expression of one character on a single shared canvas.

    The reference is the tallest body drawn for this character; the others are
    scaled up to match rather than down, so no sprite is ever resampled below
    the resolution it was drawn at.
    """
    measured = {name: measure(cast, name, *sheets[name]) for name in SHEETS}
    reference = max(m.body[3] - m.body[1] for m in measured.values())

    # Each expression maps its own body onto the reference body: same height,
    # feet on the same line, centred the same way.
    scales = {n: reference / (m.body[3] - m.body[1]) for n, m in measured.items()}

    # A scale is a measurement, and a measurement can be wrong. Say so here,
    # naming the sheet, rather than letting Pillow discover it as a failed
    # allocation several hundred gigabytes down the line.
    for name, scale in scales.items():
        if scale > MAX_SCALE:
            body = measured[name].body
            raise ValueError(
                f"{cast.name} measures {body[3] - body[1]}px tall on the "
                f"{name!r} sheet against a {reference}px reference, a x{scale:.0f} "
                f"upscale. That is a misread body, not a small drawing — check "
                f"the {cast.name} band {cast.band} on sheets/{name}.png."
            )
    anchors = {
        n: ((m.body[0] + m.body[2]) / 2, m.body[3]) for n, m in measured.items()
    }

    # How far the drawing reaches around that anchor, once scaled — the union
    # over expressions decides the canvas every sprite shares.
    spans = []
    for name, m in measured.items():
        scale, (ax, ay) = scales[name], anchors[name]
        x0, y0, x1, y1 = m.content
        spans.append(
            (
                (x0 - ax) * scale,
                (y0 - ay) * scale,
                (x1 - ax) * scale,
                (y1 - ay) * scale,
            )
        )
    span_left = min(s[0] for s in spans) - MARGIN
    span_top = min(s[1] for s in spans) - MARGIN
    span_right = max(s[2] for s in spans) + MARGIN
    # The feet are the anchor, so the canvas stops there: whatever ground
    # scribble hangs below would only push the character off its own baseline.
    width = int(round(span_right - span_left))
    height = int(round(-span_top))

    sprites = {}
    for name, m in measured.items():
        scale, (ax, ay) = scales[name], anchors[name]
        scaled = m.sprite.resize(
            (max(1, round(m.sprite.width * scale)), max(1, round(m.sprite.height * scale))),
            Image.LANCZOS,
        )
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.alpha_composite(
            scaled, (round(-span_left - ax * scale), round(-span_top - ay * scale))
        )
        sprites[name] = canvas

    # The body sits at a known place on that canvas, which is what lets the
    # manifest state a head anchor that is true for every expression.
    body_height = reference
    body_bottom = height
    body_top = height - body_height
    head_top = body_top
    head_height = cast.head_span * body_height
    head_y = head_top + head_height / 2

    return {
        "sprites": sprites,
        "size": (width, height),
        "body_height": body_height,
        "head": (-span_left, head_y),
        "head_height": head_height,
        "measured": measured,
        "scales": scales,
    }


def manifest_for(cast: Cast, built: dict) -> dict:
    """A manifest whose numbers come from the same measurements as the sprites.

    Coordinates are normalised to the sprite and y points up, so the head that
    sits near the top of the image is near 1.0 here.
    """
    width, height = built["size"]
    head_x, head_y = built["head"]
    head_height = built["head_height"]

    def point(x: float, y_down: float) -> list[float]:
        return [round(x / width, 4), round(1.0 - y_down / height, 4)]

    mouth_y = head_y + cast.mouth_drop * head_height
    poses = {}
    for sheet in SHEETS:
        poses[sheet] = {
            "head_anchor": point(head_x, head_y),
            "mouth_offset": point(head_x + cast.mouth_shift * width, mouth_y),
        }

    # default_height sizes the whole canvas, but what should read as "this
    # character's height" is the body inside it. Scale up by the headroom the
    # effects need so the body lands where the cast table asked.
    default_height = cast.body_fraction * height / built["body_height"]

    return {
        "name": cast.name,
        "anchor": "feet",
        "default_height": round(min(default_height, 1.0), 4),
        "flippable": True,
        "poses": poses,
        "expressions": [],
    }


# ---------------------------------------------------------------------------
# Backdrops
# ---------------------------------------------------------------------------
#
# The sheets are model sheets: four characters, no scenery. So unlike the cast,
# the two backgrounds are drawn here rather than cut, and the whole problem is
# not to draw well but to draw *faintly*. A backdrop competes with the sprites
# in front of it for the reader's attention, and these sprites are graphite on
# cream — a flat vector room behind them would win that competition and read as
# a collage of two different pictures.
#
# So: the paper the sheets were drawn on for the ground, one grey for what is
# near and a lighter one for what is far, thin strokes, nothing filled darker
# than the paper except where an object has to read as solid.

PAPER = (248, 244, 238, 255)
"""Sampled from the margins of the sheets, so the backdrop and the cutouts sit
on the same tone."""

NEAR = (104, 101, 98, 255)
FAR = (168, 165, 160, 255)
BACKDROP = (1200, 800)
BACK_SS = 3


class Pen:
    """A drawing surface that hides the supersampling."""

    def __init__(self, size: tuple[int, int], background=PAPER) -> None:
        self.size = size
        self.image = Image.new(
            "RGBA", (size[0] * BACK_SS, size[1] * BACK_SS), background
        )
        self.draw = ImageDraw.Draw(self.image)

    def _box(self, box):
        return tuple(value * BACK_SS for value in box)

    def rect(self, box, fill=None, outline=NEAR, width=3) -> None:
        self.draw.rectangle(self._box(box), fill=fill, outline=outline, width=width * BACK_SS)

    def rounded(self, box, radius, fill=None, outline=NEAR, width=3) -> None:
        self.draw.rounded_rectangle(
            self._box(box), radius=radius * BACK_SS, fill=fill, outline=outline,
            width=width * BACK_SS,
        )

    def line(self, points, fill=NEAR, width=3) -> None:
        self.draw.line(
            [(x * BACK_SS, y * BACK_SS) for x, y in points],
            fill=fill, width=width * BACK_SS, joint="curve",
        )

    def ellipse(self, box, fill=None, outline=NEAR, width=3) -> None:
        self.draw.ellipse(self._box(box), fill=fill, outline=outline, width=width * BACK_SS)

    def arc(self, box, start, end, fill=NEAR, width=3) -> None:
        self.draw.arc(self._box(box), start, end, fill=fill, width=width * BACK_SS)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.resize(self.size, Image.LANCZOS).save(path, optimize=True)


def office() -> Pen:
    """Where the strip happens: a window, a whiteboard, a desk, a plant."""
    pen = Pen(BACKDROP)
    floor = 600

    # The wall meets the floor here. Everything above is far, and drawn lighter.
    pen.line([(0, floor), (1200, floor)], fill=NEAR, width=3)

    pen.rounded((90, 140, 420, 400), radius=4, outline=FAR, width=4)
    pen.line([(255, 140), (255, 400)], fill=FAR, width=3)
    pen.line([(90, 270), (420, 270)], fill=FAR, width=3)

    # A whiteboard, and on it the only chart this office ever draws.
    pen.rect((640, 150, 1090, 400), fill=(252, 250, 246, 255), outline=FAR, width=4)
    pen.line(
        [(690, 220), (790, 300), (860, 250), (940, 340), (1040, 360)],
        fill=FAR, width=3,
    )
    pen.line([(690, 200), (690, 370)], fill=FAR, width=2)
    pen.line([(690, 370), (1050, 370)], fill=FAR, width=2)

    # A desk against the far wall, with a monitor asleep on it.
    pen.line([(700, 520), (1150, 520)], fill=NEAR, width=4)
    pen.line([(720, 520), (720, 600)], fill=NEAR, width=3)
    pen.line([(1130, 520), (1130, 600)], fill=NEAR, width=3)
    pen.rounded((860, 400, 1010, 500), radius=6, outline=NEAR, width=3)
    pen.line([(935, 500), (935, 520)], fill=NEAR, width=4)
    pen.line([(890, 520), (980, 520)], fill=NEAR, width=4)

    # A plant, because every office has exactly one and nobody waters it.
    # Below the window, never across it: a leaf crossing a mullion reads as a
    # mistake rather than as a plant.
    pen.line([(118, 600), (132, 528), (188, 528), (202, 600)], fill=NEAR, width=3)
    pen.line([(136, 544), (184, 544)], fill=NEAR, width=2)
    for tip, radius in (
        ((104, 476), (26, 17)),
        ((136, 442), (23, 15)),
        ((172, 436), (25, 16)),
        ((204, 466), (24, 16)),
        ((160, 490), (22, 14)),
    ):
        # The stem stops at the leaf rather than running through it.
        pen.line(
            [(160, 528), (160 + (tip[0] - 160) * 0.82, 528 + (tip[1] - 528) * 0.82)],
            fill=FAR,
            width=2,
        )
        pen.ellipse(
            (tip[0] - radius[0], tip[1] - radius[1], tip[0] + radius[0], tip[1] + radius[1]),
            outline=FAR,
            width=2,
        )

    _floor(pen, floor)
    return pen


def _floor(pen: Pen, horizon: int, vanishing_x: int = 600) -> None:
    """A few lines receding to a point, rather than a ruled grid.

    Evenly spaced horizontals read as lined paper, which is the one thing this
    backdrop must not look like: the cast is already drawn on paper, and the
    room has to sit behind them rather than beside them.
    """
    for edge_x in (-500, 150, 620, 1080, 1750):
        pen.line([(vanishing_x, horizon), (edge_x, pen.size[1])], fill=FAR, width=2)


def server_room() -> Pen:
    """Where the build server lives, and where the shouting comes from."""
    pen = Pen(BACKDROP)
    floor = 640

    pen.line([(0, floor), (1200, floor)], fill=NEAR, width=3)

    # Three racks, the middle one closer and so drawn darker.
    for left, top, ink in ((120, 230, FAR), (450, 190, NEAR), (800, 220, FAR)):
        width = 280
        pen.rect((left, top, left + width, floor), outline=ink, width=4)
        # Rack units, with a light on each. Regular, because a rack is regular
        # and the eye reads the repetition faster than it reads any detail.
        for row in range(top + 34, floor - 20, 44):
            pen.line([(left + 12, row), (left + width - 12, row)], fill=ink, width=2)
            pen.rect(
                (left + 22, row + 12, left + 34, row + 22), fill=ink, outline=ink, width=1
            )

    # A cable tray overhead, with what always hangs off it. Kept clear of the
    # racks: a cable crossing a rack front is a cable nobody can read.
    pen.line([(0, 60), (1200, 60)], fill=FAR, width=4)
    for x in range(70, 1200, 170):
        pen.arc((x, 60, x + 130, 150), 0, 180, fill=FAR, width=3)

    _floor(pen, floor)
    return pen


def main() -> None:
    sheets = {name: read_sheet(name) for name in SHEETS}
    for cast in CAST:
        built = build(cast, sheets)
        directory = OUT / "characters" / cast.name
        (directory / "body").mkdir(parents=True, exist_ok=True)
        for sheet, sprite in built["sprites"].items():
            sprite.save(directory / "body" / f"{sheet}.png", optimize=True)
        (directory / "character.yaml").write_text(
            yaml.safe_dump(manifest_for(cast, built), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        width, height = built["size"]
        scales = ", ".join(f"{n} x{s:.3f}" for n, s in built["scales"].items())
        print(f"{cast.name:<10} {width}x{height}  body {built['body_height']}px  [{scales}]")

    office().save(OUT / "backgrounds" / "office.png")
    server_room().save(OUT / "backgrounds" / "server-room.png")

    print(f"\nwrote the rat library to {OUT}")


if __name__ == "__main__":
    main()
