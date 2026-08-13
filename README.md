# InkPy

A Python engine for generating **short strips (4 panels maximum)** from a declarative description and a library of reusable assets.

InkPy does not write stories and does not draw characters. The author supplies the narrative, the assets and the composition; the engine assembles, lays out and exports — **deterministically and reproducibly**.

```
strip.yaml + assets/  →  InkPy  →  strip.png
```

---

## Quick start

```bash
pip install -e ".[dev]"

python examples/make_assets.py          # draw the example library
inkpy render examples/monday-morning.yaml -o out/monday.png
inkpy render examples/monday-morning.yaml -o out/wire.png --wireframe
```

Assets are looked for in `assets/` beside the strip file unless `--assets`
says otherwise.

### Smoke test

The shortest path from a fresh clone to a comic, and the thing to run when
something looks broken. One panel, one character, one bubble — four commands,
each of which should print exactly what is shown after it:

```bash
pip install -e ".[dev]"

python examples/hello/make_hello.py
# wrote the hello library to examples/hello/assets

inkpy check examples/hello/hello.yaml
# examples/hello/hello.yaml: 1 panels, 1 bubbles, 0 warnings

inkpy render examples/hello/hello.yaml -o out/hello.png
# out/hello.png (800x600, 1 panels)

inkpy verify examples/hello/hello.yaml out/hello.png
# out/hello.png matches examples/hello/hello.yaml.
```

Each step isolates a layer, so a failure says where the problem is: the
generator is Pillow only, `check` is parsing, validation and layout with no
renderer involved, `render` adds SVG and rasterisation, `verify` reads the
provenance back out of the PNG.

`tests/test_smoke.py` runs these same four steps against a library it draws in
a temporary directory — including a check that this section still lists them —
so the procedure cannot rot while the README goes on recommending it:

```bash
pytest tests/test_smoke.py
```

`examples/hello/hello.yaml` is also the smallest thing to copy when starting a
strip of your own.

| Command | |
|---|---|
| `inkpy render strip.yaml` | render to PNG (also `-f svg`, `-f pdf`) |
| `inkpy render … --wireframe` | overlay bounding boxes, anchors and reserved zones |
| `inkpy watch strip.yaml` | re-render on every save |
| `inkpy check strip.yaml` | validate and report layout warnings, write nothing |
| `inkpy verify strip.yaml out.png` | confirm a render still matches its sources |
| `inkpy assets list assets/` | what a library provides, ready to write against |
| `inkpy schema -o strip.schema.json` | JSON Schema, for editor autocompletion |
| `inkpy styles` | the style names a strip may use |

Four example strips: `hello/hello.yaml` (one panel, the smoke test below),
`monday-morning.yaml` (a four-panel strip), `bubble-types.yaml` (the four
bubble types), `effects.yaml` (frame weights and speed lines).

---

## Why

Generative image models produce beautiful isolated panels but fail at what actually makes a comic: keeping a character identical across panels, holding a consistent style, controlling composition, and reproducing exact dialogue.

InkPy inverts the problem. Characters are fixed assets, composition is written down, and rendering is a pure function of those inputs. Consistency isn't a property you hope to coax out of a model — it falls out of the architecture.

### Non-goals

Explicitly out of scope, to keep the engine small and reliable:

- generating artwork or scripts;
- long-form pages, pagination, or multi-page books;
- a bespoke scripting language (validated YAML is enough);
- transforming the render with generative AI (see "Rejected ideas").

---

## Design constraints

These constraints are the core of the project. Everything else follows from them.

| Constraint | Consequence |
|---|---|
| **4 panels maximum** | No general-purpose layout engine needed — a closed set of named templates suffices. |
| **Deterministic rendering** | Same input → same output, byte for byte. No sources of randomness, embedded fonts, hashed assets. |
| **Author-supplied assets** | The engine draws nothing; it composes, positions and dresses. |
| **Readable format** | A strip's source must stay editable in any text editor and versionable in Git. |

---

## Architecture

