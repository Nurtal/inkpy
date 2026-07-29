# InkPy

A Python engine for generating **short strips (4 panels maximum)** from a declarative description and a library of reusable assets.

InkPy does not write stories and does not draw characters. The author supplies the narrative, the assets and the composition; the engine assembles, lays out and exports — **deterministically and reproducibly**.

```
strip.yaml + assets/  →  InkPy  →  strip.png
```

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

**`dialogue[].type`** — `speech` (round bubble, pointed tail), `thought` (cloud bubble, bubble-trail tail), `shout` (spiked outline), `narration` (rectangular caption, no tail, pinned to a corner).

**Dialogue order is reading order.** The engine places bubbles so their visual order (top→bottom, left→right) matches the array order. When that's geometrically impossible given the requested positions, it emits a warning rather than silently producing an unreadable panel.

---

## Bubble layout

This is the trickiest piece of the project and the main driver of perceived quality. Target algorithm for v0.1:

1. **Measure** — every line is measured with the final font (`PIL.ImageFont.getbbox()` or `fontTools`), never estimated. SVG provides no text metrics: measure upfront, then emit explicitly positioned `<tspan>` elements rather than depending on the viewer's rendering engine.
2. **Break lines into an oval** — a comic bubble wants a rounded silhouette: short lines at the top and bottom, longer ones in the middle. Plain fixed-width wrapping yields a rectangle, which instantly gives away the automated render.
3. **Reserve** — bubbles occupy the upper band of the panel by default (~35% of its height). That zone is subtracted from the available space before characters are placed.
4. **Place** — respecting reading order, each bubble as close as possible to its speaker.
5. **Resolve collisions** — bubble/bubble, bubble/face, bubble/panel edge. Strategies in order: shift horizontally, narrow the bubble (making it taller), move up, and only as a last resort drop the font one step within the style's limits.
6. **Draw the tail** — a Bézier curve from the bubble edge to the speaker's `mouth_offset`, accounting for `flip`.

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

---

## Reproducibility

The "same input → same output" promise has to be verifiable, not merely asserted:

- fonts embedded in the package, never resolved from the system;
- no sources of randomness in layout;
- iteration over ordered collections only;
- asset hashes and the InkPy version written into PNG/PDF metadata;
- an `inkpy verify strip.yaml out.png` command that recomputes and compares the hash.

---

## Assets and licensing

Assets are supplied by the author and remain their responsibility. Examples shipped in this repository use only original characters or freely licensed assets — no copyrighted characters, not even for demonstration.

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

### v0.1 — A strip comes out

**Single exit criterion: a 4-panel YAML file produces a legible PNG.**

- [ ] Pydantic schema for the strip format
- [ ] Asset loading + character manifests
- [ ] Layout templates
- [ ] Body + face compositing, feet anchoring, `flip`, `z`-sorting
- [ ] Bubbles: measuring, wrapping, placement, tail
- [ ] `Scene` IR and SVG → PNG backend
- [ ] `--wireframe` mode
- [ ] Explicit validation error messages

### v0.2 — Render quality

- [ ] Bubble collision resolution
- [ ] Oval line breaking
- [ ] Bubble types: thought, shout, narration caption
- [ ] Simple effects: speed lines, variable frame weight
- [ ] PDF export
- [ ] Style / theme system

### v0.3 — Authoring comfort

- [ ] `inkpy watch`: re-render on save
- [ ] JSON Schema export for editor autocompletion
- [ ] Asset library inspection (`inkpy assets list`)
- [ ] Reproducibility verification

### Rejected ideas

Recorded here so they don't get rediscovered in six months:

- **A dedicated language (DSL)** — YAML + Pydantic already fills that role. Writing a language parser costs weeks and buys no new capability.
- **Plugin system, community asset sharing** — features for a project with hundreds of users, not a nascent engine.
- **Generative AI enhancement layer** — directly contradicts the value proposition: the project exists to deliver consistency and reproducibility, and style transfer reintroduces exactly the variability we're trying to eliminate. Possibly one day as external, opt-in post-processing; never in the pipeline.

---

## License

To be defined.
