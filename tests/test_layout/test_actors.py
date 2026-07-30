"""Actor placement: anchoring, scaling, compositing, mirroring, z-order."""

from __future__ import annotations

import textwrap

import pytest

from inkpy.assets import AssetLibrary
from inkpy.geometry import Rect
from inkpy.layout.actors import MIN_SHRINK, place_panel_contents
from inkpy.layout.scene import DrawKind
from inkpy.model import parse_script
from tests.conftest import CAT_MANIFEST, write_manifest

PANEL = Rect(100.0, 200.0, 400.0, 300.0)


def panel_of(body: str):
    """Wrap a panel body in the smallest valid strip file.

    ``- id: 1`` puts the panel's keys at column 6, so the body is re-indented
    to match rather than relying on the caller's source indentation.
    """
    keys = textwrap.indent(textwrap.dedent(body).strip("\n"), " " * 6)
    script = parse_script(
        "comic:\n"
        "  title: t\n"
        "  page: {width: 1200, height: 900}\n"
        '  layout: "1x1"\n'
        "  panels:\n"
        "    - id: 1\n"
        f"{keys}\n"
    )
    return script.panels[0]


def place(body: str, library: AssetLibrary, rect: Rect = PANEL, reserved=()):
    return place_panel_contents(panel_of(body), rect, library, reserved)


class TestAnchoring:
    def test_feet_land_exactly_on_the_requested_point(self, library):
        result = place("actors: [{character: cat, at: [0.25, 0.10]}]", library)
        body = result.actors[0].rect
        assert body.bottom == pytest.approx(PANEL.bottom + 0.10 * PANEL.height)
        assert body.center.x == pytest.approx(PANEL.left + 0.25 * PANEL.width)

    def test_characters_of_different_heights_share_a_horizon(self, library):
        result = place(
            """
            actors:
              - {character: cat, at: [0.3, 0.12]}
              - {character: human, at: [0.7, 0.12]}
            """,
            library,
        )
        cat, human = result.actors
        assert cat.rect.bottom == pytest.approx(human.rect.bottom)
        assert human.rect.height > cat.rect.height


class TestScaling:
    def test_height_comes_from_the_manifest_at_medium(self, library):
        result = place("actors: [{character: cat, at: [0.5, 0.0]}]", library)
        assert result.actors[0].rect.height == pytest.approx(0.45 * PANEL.height)

    def test_camera_multiplies_the_manifest_height(self, library):
        wide = place("camera: wide\nactors: [{character: cat, at: [0.5, 0.0]}]", library)
        close = place("camera: close\nactors: [{character: cat, at: [0.5, 0.0]}]", library)
        assert wide.actors[0].rect.height < close.actors[0].rect.height

    def test_explicit_scale_replaces_the_camera_factor(self, library):
        result = place(
            "camera: close\nactors: [{character: cat, at: [0.5, 0.0], scale: 1.0}]",
            library,
        )
        assert result.actors[0].rect.height == pytest.approx(0.45 * PANEL.height)

    def test_aspect_ratio_is_preserved(self, library):
        result = place("actors: [{character: cat, pose: sitting, at: [0.5, 0.0]}]", library)
        body = result.actors[0].rect
        assert body.width / body.height == pytest.approx(140 / 160)


class TestFaceCompositing:
    def test_face_is_pinned_to_the_head_anchor(self, library):
        result = place("actors: [{character: cat, at: [0.5, 0.0]}]", library)
        actor = result.actors[0]
        expected = actor.rect.from_local(library.character("cat").pose_spec("idle").head)
        assert actor.head.as_tuple() == pytest.approx(expected.as_tuple())
        assert actor.face is not None
        assert actor.face.rect.center.as_tuple() == pytest.approx(expected.as_tuple())

    def test_face_rides_at_the_body_scale(self, library):
        result = place("actors: [{character: cat, at: [0.5, 0.0]}]", library)
        actor = result.actors[0]
        body_scale = actor.rect.height / 200  # cat/idle.png is 200px tall
        assert actor.face.rect.height == pytest.approx(48 * body_scale)

    def test_face_is_drawn_in_front_of_its_own_body(self, library):
        result = place(
            """
            actors:
              - {character: cat, at: [0.3, 0.0], z: 5}
              - {character: human, at: [0.7, 0.0], z: 5}
            """,
            library,
        )
        kinds = [(d.label, d.kind) for d in result.draws]
        assert kinds == [
            ("cat/idle", DrawKind.BODY),
            ("cat/neutral", DrawKind.FACE),
            ("human/idle", DrawKind.BODY),
            ("human/neutral", DrawKind.FACE),
        ]

    def test_expression_selects_the_face_sprite(self, library):
        result = place(
            "actors: [{character: cat, expression: bored, at: [0.5, 0.0]}]", library
        )
        assert result.actors[0].face.sprite.name == "bored"

    def test_faceless_character_has_no_face_draw(self, tmp_path, library_root):
        write_manifest(
            library_root / "characters" / "cat",
            {k: v for k, v in CAT_MANIFEST.items() if k != "expressions"},
        )
        for stale in (library_root / "characters" / "cat" / "face").iterdir():
            stale.unlink()
        library = AssetLibrary.load(library_root)
        result = place("actors: [{character: cat, at: [0.5, 0.0]}]", library)
        assert result.actors[0].face is None
        assert len(result.draws) == 1