The essential step is the **intermediate representation (IR)** sitting between authorial intent and pixels. It's what makes the engine testable and the backends interchangeable.

```
strip.yaml
    │
    │  parse + validate        (Pydantic)
    ▼
ComicScript                    typed authorial intent
    │                          "cat, sitting, bored, on the left"
    │  layout engine
    ▼
Scene (IR)                     resolved geometry, in absolute pixels
    │                          rectangles, sprites, bubble polygons,
    │                          tails, pre-positioned text lines
    │  backend
    ▼
SVG  ──rasterize──►  PNG / PDF
```

**Why the IR changes everything:**

- **Testing** — you assert against a data structure ("no bubble covers a face", "bubbles follow reading order") instead of diffing images pixel by pixel, which is unmaintainable.
- **Backends** — SVG today, Pillow or Cairo later, without touching layout.
- **Debugging** — a `--wireframe` mode draws bounding boxes, anchors and reserved zones. Indispensable from day one.

### Composition order

Counter-intuitively, characters are **not** placed first:

```
1. Background
2. Reserve bubble space        ← computed BEFORE any placement
3. Place characters in the remaining space
4. Objects and effects
5. Render bubbles + text
6. Panel frame
```

Placing characters first guarantees that bubbles will end up covering their heads.

---

## Coordinate system

Specified once, applied everywhere.

- Origin: **bottom-left corner** of the panel.
- `y` axis points **up**.
- Coordinates normalized to `[0, 1]`, resolution-independent.
- A character's anchor point is **the ground under their feet** (`anchor: feet`), not the sprite's center — the only way to align characters on a shared horizon line.
- Depth is explicit via `z` (higher = closer to the reader). Never inferred from `y`.

---

## Asset library

### Organization

```
assets/
├── characters/
│   └── cat/
│       ├── character.yaml
│       ├── body/
│       │   ├── idle.png
│       │   ├── sitting.png
│       │   └── walking.png
│       └── face/
│           ├── neutral.png
│           ├── bored.png
│           └── angry.png
├── objects/
│   ├── sofa.png
│   └── mug.png
└── backgrounds/
    ├── kitchen.png
    └── garden.png
```

### Layered compositing

A character is not a flat sprite. Separating **body** (pose) from **face** (expression) avoids the cartesian product: 3 poses × 4 expressions needs 7 files, not 12. The face is pinned to an anchor point declared by the body.

### Character manifest

Every character declares its own geometry. Without this file the engine can neither place a face nor aim a speech-bubble tail.

```yaml
# assets/characters/cat/character.yaml
name: cat
anchor: feet                 # reference point for body sprites
default_height: 0.45         # fraction of panel height, at camera: medium
flippable: true              # horizontal mirroring allowed

poses:
  idle:
    head_anchor:  [0.50, 0.78]   # where to pin the face (body sprite space)
    mouth_offset: [0.55, 0.74]   # target for the bubble tail
  sitting:
    head_anchor:  [0.48, 0.66]
    mouth_offset: [0.53, 0.62]

expressions: [neutral, bored, angry, happy]
```

At load time the engine validates that every referenced pose exists both as a file **and** as metadata, and raises an explicit error otherwise.

---

## Strip format

### Full example

```yaml
comic:
  title: "Monday Morning"
  page:
    width: 1200
    height: 900
    gutter: 16          # space between panels
    margin: 24          # page margin
  layout: "2x2"
  style: "default"      # font, frame weight, bubble style

  panels:
    - id: 1
      background: kitchen
      camera: medium              # wide | medium | close → sprite scale
      actors:
        - character: cat
          pose: sitting
          expression: bored
          at: [0.30, 0.10]        # anchored at the feet, origin bottom-left
          z: 1
          flip: false
        - character: human
          pose: idle
          expression: happy
          at: [0.70, 0.12]
          z: 0
          flip: true              # faces left, toward the cat
      objects:
        - name: mug
          at: [0.55, 0.30]
          scale: 0.4
          z: 2
      dialogue:
        - speaker: human
          text: "Are you finally awake?"
          type: speech
        - speaker: cat
          text: "I am awake. Unfortunately."
          type: thought
```

