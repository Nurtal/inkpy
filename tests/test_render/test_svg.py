"""The SVG backend.

Deliberately not a pixel diff. What matters about this backend is structural:
it must be well-formed, it must depend on nothing outside itself, and it must
produce the same bytes twice. Those are all things you can ask of a string.

One golden document is checked in — a strip with no sprites at all, so the file
stays small enough to review in a diff, which is the only thing that makes a
golden test worth keeping.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
from lxml import etree

from inkpy.layout.compose import build_scene
from inkpy.model import parse_script
from inkpy.render.svg import SvgOptions, render_svg

GOLDEN = Path(__file__).parent / "golden" / "captions.svg"

SPRITELESS = """
comic:
  title: "Captions only"
  page: {width: 400, height: 300, gutter: 12, margin: 16}
  layout: "1x2"
  panels:
    - id: 1
      dialogue:
        - {text: "A room, in the morning.", type: narration}
    - id: 2
      dialogue:
        - {text: "The same room, later.", type: narration}
"""

WITH_ART = """
comic:
  title: t
  page: {width: 600, height: 400}
  layout: "1x1"
  panels:
    - id: 1
      background: kitchen
      actors:
        - {character: cat, pose: sitting, expression: bored, at: [0.3, 0.08]}
        - {character: human, at: [0.75, 0.08], flip: true}
      objects:
        - {name: mug, at: [0.55, 0.2]}
      dialogue:
        - {speaker: cat, text: "Mm."}
"""


def svg_of(source: str, library, **options) -> str:
    scene = build_scene(parse_script(textwrap.dedent(source)), library)
    return render_svg(scene, SvgOptions(**options))


class TestWellFormed:
    def test_output_parses(self, library):
        root = etree.fromstring(svg_of(WITH_ART, library).encode("utf-8"))
        assert root.tag == "{http://www.w3.org/2000/svg}svg"

    def test_canvas_matches_the_page(self, library):
        root = etree.fromstring(svg_of(WITH_ART, library).encode("utf-8"))
        assert root.get("width") == "600" and root.get("height") == "400"
        assert root.get("viewBox") == "0 0 600 400"

    def test_one_group_per_panel(self, library):
        svg = svg_of(SPRITELESS, library)
        assert svg.count('id="panel-1"') == 1
        assert svg.count('id="panel-2"') == 1

    def test_each_panel_is_clipped(self, library):
        svg = svg_of(WITH_ART, library)
        assert 'clipPath id="panel-1-clip"' in svg
        assert 'clip-path="url(#panel-1-clip)"' in svg


class TestSelfContained:
    def test_text_is_never_left_as_text(self, library):
        """The whole point: a viewer gets no say in which font to substitute."""
        svg = svg_of(WITH_ART, library)
        assert "<text" not in svg
        assert "font-family" not in svg

    def test_dialogue_survives_as_outlines(self, library):
        svg = svg_of(WITH_ART, library)
        # "Mm." never appears as characters, but its glyphs are drawn.
        assert "Mm." not in svg
        assert svg.count("<path") > 1

    def test_sprites_are_embedded(self, library):
        svg = svg_of(WITH_ART, library)
        assert "data:image/png;base64," in svg
        assert "file://" not in svg

    def test_sprites_can_be_left_on_disk(self, library):
        svg = svg_of(WITH_ART, library, embed_assets=False)
        assert "data:image/png;base64," not in svg
        assert "file://" in svg

    def test_no_external_reference_of_any_kind(self, library):
        svg = svg_of(WITH_ART, library)
        remote = re.findall(r'(?:href|src)="(?!data:)([^"]*)"', svg)
        assert remote == []


class TestGeometry:
    def test_the_document_is_flipped_once(self, library):
        """One y-flip for the page, so no coordinate is converted by hand."""
        svg = svg_of(SPRITELESS, library)
        assert svg.count("scale(1,-1)") >= 1
        assert 'transform="translate(0,300) scale(1,-1)"' in svg

    def test_images_are_counter_flipped(self, library):
        """An image in a flipped frame would otherwise render upside down."""
        svg = svg_of(WITH_ART, library)
        assert re.search(r'translate\([\d.]+,[\d.]+\) scale\(1,-1\)"><image', svg)

    def test_a_mirrored_sprite_is_mirrored_in_the_transform(self, library):
        svg = svg_of(WITH_ART, library)
        assert "scale(-1,-1)" in svg

    def test_a_bubble_and_its_tail_are_one_path(self, library):
        """Two shapes would leave the bubble's outline crossing the tail."""
        svg = svg_of(WITH_ART, library)
        outlines = re.findall(r'<path class="bubble [^"]*" d="([^"]*)"', svg)
        assert len(outlines) == 1
        assert outlines[0].count("Q") == 2  # one curve out to the tip, one back

    def test_a_narration_caption_is_a_rectangle_without_a_tail(self, library):
        svg = svg_of(SPRITELESS, library)
        outlines = re.findall(r'<path class="bubble ([^"]*)" d="([^"]*)"', svg)
        assert [kind for kind, _ in outlines] == ["narration", "narration"]
        assert all("Q" not in data for _, data in outlines)


