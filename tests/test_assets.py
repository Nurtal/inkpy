"""Asset loading, manifest validation, and the messages both produce."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from inkpy.assets import AssetLibrary, check_script, load_manifest
from inkpy.errors import AssetError
from inkpy.model import parse_script
from tests.conftest import CAT_MANIFEST, write_manifest, write_sprite

SCRIPT = """
comic:
  title: t
  page: {width: 1200, height: 900}
  layout: "1x1"
  panels:
    - id: 1
      background: kitchen
      actors:
        - {character: cat, pose: sitting, expression: bored, at: [0.3, 0.1]}
      objects:
        - {name: mug, at: [0.55, 0.3]}
"""


def script(text: str = SCRIPT):
    return parse_script(textwrap.dedent(text), source="strip.yaml")


class TestLoading:
    def test_library_indexes_everything(self, library: AssetLibrary):
        assert sorted(library.characters) == ["cat", "human"]
        assert sorted(library.objects) == ["mug"]
        assert sorted(library.backgrounds) == ["garden", "kitchen"]

    def test_sprite_dimensions_are_read(self, library: AssetLibrary):
        sitting = library.character("cat").body("sitting")
        assert (sitting.width, sitting.height) == (140, 160)
        assert sitting.aspect == pytest.approx(140 / 160)

    def test_manifest_geometry_is_available(self, library: AssetLibrary):
        spec = library.character("cat").pose_spec("idle")
        assert spec.head.as_tuple() == (0.50, 0.78)
        assert spec.mouth.as_tuple() == (0.55, 0.74)
        assert spec.face_scale == 1.0

    def test_missing_library(self, tmp_path: Path):
        with pytest.raises(AssetError, match="is not a directory"):
            AssetLibrary.load(tmp_path / "nope")

    def test_missing_subdirectories_are_tolerated(self, tmp_path: Path):
        (tmp_path / "assets").mkdir()
        library = AssetLibrary.load(tmp_path / "assets")
        assert library.characters == {} and library.backgrounds == {}


class TestLookupErrors:
    def test_unknown_pose_names_the_alternatives(self, library: AssetLibrary):
        with pytest.raises(AssetError) as exc:
            library.character("cat").body("flying")
        assert str(exc.value) == (
            "Character 'cat' has no pose 'flying'. Available: idle, sitting."
        )

    def test_close_name_gets_a_suggestion(self, library: AssetLibrary):
        with pytest.raises(AssetError, match="Did you mean 'sitting'"):
            library.character("cat").body("sit")

    def test_unknown_character(self, library: AssetLibrary):
        with pytest.raises(AssetError, match="Unknown character 'dog'"):
            library.character("dog")

    def test_unknown_expression(self, library: AssetLibrary):
        with pytest.raises(AssetError, match="has no expression 'furious'"):
            library.character("cat").face("furious")


class TestManifestConsistency:
    def test_pose_declared_without_a_file(self, library_root: Path, tmp_path: Path):
        (library_root / "characters" / "cat" / "body" / "sitting.png").unlink()
        with pytest.raises(AssetError) as exc:
            AssetLibrary.load(library_root)
        assert "declares pose(s) sitting with no matching file" in str(exc.value)
        assert "body/sitting.png" in str(exc.value).replace("\\", "/")

    def test_file_without_a_declaration(self, library_root: Path):
        write_sprite(
            library_root / "characters" / "cat" / "body" / "flying.png", (10, 10), "red"
        )
        with pytest.raises(AssetError) as exc:
            AssetLibrary.load(library_root)
        assert "pose file(s) flying that the manifest does not declare" in str(exc.value)
        assert "Declared: idle, sitting." in str(exc.value)

    def test_directory_name_must_match_manifest_name(self, library_root: Path):
        manifest = dict(CAT_MANIFEST, name="feline")
        write_manifest(library_root / "characters" / "cat", manifest)
        with pytest.raises(AssetError, match="declares name 'feline'"):
            AssetLibrary.load(library_root)

    def test_missing_manifest(self, library_root: Path):
        (library_root / "characters" / "cat" / "character.yaml").unlink()
        with pytest.raises(AssetError, match="character manifest not found"):
            AssetLibrary.load(library_root)

    def test_manifest_needs_at_least_one_pose(self, tmp_path: Path):
        write_manifest(tmp_path / "cat", {"name": "cat", "poses": {}})
        with pytest.raises(AssetError, match="not a valid character manifest"):
            load_manifest(tmp_path / "cat" / "character.yaml")

    def test_non_png_sprite_is_rejected(self, library_root: Path):
        (library_root / "characters" / "cat" / "body" / "idle.jpg").write_bytes(b"x")
        with pytest.raises(AssetError, match="Sprites must be PNG"):
            AssetLibrary.load(library_root)

    def test_faceless_character_needs_no_face_directory(self, tmp_path: Path):
        root = tmp_path / "assets"
        write_manifest(
            root / "characters" / "rock",
            {
                "name": "rock",
                "poses": {"idle": {"head_anchor": [0.5, 0.9], "mouth_offset": [0.5, 0.8]}},
            },
        )
        write_sprite(root / "characters" / "rock" / "body" / "idle.png", (40, 40), "grey")
        library = AssetLibrary.load(root)
        assert library.character("rock").face("neutral") is None


class TestScriptCrossCheck:
    def test_valid_script_passes(self, library: AssetLibrary):
        check_script(script(), library)

    def test_every_problem_is_reported_at_once(self, library: AssetLibrary):
        broken = SCRIPT.replace("background: kitchen", "background: bathroom")
        broken = broken.replace("pose: sitting", "pose: flying")
        broken = broken.replace("name: mug", "name: teapot")
        with pytest.raises(AssetError) as exc:
            check_script(script(broken), library)
        message = str(exc.value)
        assert "3 missing or inapplicable assets" in message
        assert "unknown background 'bathroom'" in message
        assert "has no pose 'flying'" in message
        assert "unknown object 'teapot'" in message

    def test_problems_are_prefixed_by_panel(self, library: AssetLibrary):
        with pytest.raises(AssetError, match=r"panel 1: unknown character 'dog'"):
            check_script(script(SCRIPT.replace("character: cat", "character: dog")), library)

    def test_flip_on_a_non_flippable_character(self, library_root: Path):
        write_manifest(
            library_root / "characters" / "cat", dict(CAT_MANIFEST, flippable=False)
        )
        library = AssetLibrary.load(library_root)
        with pytest.raises(AssetError, match="is not flippable"):
            check_script(script(SCRIPT.replace("at: [0.3, 0.1]", "at: [0.3, 0.1], flip: true")), library)


class TestReproducibility:
    def test_fingerprint_is_stable(self, library_root: Path):
        first = AssetLibrary.load(library_root).fingerprint()
        second = AssetLibrary.load(library_root).fingerprint()
        assert first == second

    def test_fingerprint_tracks_content(self, library_root: Path):
        before = AssetLibrary.load(library_root).fingerprint()
        write_sprite(
            library_root / "characters" / "cat" / "face" / "bored.png", (48, 48), "#000000"
        )
        assert AssetLibrary.load(library_root).fingerprint() != before