### Field reference

**`page`** — dimensions in pixels, gutters and margins. One page per file.

**`layout`** — a named template from a closed set:

| Template | Arrangement |
|---|---|
| `1x1` | single full-page panel |
| `2x1` | two panels side by side |
| `1x2` | two panels stacked |
| `4x1` | classic horizontal strip |
| `2x2` | grid |
| `1+2` | one wide panel on top, two below |
| `2+1` | two panels on top, one wide below |

**`camera`** — `wide` / `medium` / `close`. Derives character scale from `default_height` instead of making the author tune numbers by hand. `scale` remains available as a per-actor override.

**`actors[].flip`** — horizontal mirror. Lets two characters face each other from a single set of sprites.

**`dialogue[].type`** — `speech` (round bubble, pointed tail), `thought` (cloud bubble, bubble-trail tail), `shout` (spiked outline, one spike stretched into the tail), `narration` (rectangular caption, no tail, pinned to a corner).

**`frame`** — `none` / `thin` / `normal` / `bold`. A multiplier on the style's border weight; `none` lets the panel bleed into the page.

**`effects`** — a list of drawn flourishes. Only `speed_lines` so far, since it is the one effect whose entire content is a direction:

```yaml
effects:
  - type: speed_lines
    at: [0.62, 0.35]      # where the movement is heading
    direction: right      # left | right | up | down
    length: 0.5           # fraction of the panel, along the direction
    spread: 0.42          # fraction of the panel, across it
    count: 9
    z: 0
```

The lines trail *back* from `at`, which is the convention: they record where the thing has been.

**Dialogue order is reading order.** The engine places bubbles so their visual order (top→bottom, left→right) matches the array order. When that's geometrically impossible given the requested positions, it emits a warning rather than silently producing an unreadable panel.

---

## Bubble layout

This is the trickiest piece of the project and the main driver of perceived quality.

1. **Measure** — every line is measured with the final font, via `fontTools`, never estimated. SVG provides no text metrics, so the same face that measures a line also draws it: text is emitted as glyph outlines, not as `<text>`. Nothing downstream gets to substitute a font.
2. **Break lines into an oval** — a comic bubble wants a rounded silhouette: short lines at the top and bottom, longer ones in the middle. Plain fixed-width wrapping yields a rectangle, which instantly gives away the automated render — and costs area, because the ellipse around a rectangle is √2 larger on *both* axes. Each line therefore gets its own measure, taken from the ellipse's width at that line's height, and the words are distributed by a small paragraph-breaker rather than greedily. Several line counts are tried and the one with the smallest bubble wins; adding a line often shrinks the bubble, which a fixed-width wrapper can never discover.
3. **Reserve** — bubbles claim the upper band of the panel (~35% of its height by default) *before* anything is placed. The share is a floor, not a ceiling: when the dialogue needs more it takes more.
4. **Place** — respecting reading order, each bubble as close as possible to its speaker. Two bubbles share a row only when their speakers read left-to-right in the same order as the dialogue; otherwise they stack, so no two tails cross.
5. **Resolve collisions** — strategies in order, cheapest first: shift horizontally, narrow the bubble (making it taller), lift the block into whatever slack the band has, and only as a last resort drop the font one step within the style's limits. A bubble that exhausts all four says so instead of sitting on a face.
6. **Draw the tail** — a Bézier from the bubble edge to the speaker's `mouth_offset`, accounting for `flip`. Bubble and tail are emitted as one closed path: an ellipse drawn *over* a separate tail leaves its own outline running across the tail's neck, which is exactly how a machine-made bubble announces itself. A shout needs no special case — its tail is one of its own spikes, drawn longer.

---

## Repository layout

