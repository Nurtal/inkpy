"""The command line, including the shipped example.

The last test in this file is the v0.1 exit criterion, stated as an assertion:
a four-panel YAML file produces a legible PNG.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from typer.testing import CliRunner

from inkpy.cli import app
from inkpy.render.raster import read_provenance

runner = CliRunner()

EXAMPLES = Path(__file__).parent.parent / "examples"

STRIP = """
comic:
  title: "Two panels"
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
def project(tmp_path: Path, library_root: Path) -> Path:
    """A strip file with its asset library beside it, as authors lay it out.

    In its own directory, because ``library_root`` already occupies
    ``tmp_path/assets`` and the point here is the *default* lookup.
    """
    home = tmp_path / "strip"
    home.mkdir()
    shutil.copytree(library_root, home / "assets")
    strip = home / "strip.yaml"
    strip.write_text(textwrap.dedent(STRIP), encoding="utf-8")
    return strip


def run(*args: str):
    return runner.invoke(app, list(args))


class TestRender:
    def test_a_strip_becomes_a_png(self, project, tmp_path):
        result = run("render", str(project), "-o", str(tmp_path / "out.png"))
        assert result.exit_code == 0, result.output
        with Image.open(tmp_path / "out.png") as image:
            assert image.size == (400, 300)

    def test_the_output_path_defaults_to_the_strips_name(self, project):
        assert run("render", str(project)).exit_code == 0
        assert project.with_suffix(".png").is_file()

    def test_assets_are_found_beside_the_strip(self, project):
        """No --assets flag anywhere above: the default convention is used."""
        result = run("render", str(project))
        assert result.exit_code == 0

    def test_an_explicit_asset_library(self, project, library_root, tmp_path):
        result = run(
            "render", str(project), "-a", str(library_root), "-o", str(tmp_path / "o.png")
        )
        assert result.exit_code == 0

    def test_svg_and_pdf_formats(self, project, tmp_path):
        for fmt, magic in (("svg", b"<?xml"), ("pdf", b"%PDF")):
            out = tmp_path / f"out.{fmt}"
            assert run("render", str(project), "-f", fmt, "-o", str(out)).exit_code == 0
            assert out.read_bytes().startswith(magic)

    def test_scale(self, project, tmp_path):
        run("render", str(project), "--scale", "2", "-o", str(tmp_path / "big.png"))
        with Image.open(tmp_path / "big.png") as image:
            assert image.size == (800, 600)

    def test_wireframe(self, project, tmp_path):
        plain = tmp_path / "plain.svg"
        wire = tmp_path / "wire.svg"
        run("render", str(project), "-f", "svg", "-o", str(plain))
        run("render", str(project), "-f", "svg", "--wireframe", "-o", str(wire))
        assert 'class="wireframe"' not in plain.read_text()
        assert 'class="wireframe"' in wire.read_text()

    def test_style_override(self, project, tmp_path):
        result = run(
            "render", str(project), "-s", "compact", "-o", str(tmp_path / "c.png")
        )
        assert result.exit_code == 0

    def test_an_unknown_style_is_refused_by_name(self, project, tmp_path):
        result = run("render", str(project), "-s", "neon", "-o", str(tmp_path / "x.png"))
        assert result.exit_code == 1
        assert "Unknown style 'neon'" in result.output


class TestErrorsAreReadable:
    def test_a_missing_strip(self, tmp_path):
        result = run("render", str(tmp_path / "nope.yaml"))
        assert result.exit_code == 1
        assert "strip file not found" in result.output
        assert "Traceback" not in result.output

    def test_a_missing_asset_library(self, tmp_path):
        strip = tmp_path / "strip.yaml"
        strip.write_text(textwrap.dedent(STRIP), encoding="utf-8")
        result = run("render", str(strip))
        assert result.exit_code == 1
        assert "asset library not found" in result.output

    def test_a_typo_in_the_strip(self, project):
        project.write_text(
            textwrap.dedent(STRIP).replace("expression: bored", "expresion: bored"),
            encoding="utf-8",
        )
        result = run("render", str(project))
        assert result.exit_code == 1
        assert "unknown field" in result.output
        assert "Traceback" not in result.output

    def test_a_missing_pose(self, project):
        project.write_text(
            textwrap.dedent(STRIP).replace("pose: sitting", "pose: flying"),
            encoding="utf-8",
        )
        result = run("render", str(project))
        assert result.exit_code == 1
        assert "has no pose 'flying'" in result.output


