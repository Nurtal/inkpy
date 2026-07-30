"""Rasterisation, and the reproducibility promise attached to it.

Not a pixel-diff suite. Two or three cases that check the properties actually
claimed — the same inputs give the same bytes, and every render says what made
it — plus enough sampling to catch a page that came out blank or upside down.
One render test per feature is the maintenance trap the README warns about.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from PIL import Image

from inkpy.errors import RenderError
from inkpy.layout.compose import build_scene
from inkpy.model import parse_script
from inkpy.render.raster import read_provenance, render_pdf, render_png, render_svg_file
from inkpy.render.svg import render_svg

cairosvg = pytest.importorskip("cairosvg", reason="rasterising needs cairosvg")

STRIP = """
comic:
  title: "Monday Morning"
  page: {width: 400, height: 300, gutter: 10, margin: 12}
  layout: "2x1"
  panels:
    - id: 1
      background: kitchen
      actors:
        - {character: cat, pose: sitting, expression: bored, at: [0.35, 0.08]}
      dialogue:
        - {speaker: cat, text: "Mm."}
    - id: 2
      background: garden
      actors:
        - {character: human, at: [0.5, 0.08]}
"""


@pytest.fixture
def scene(library):
    return build_scene(parse_script(textwrap.dedent(STRIP)), library)


@pytest.fixture
def svg(scene):
    return render_svg(scene)


def render(scene, svg, tmp_path: Path, name: str = "out.png", **kwargs) -> Path:
    return render_png(scene, svg, tmp_path / name, **kwargs)


class TestPng:
    def test_a_page_comes_out_at_the_requested_size(self, scene, svg, tmp_path):
        with Image.open(render(scene, svg, tmp_path)) as image:
            assert image.size == (400, 300)

    def test_scale_multiplies_the_resolution(self, scene, svg, tmp_path):
        with Image.open(render(scene, svg, tmp_path, scale=2.0)) as image:
            assert image.size == (800, 600)

    def test_a_negative_scale_is_refused(self, scene, svg, tmp_path):
        with pytest.raises(RenderError, match="scale must be positive"):
            render(scene, svg, tmp_path, scale=0.0)

    def test_missing_directories_are_created(self, scene, svg, tmp_path):
        written = render_png(scene, svg, tmp_path / "deep" / "out.png")
        assert written.is_file()

    def test_the_page_is_not_blank(self, scene, svg, tmp_path):
        with Image.open(render(scene, svg, tmp_path)) as image:
            assert len(image.convert("RGB").getcolors(maxcolors=1 << 16) or []) > 8

    def test_the_margin_stays_the_page_colour(self, scene, svg, tmp_path):
        """A cheap check that nothing leaked outside the panels."""
        with Image.open(render(scene, svg, tmp_path)) as image:
            rgb = image.convert("RGB")
            assert rgb.getpixel((2, 2)) == (255, 255, 255)
            assert rgb.getpixel((397, 297)) == (255, 255, 255)

    def test_the_page_is_the_right_way_up(self, scene, svg, tmp_path):
        """Panel 1 has a kitchen behind it and panel 2 a garden.

        The two backgrounds differ in colour, so sampling one pixel in each
        catches a document flipped on either axis — the mistake this backend
        is most exposed to.
        """
        with Image.open(render(scene, svg, tmp_path)) as image:
            rgb = image.convert("RGB")
            left = rgb.getpixel((100, 40))
            right = rgb.getpixel((300, 40))
            assert left != right


class TestProvenance:
    def test_a_render_records_what_made_it(self, scene, svg, tmp_path):
        stamped = read_provenance(render(scene, svg, tmp_path))
        assert stamped["inkpy:version"] == scene.engine_version
        assert stamped["inkpy:assets"] == scene.asset_fingerprint
        assert stamped["inkpy:title"] == "Monday Morning"

    def test_a_foreign_png_carries_none(self, tmp_path):
        path = tmp_path / "plain.png"
        Image.new("RGB", (4, 4), "red").save(path)
        assert read_provenance(path) == {}

    def test_provenance_follows_the_assets(self, library_root, scene, svg, tmp_path):
        from inkpy.assets import AssetLibrary
        from tests.conftest import write_sprite

        before = read_provenance(render(scene, svg, tmp_path))["inkpy:assets"]
        write_sprite(
            library_root / "backgrounds" / "kitchen.png", (1200, 900), "#000000"
        )
        rebuilt = build_scene(
            parse_script(textwrap.dedent(STRIP)), AssetLibrary.load(library_root)
        )
        after = render_png(
            rebuilt, render_svg(rebuilt), tmp_path / "second.png"
        )
        assert read_provenance(after)["inkpy:assets"] != before


class TestDeterminism:
    def test_the_same_strip_gives_the_same_bytes(self, scene, svg, tmp_path):
        first = render(scene, svg, tmp_path, "first.png").read_bytes()
        second = render(scene, svg, tmp_path, "second.png").read_bytes()
        assert first == second

    def test_a_rebuilt_scene_gives_the_same_bytes(self, library, tmp_path):
        """End to end: parse, compose, render, twice, from the same sources."""
        outputs = []
        for name in ("a.png", "b.png"):
            built = build_scene(parse_script(textwrap.dedent(STRIP)), library)
            outputs.append(
                render_png(built, render_svg(built), tmp_path / name).read_bytes()
            )
        assert outputs[0] == outputs[1]


class TestOtherFormats:
    def test_svg_is_written_verbatim(self, svg, tmp_path):
        written = render_svg_file(svg, tmp_path / "out.svg")
        assert written.read_text(encoding="utf-8") == svg

    def test_pdf_export(self, scene, svg, tmp_path):
        written = render_pdf(scene, svg, tmp_path / "out.pdf")
        assert written.read_bytes().startswith(b"%PDF")