```
inkpy/
├── inkpy/
│   ├── model/            # Pydantic schemas: ComicScript, Panel, Actor, Dialogue
│   ├── assets/           # loading, manifests, cache, hashing
│   ├── layout/
│   │   ├── page.py       # templates → panel rectangles
│   │   ├── actors.py     # anchoring, scaling, z-sorting
│   │   ├── bubbles.py    # measuring, wrapping, placement, collisions
│   │   └── scene.py      # IR definition
│   ├── render/
│   │   ├── svg.py        # IR → SVG
│   │   ├── raster.py     # SVG → PNG/PDF
│   │   └── wireframe.py  # debug render
│   ├── styles/           # themes: fonts, frames, bubble shapes
│   └── cli.py
├── examples/
├── tests/
│   ├── test_layout/      # assertions on the IR
│   └── test_render/      # a handful of golden cases only
└── docs/
```

---

## Testing

- **Layout is tested against the IR**, not against images: "no bubble covers a `head_anchor`", "bubbles are in reading order", "every actor is inside its panel bounds", "z-sorting is stable".
- **Render tests are few and deliberate**: two or three golden pages, compared with tolerance. One render test per feature is a maintenance trap.
- **Validation errors are tested for their message.** `Character 'cat' has no pose 'flying'. Available poses: idle, sitting, walking.` beats a `KeyError`.
- **One end-to-end smoke test** (`tests/test_smoke.py`) runs the four-command procedure from *Quick start* for real — generator, `check`, `render`, `verify` — over a library it draws in a temporary directory. It is the only test that never skips for want of assets, and the only one whose job is to fail when the *instructions* stop being true.

---

## Reproducibility

The "same input → same output" promise has to be verifiable, not merely asserted:

- fonts embedded in the package, never resolved from the system;
- no sources of randomness in layout;
- iteration over ordered collections only;
- every input written into the PNG's metadata: the engine version, the style, a hash of the sprites used, and a hash of the strip itself;
- an `inkpy verify strip.yaml out.png` command that recomputes all four from the sources and compares.

The strip's hash is taken from the validated script rather than from the
file's bytes, so it answers the question worth asking. A reworded line, a
moved actor, a different bubble type move it; a comment, a rearranged mapping
or a default spelled out in full do not. A fingerprint that went off on those
would only teach people to ignore it.

`--style` is part of it because it is part of the render: an image made with
`-s compact` does not match the strip as written, and `verify` says so and
names the flag that would make the check meaningful.

---

## Assets and licensing

Assets are supplied by the author and remain their responsibility. Examples shipped in this repository use only original characters or freely licensed assets — no copyrighted characters, not even for demonstration. The example library is not committed as artwork at all: `examples/make_assets.py` draws it, so what is under review is the code that produces the sprites rather than a pile of unreviewable PNGs.

Three generators draw the libraries the examples render against, and none of what they produce is committed:

| Generator | Library |
|---|---|
| `python examples/hello/make_hello.py` | one character, for the smoke test |
| `python examples/make_assets.py` | the cat and the human of `monday-morning.yaml` |
| `python examples/rats/make_rats.py` | four characters cut out of the pencil sheets in `examples/rats/sheets/`, which *are* committed — they are the source the script works from |

The generators are not part of the engine, but they are run from this repository, so they are installable from it: `pip install -e ".[examples]"`. Only the last one needs it — it measures the sheets with numpy, so that every expression of a character lands at exactly the same size.

The one asset InkPy itself ships is a font. Reproducibility requires it: a face resolved from the system would make the same strip render differently on two machines. `inkpy/styles/fonts/` contains DejaVu Sans with its license (`LICENSE.txt`, Bitstream Vera).

---

## Stack

| Need | Choice |
|---|---|
| Schema and validation | Pydantic v2 (also gives JSON Schema export for free) |
| Text metrics | Pillow / fontTools |
| Vector rendering | SVG emitted directly (lxml) |
| Rasterization | cairosvg or resvg |
| CLI | Typer |

SVG over Pillow for rendering: bubbles, Bézier tails and text are far simpler to produce in vector form, and PDF export comes almost for free.