class TestCheck:
    def test_check_validates_without_writing(self, project):
        result = run("check", str(project))
        assert result.exit_code == 0
        assert "2 panels" in result.output
        assert not project.with_suffix(".png").exists()

    def test_check_reports_problems(self, project):
        project.write_text(
            textwrap.dedent(STRIP).replace("background: garden", "background: attic"),
            encoding="utf-8",
        )
        result = run("check", str(project))
        assert result.exit_code == 1
        assert "unknown background 'attic'" in result.output


class TestVerify:
    def test_a_fresh_render_verifies(self, project, tmp_path):
        out = tmp_path / "out.png"
        run("render", str(project), "-o", str(out))
        result = run("verify", str(project), str(out))
        assert result.exit_code == 0, result.output
        assert "matches" in result.output

    def test_a_changed_asset_fails_verification(self, project, tmp_path):
        from tests.conftest import write_sprite

        out = tmp_path / "out.png"
        run("render", str(project), "-o", str(out))
        write_sprite(project.parent / "assets" / "backgrounds" / "garden.png", (1200, 900), "#000")
        result = run("verify", str(project), str(out))
        assert result.exit_code == 1
        assert "assets differ" in result.output

    def test_a_reworded_line_fails_verification(self, project, tmp_path):
        """The check the assets hash cannot make: same artwork, other words."""
        out = tmp_path / "out.png"
        run("render", str(project), "-o", str(out))
        project.write_text(
            textwrap.dedent(STRIP).replace('"Mm."', '"Mm. Indeed."'), encoding="utf-8"
        )
        result = run("verify", str(project), str(out))
        assert result.exit_code == 1
        assert "the strip differs" in result.output

    def test_a_moved_actor_fails_verification(self, project, tmp_path):
        out = tmp_path / "out.png"
        run("render", str(project), "-o", str(out))
        project.write_text(
            textwrap.dedent(STRIP).replace("at: [0.35, 0.08]", "at: [0.65, 0.08]"),
            encoding="utf-8",
        )
        result = run("verify", str(project), str(out))
        assert result.exit_code == 1
        assert "the strip differs" in result.output

    def test_a_retitled_strip_says_so_in_those_words(self, project, tmp_path):
        """A title change is a strip change, reported as the specific one."""
        out = tmp_path / "out.png"
        run("render", str(project), "-o", str(out))
        project.write_text(
            textwrap.dedent(STRIP).replace("Two panels", "Two panels, revised"),
            encoding="utf-8",
        )
        result = run("verify", str(project), str(out))
        assert result.exit_code == 1
        assert "title differs" in result.output
        assert "the strip differs" not in result.output

    def test_editing_a_comment_still_verifies(self, project, tmp_path):
        """The fingerprint is of the strip's meaning, not of its bytes."""
        out = tmp_path / "out.png"
        run("render", str(project), "-o", str(out))
        project.write_text(
            "# rendered before this comment existed\n" + textwrap.dedent(STRIP),
            encoding="utf-8",
        )
        result = run("verify", str(project), str(out))
        assert result.exit_code == 0, result.output

    def test_a_render_in_another_style_is_not_a_match(self, project, tmp_path):
        """Same strip, same assets, different pixels: verify has to notice."""
        out = tmp_path / "compact.png"
        run("render", str(project), "-s", "compact", "-o", str(out))
        result = run("verify", str(project), str(out))
        assert result.exit_code == 1
        assert "style differs" in result.output
        assert "--style compact" in result.output

    def test_the_style_it_was_rendered_with_verifies(self, project, tmp_path):
        out = tmp_path / "compact.png"
        run("render", str(project), "-s", "compact", "-o", str(out))
        result = run("verify", str(project), str(out), "-s", "compact")
        assert result.exit_code == 0, result.output

    def test_an_image_without_a_script_hash_cannot_be_checked(self, project, tmp_path):
        """A render from before the strip was fingerprinted: say so, don't pass it."""
        out = tmp_path / "out.png"
        run("render", str(project), "-o", str(out))
        stripped = tmp_path / "old.png"
        info = PngImagePlugin.PngInfo()
        for key, value in read_provenance(out).items():
            if key != "inkpy:script":
                info.add_text(key, value)
        with Image.open(out) as image:
            image.save(stripped, format="PNG", pnginfo=info)

        result = run("verify", str(project), str(stripped))
        assert result.exit_code == 1
        assert "records no hash of the strip" in result.output

    def test_a_foreign_png_is_reported_as_such(self, project, tmp_path):
        alien = tmp_path / "alien.png"
        Image.new("RGB", (4, 4), "red").save(alien)
        result = run("verify", str(project), str(alien))
        assert result.exit_code == 1
        assert "carries no InkPy provenance" in result.output