class TestProvenance:
    def test_the_render_records_what_made_it(self, library):
        svg = svg_of(WITH_ART, library)
        assert "<metadata>" in svg
        assert 'version="0.1.0.dev0"' in svg
        assert re.search(r'assets="[0-9a-f]{64}"', svg)


class TestWireframe:
    def test_off_by_default(self, library):
        assert 'class="wireframe"' not in svg_of(WITH_ART, library)

    def test_the_overlay_draws_the_marks_the_ir_carries(self, library):
        svg = svg_of(WITH_ART, library, wireframe=True)
        assert 'class="wireframe"' in svg
        assert "stroke-dasharray" in svg

    def test_bare_mode_drops_the_artwork(self, library):
        svg = svg_of(WITH_ART, library, wireframe=True, artwork=False)
        assert "data:image/png;base64," not in svg
        assert 'class="wireframe"' in svg

    def test_the_wireframe_never_needs_a_system_font(self, library):
        svg = svg_of(WITH_ART, library, wireframe=True)
        assert "<text" not in svg


class TestDeterminism:
    def test_the_same_scene_serialises_identically(self, library):
        assert svg_of(WITH_ART, library) == svg_of(WITH_ART, library)

    def test_numbers_are_written_at_fixed_precision(self, library):
        svg = svg_of(WITH_ART, library)
        long_decimals = re.findall(r"\d+\.\d{4,}", svg)
        assert long_decimals == []


class TestGolden:
    def test_matches_the_checked_in_document(self, library):
        produced = svg_of(SPRITELESS, library)
        expected = GOLDEN.read_text(encoding="utf-8")
        if produced != expected:
            failed = GOLDEN.with_name("captions.actual.svg")
            failed.write_text(produced, encoding="utf-8")
            pytest.fail(
                f"render differs from the golden document.\n"
                f"  expected: {GOLDEN}\n"
                f"  actual:   {failed}\n"
                f"If the change is intended, copy the actual over the golden "
                f"and review the diff."
            )


class TestEffectsAndFrames:
    """The backend transcribes effects; it does not decide anything about them."""

    WITH_EFFECT = """
    comic:
      title: t
      page: {width: 600, height: 400}
      layout: "1x1"
      panels:
        - id: 1
          frame: bold
          effects:
            - {type: speed_lines, at: [0.5, 0.5], count: 5}
    """

    NO_FRAME = WITH_EFFECT.replace("frame: bold", "frame: none")

    def test_speed_lines_become_one_path(self, library):
        svg = svg_of(self.WITH_EFFECT, library)
        paths = re.findall(r'<path class="effect speed_lines" d="([^"]*)"', svg)
        assert len(paths) == 1
        assert paths[0].count("M") == 5

    def test_a_bold_frame_is_drawn_heavier_than_a_normal_one(self, library):
        def frame_width(source: str) -> float:
            svg = svg_of(source, library)
            widths = re.findall(r'stroke-width="([\d.]+)"', svg)
            return max(float(width) for width in widths)

        bold = frame_width(self.WITH_EFFECT)
        normal = frame_width(self.WITH_EFFECT.replace("frame: bold", "frame: normal"))
        assert bold > normal

    def test_frame_none_emits_no_border(self, library):
        """Not a zero-width stroke — no stroked rectangle at all."""
        framed = re.findall(
            r'<rect [^>]*fill="none" stroke=', svg_of(self.WITH_EFFECT, library)
        )
        bare = re.findall(
            r'<rect [^>]*fill="none" stroke=', svg_of(self.NO_FRAME, library)
        )
        assert len(framed) == 1
        assert bare == []

    def test_a_thought_bubble_is_a_closed_cloud_with_puffs(self, library):
        svg = svg_of(
            """
            comic:
              title: t
              page: {width: 600, height: 400}
              layout: "1x1"
              panels:
                - id: 1
                  actors: [{character: cat, at: [0.5, 0.05]}]
                  dialogue: [{speaker: cat, text: "Hmm.", type: thought}]
            """,
            library,
        )
        assert svg.count('class="puff"') == 3
        outline = re.search(r'<path class="bubble thought" d="([^"]*)"', svg).group(1)
        assert "Q" not in outline  # a cloud has no tail attached to it
        assert outline.endswith("Z")

    def test_a_shout_tail_is_one_of_its_own_spikes(self, library):
        svg = svg_of(
            """
            comic:
              title: t
              page: {width: 600, height: 400}
              layout: "1x1"
              panels:
                - id: 1
                  actors: [{character: cat, at: [0.5, 0.05]}]
                  dialogue: [{speaker: cat, text: "HEY!", type: shout}]
            """,
            library,
        )
        outline = re.search(r'<path class="bubble shout" d="([^"]*)"', svg).group(1)
        # One unbroken polygon: no curve commands, and 22 vertices.
        assert "Q" not in outline
        assert outline.count("L") == 21