---

## Roadmap

### v0.1 — A strip comes out ✅

**Single exit criterion: a 4-panel YAML file produces a legible PNG.** Met —
`examples/monday-morning.yaml` is that file, and `tests/test_cli.py` asserts it.

- [x] Pydantic schema for the strip format
- [x] Asset loading + character manifests
- [x] Layout templates
- [x] Body + face compositing, feet anchoring, `flip`, `z`-sorting
- [x] Bubbles: measuring, wrapping, placement, tail
- [x] `Scene` IR and SVG → PNG backend
- [x] `--wireframe` mode
- [x] Explicit validation error messages

Three decisions were taken during the build that the spec above did not
anticipate, and that are worth recording:

**The reserved band is a floor, not a fixed share.** `bubble_band` says how
much of a panel bubbles get by default; when the dialogue needs more, it takes
more, and characters shrink accordingly. Holding it as a hard limit would only
have meant bubbles quietly spilling over the artwork. Reservation runs in two
passes — place characters against the nominal band to find the speakers'
mouths, measure the dialogue, then reserve for real.

**Bubbles whose speakers stand in the wrong order are stacked, not placed side
by side.** If the right-hand character speaks first, a single row would force
the first bubble left and the second right, running both tails across each
other. Stacking keeps each bubble over its own speaker and makes reading order
top-to-bottom, which is unambiguous. This is the case the "emit a warning"
note in *Strip format* was written for; there turned out to be a better answer
than warning.

**Text is embedded as outlines, not as `<text>`.** Fonts ship inside the
package, and the glyphs are emitted as paths built from those fonts, so no
renderer anywhere gets to choose a substitute. It is what makes "same input,
same output" true off the machine that rendered it.

### v0.2 — Render quality ✅

- [x] Bubble collision resolution
- [x] Oval line breaking
- [x] Bubble types: thought, shout, narration caption
- [x] Simple effects: speed lines, variable frame weight
- [x] PDF export
- [x] Style / theme system

Oval breaking turned out to be a packing win as well as a cosmetic one: it cuts
7–23% off a bubble's area on the example strip, because the corners a rectangle
of text wastes are corners the panel was paying for.

It also forced a correction upstream. Reserving a full-width band and shrinking
every character under it punished a character standing beneath a *gap* between
two bubbles. The reservation now converges instead: place the cast against the
nominal band to find their mouths, lay the bubbles out, then re-place the cast
against the bubbles' own rectangles. A character only ever yields to the space
above itself.

The one place the IR could have lied is worth recording. A thought bubble's
scallops bulge outward, so drawing them naively would put ink outside the
rectangle the layout engine reserved — and every assertion made against that
rectangle would have been wrong by exactly that margin. Instead the bubble is
inflated by the scallop depth in layout, and the renderer draws the peaks out to
the edge. The IR stays the truth about the page.

### v0.3 — Authoring comfort ✅

- [x] `inkpy watch`: re-render on save
- [x] JSON Schema export for editor autocompletion
- [x] Asset library inspection (`inkpy assets list`)
- [x] Reproducibility verification

`watch` polls modification times rather than subscribing to filesystem events:
one fewer dependency, and imperceptible at this scale. It does not stop on an
error, because a half-finished edit is the normal state of a file being watched.

The JSON Schema is derived from the Pydantic models, not maintained alongside
them, so an editor's autocompletion cannot drift from what the engine accepts.

### Rejected ideas

Recorded here so they don't get rediscovered in six months:

- **A dedicated language (DSL)** — YAML + Pydantic already fills that role. Writing a language parser costs weeks and buys no new capability.
- **Plugin system, community asset sharing** — features for a project with hundreds of users, not a nascent engine.
- **Generative AI enhancement layer** — directly contradicts the value proposition: the project exists to deliver consistency and reproducibility, and style transfer reintroduces exactly the variability we're trying to eliminate. Possibly one day as external, opt-in post-processing; never in the pipeline.

---

## License

To be defined.