class TestVersion:
    def test_version(self):
        result = run("version")
        assert result.exit_code == 0 and result.output.startswith("inkpy ")


@pytest.mark.skipif(
    not (EXAMPLES / "assets" / "characters").is_dir(),
    reason="run 'python examples/make_assets.py' first",
)
class TestTheShippedExample:
    """v0.1's single exit criterion: a four-panel YAML file gives a legible PNG."""

    def test_it_renders(self, tmp_path):
        out = tmp_path / "monday.png"
        result = run("render", str(EXAMPLES / "monday-morning.yaml"), "-o", str(out))
        assert result.exit_code == 0, result.output
        with Image.open(out) as image:
            assert image.size == (1400, 1000)

    def test_it_has_four_panels_and_eight_bubbles(self, tmp_path):
        result = run("check", str(EXAMPLES / "monday-morning.yaml"))
        assert result.exit_code == 0
        assert "4 panels, 8 bubbles" in result.output

    def test_it_is_reproducible(self, tmp_path):
        strip = EXAMPLES / "monday-morning.yaml"
        first = tmp_path / "a.png"
        second = tmp_path / "b.png"
        run("render", str(strip), "-o", str(first))
        run("render", str(strip), "-o", str(second))
        assert first.read_bytes() == second.read_bytes()

    def test_the_render_verifies_against_its_sources(self, tmp_path):
        strip = EXAMPLES / "monday-morning.yaml"
        out = tmp_path / "monday.png"
        run("render", str(strip), "-o", str(out))
        assert read_provenance(out)["inkpy:title"] == "Monday Morning"
        assert run("verify", str(strip), str(out)).exit_code == 0


@pytest.mark.skipif(
    not (EXAMPLES / "rats" / "assets").is_dir(),
    reason="run 'python examples/rats/make_rats.py' first",
)
class TestTheRatStrip:
    """The other cast: sprites cut from drawn sheets, not generated by a script.

    Worth its own case because the library differs in kind. These characters
    have no face layer — the sheets were drawn one emotion at a time, so the
    expression is in the pose — and the library ships no backgrounds at all.
    """

    def test_it_renders_cleanly(self):
        result = run("check", str(EXAMPLES / "rats" / "same-seed.yaml"))
        assert result.exit_code == 0, result.output
        assert "4 panels, 7 bubbles, 0 warnings" in result.output

    def test_it_produces_a_page(self, tmp_path):
        out = tmp_path / "same-seed.png"
        result = run("render", str(EXAMPLES / "rats" / "same-seed.yaml"), "-o", str(out))
        assert result.exit_code == 0, result.output
        with Image.open(out) as image:
            assert image.size == (1400, 1000)

    def test_the_render_verifies_against_its_sources(self, tmp_path):
        strip = EXAMPLES / "rats" / "same-seed.yaml"
        out = tmp_path / "same-seed.png"
        run("render", str(strip), "-o", str(out))
        assert run("verify", str(strip), str(out)).exit_code == 0