class TestFlip:
    def test_flip_mirrors_the_anchors(self, library):
        straight = place("actors: [{character: cat, at: [0.5, 0.0]}]", library).actors[0]
        flipped = place(
            "actors: [{character: cat, at: [0.5, 0.0], flip: true}]", library
        ).actors[0]
        assert straight.rect == flipped.rect
        # head_anchor x is 0.50 for cat/idle, so mirroring barely moves it;
        # mouth_offset at 0.55 must land symmetrically on the other side.
        centre = straight.rect.center.x
        assert flipped.mouth.x - centre == pytest.approx(centre - straight.mouth.x)
        assert flipped.mouth.y == pytest.approx(straight.mouth.y)

    def test_flip_flag_reaches_the_sprites(self, library):
        result = place("actors: [{character: cat, at: [0.5, 0.0], flip: true}]", library)
        assert all(draw.flip for draw in result.draws)

    def test_two_characters_can_face_each_other(self, library):
        result = place(
            """
            actors:
              - {character: cat, at: [0.25, 0.0]}
              - {character: human, at: [0.75, 0.0], flip: true}
            """,
            library,
        )
        cat, human = result.actors
        # The cat's mouth leans right, the flipped human's leans left: they
        # face across the panel rather than both looking the same way.
        assert cat.mouth.x > cat.rect.center.x
        assert human.mouth.x < human.rect.center.x


class TestDepth:
    def test_higher_z_is_drawn_later(self, library):
        result = place(
            """
            actors:
              - {character: cat, at: [0.3, 0.0], z: 3}
              - {character: human, at: [0.7, 0.0], z: 1}
            """,
            library,
        )
        assert [d.label for d in result.draws][0].startswith("human")

    def test_z_ties_keep_file_order(self, library):
        result = place(
            """
            actors:
              - {character: human, at: [0.7, 0.0]}
              - {character: cat, at: [0.3, 0.0]}
            """,
            library,
        )
        assert result.draws[0].label.startswith("human")

    def test_depth_is_never_inferred_from_y(self, library):
        """A character standing higher up is not automatically behind."""
        result = place(
            """
            actors:
              - {character: cat, at: [0.3, 0.5], z: 9}
              - {character: human, at: [0.7, 0.0], z: 0}
            """,
            library,
        )
        assert result.draws[-1].label.startswith("cat")

    def test_objects_sort_with_actors(self, library):
        result = place(
            """
            actors: [{character: cat, at: [0.3, 0.0], z: 1}]
            objects: [{name: mug, at: [0.5, 0.2], z: 0}]
            """,
            library,
        )
        assert result.draws[0].kind is DrawKind.OBJECT

    def test_sorting_is_deterministic(self, library):
        body = """
        actors:
          - {character: cat, at: [0.3, 0.0]}
          - {character: human, at: [0.7, 0.0]}
        objects: [{name: mug, at: [0.5, 0.2]}]
        """
        first = [d.label for d in place(body, library).draws]
        second = [d.label for d in place(body, library).draws]
        assert first == second


class TestBubbleBand:
    def test_without_a_band_a_character_keeps_its_full_height(self, library):
        result = place("actors: [{character: human, at: [0.5, 0.0]}]", library)
        assert result.actors[0].rect.height == pytest.approx(0.70 * PANEL.height)

    def test_a_character_shrinks_to_clear_the_band(self, library):
        band = Rect(PANEL.x, PANEL.top - 0.35 * PANEL.height, PANEL.width, 0.35 * PANEL.height)
        result = place(
            "actors: [{character: human, at: [0.5, 0.0]}]", library, reserved=(band,)
        )
        assert result.actors[0].rect.top <= band.bottom + 1e-9
        assert "was scaled to" in result.warnings[0]

    def test_shrinking_stops_at_the_floor_and_warns(self, library):
        band = Rect(PANEL.x, PANEL.bottom + 0.2 * PANEL.height, PANEL.width, 0.8 * PANEL.height)
        result = place(
            "actors: [{character: human, at: [0.5, 0.0]}]", library, reserved=(band,)
        )
        nominal = 0.70 * PANEL.height
        assert result.actors[0].rect.height == pytest.approx(nominal * MIN_SHRINK)
        assert any("even at its minimum size" in w for w in result.warnings)

    def test_the_band_is_recorded_as_a_mark(self, library):
        band = Rect(PANEL.x, PANEL.top - 50, PANEL.width, 50)
        result = place("actors: []", library, reserved=(band,))
        assert result.marks[0].kind == "band" and result.marks[0].rect == band


class TestMarksAndWarnings:
    def test_every_actor_contributes_debug_marks(self, library):
        result = place("actors: [{character: cat, at: [0.5, 0.0]}]", library)
        kinds = {mark.kind for mark in result.marks}
        assert kinds == {"actor", "head", "mouth", "feet"}

    def test_actor_outside_the_panel_warns(self, library):
        result = place("actors: [{character: cat, at: [1.0, 1.0]}]", library)
        assert any("entirely outside the panel" in w for w in result.warnings)

    def test_a_normal_panel_produces_no_warnings(self, library):
        result = place(
            """
            actors:
              - {character: cat, at: [0.3, 0.1]}
              - {character: human, at: [0.7, 0.1]}
            """,
            library,
        )
        assert result.warnings == ()


class TestObjects:
    def test_object_scale_is_relative_to_the_panel(self, library):
        small = place("objects: [{name: mug, at: [0.5, 0.2], scale: 0.4}]", library)
        big = place("objects: [{name: mug, at: [0.5, 0.2], scale: 0.8}]", library)
        assert big.draws[0].rect.height == pytest.approx(2 * small.draws[0].rect.height)

    def test_object_is_anchored_at_its_base(self, library):
        result = place("objects: [{name: mug, at: [0.5, 0.25]}]", library)
        assert result.draws[0].rect.bottom == pytest.approx(PANEL.bottom + 0.25 * PANEL.height)