class TestSchemaExport:
    def test_schema_goes_to_stdout(self):
        import json

        result = run("schema")
        assert result.exit_code == 0
        document = json.loads(result.output)
        assert document["required"] == ["comic"]
        assert "panels" in document["properties"]["comic"]["properties"]

    def test_schema_describes_the_closed_vocabularies(self):
        import json

        document = json.loads(run("schema").output)
        layouts = document["properties"]["comic"]["$defs"]["Layout"]["enum"]
        assert set(layouts) == {"1x1", "2x1", "1x2", "4x1", "2x2", "1+2", "2+1"}

    def test_schema_can_be_written_to_a_file(self, tmp_path):
        out = tmp_path / "nested" / "strip.schema.json"
        assert run("schema", "-o", str(out)).exit_code == 0
        assert out.read_text().startswith("{")

    def test_the_schema_tracks_the_models(self):
        """Derived, not maintained: a new field appears without being listed."""
        import json

        document = json.loads(run("schema").output)
        panel = document["properties"]["comic"]["$defs"]["Panel"]["properties"]
        assert {"frame", "effects", "dialogue", "actors"} <= set(panel)


class TestAssetsList:
    def test_it_reports_what_a_library_provides(self, library_root):
        result = run("assets", "list", str(library_root))
        assert result.exit_code == 0
        assert "character cat" in result.output
        assert "poses:       idle, sitting" in result.output
        assert "expressions: bored, neutral" in result.output
        assert "backgrounds: garden, kitchen" in result.output

    def test_it_reports_the_fingerprint(self, library_root):
        result = run("assets", "list", str(library_root))
        assert "fingerprint:" in result.output

    def test_a_missing_library_is_refused_readably(self, tmp_path):
        result = run("assets", "list", str(tmp_path / "nope"))
        assert result.exit_code == 1
        assert "asset library not found" in result.output
        assert "Traceback" not in result.output


class TestStyles:
    def test_it_lists_the_names_a_strip_may_use(self):
        result = run("styles")
        assert result.exit_code == 0
        assert result.output.split() == ["compact", "default"]


class TestWatch:
    def test_a_first_pass_renders_immediately(self, project, tmp_path, monkeypatch):
        """The loop is driven one tick at a time, so the test never hangs."""
        import inkpy.cli as cli

        ticks = {"n": 0}

        def one_tick(_seconds):
            ticks["n"] += 1
            raise KeyboardInterrupt

        monkeypatch.setattr(cli.time, "sleep", one_tick)
        out = tmp_path / "watched.png"
        result = run("watch", str(project), "-o", str(out))
        assert result.exit_code == 0
        assert ticks["n"] == 1
        assert out.is_file()
        assert "watching" in result.output and "wrote" in result.output

    def test_an_error_does_not_stop_the_watch(self, project, tmp_path, monkeypatch):
        import inkpy.cli as cli

        project.write_text("comic: {}\n", encoding="utf-8")
        monkeypatch.setattr(
            cli.time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt)
        )
        result = run("watch", str(project), "-o", str(tmp_path / "x.png"))
        assert result.exit_code == 0
        assert "required field is missing" in result.output
        assert "stopped" in result.output

    def test_a_second_tick_without_changes_does_not_re_render(
        self, project, tmp_path, monkeypatch
    ):
        import inkpy.cli as cli

        ticks = {"n": 0}

        def two_ticks(_seconds):
            ticks["n"] += 1
            if ticks["n"] >= 2:
                raise KeyboardInterrupt

        monkeypatch.setattr(cli.time, "sleep", two_ticks)
        result = run("watch", str(project), "-o", str(tmp_path / "w.png"))
        assert result.output.count("wrote") == 1

    def test_an_edit_triggers_a_re_render(self, project, tmp_path, monkeypatch):
        import inkpy.cli as cli

        ticks = {"n": 0}

        def edit_then_stop(_seconds):
            ticks["n"] += 1
            if ticks["n"] == 1:
                text = project.read_text()
                project.write_text(text.replace('"Mm."', '"Mm. Indeed."'))
            else:
                raise KeyboardInterrupt

        monkeypatch.setattr(cli.time, "sleep", edit_then_stop)
        result = run("watch", str(project), "-o", str(tmp_path / "w.png"))
        assert result.output.count("wrote") == 2
