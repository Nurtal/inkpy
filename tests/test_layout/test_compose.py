"""The composer, and the invariants that must hold for any strip.

These are the assertions the README names as the reason for having an IR. They
are written against whole scenes rather than single panels, because that is
where an ordering mistake actually shows up.
"""

from __future__ import annotations

import itertools
import textwrap

import pytest

from inkpy.errors import AssetError
from inkpy.layout.compose import build_scene
from inkpy.layout.scene import DrawKind
from inkpy.model import parse_script
from inkpy.styles import get_style

FULL = """
comic:
  title: "Monday Morning"
  page: {width: 1200, height: 900, gutter: 16, margin: 24}
  layout: "2x2"
  panels:
    - id: 1
      background: kitchen
      camera: medium
      actors:
        - {character: cat, pose: sitting, expression: bored, at: [0.30, 0.08]}
      objects:
        - {name: mug, at: [0.70, 0.15], scale: 0.5}
      dialogue:
        - {speaker: cat, text: "I am awake. Unfortunately."}
    - id: 2
      background: kitchen
      actors:
        - {character: cat, at: [0.28, 0.08], z: 1}
        - {character: human, at: [0.72, 0.08], z: 0, flip: true}
      dialogue:
        - {speaker: cat, text: "Good morning."}
        - {speaker: human, text: "It is not."}
    - id: 3
      background: garden
      camera: wide
      actors:
        - {character: human, at: [0.5, 0.08]}
    - id: 4
      background: garden
      actors:
        - {character: cat, at: [0.5, 0.08]}
      dialogue:
        - {text: "Later.", type: narration}
"""


@pytest.fixture
def scene(library):
    return build_scene(parse_script(textwrap.dedent(FULL)), library)


class TestShape:
    def test_page_dimensions_carry_through(self, scene):
        assert (scene.width, scene.height) == (1200, 900)
        assert scene.title == "Monday Morning"

    def test_one_scene_panel_per_script_panel(self, scene):
        assert [panel.id for panel in scene.panels] == [1, 2, 3, 4]

    def test_panels_are_laid_out_in_reading_order(self, scene):
        for previous, current in itertools.pairwise(scene.panels):
            assert current.rect.top < previous.rect.top or current.rect.left > previous.rect.left

    def test_engine_version_is_recorded(self, scene):
        from inkpy import __version__

        assert scene.engine_version == __version__


class TestCompositionOrder:
    def test_background_is_drawn_first(self, scene):
        for panel in scene.panels:
            assert panel.draws[0].kind is DrawKind.BACKGROUND

    def test_background_covers_its_panel(self, scene):
        for panel in scene.panels:
            assert panel.draws[0].rect.contains_rect(panel.rect)

    def test_background_keeps_its_aspect_ratio(self, scene):
        draw = scene.panels[0].draws[0]
        assert draw.rect.width / draw.rect.height == pytest.approx(
            draw.sprite.width / draw.sprite.height
        )

    def test_a_panel_without_a_background_has_none(self, library):
        scene = build_scene(
            parse_script(
                'comic:\n  title: t\n  page: {width: 400, height: 300}\n'
                '  layout: "1x1"\n  panels:\n'
                "    - {id: 1, actors: [{character: cat, at: [0.5, 0.1]}]}\n"
            ),
            library,
        )
        assert all(draw.kind is not DrawKind.BACKGROUND for draw in scene.panels[0].draws)

    def test_faces_come_after_bodies(self, scene):
        for panel in scene.panels:
            for index, draw in enumerate(panel.draws):
                if draw.kind is DrawKind.FACE:
                    assert panel.draws[index - 1].kind is DrawKind.BODY


class TestInvariants:
    """The properties that make a page readable, asserted on every panel."""

    def test_no_bubble_covers_a_face(self, scene):
        for panel in scene.panels:
            faces = [d.rect for d in panel.draws if d.kind is DrawKind.FACE]
            for bubble, face in itertools.product(panel.bubbles, faces):
                assert not bubble.rect.intersects(face)

    def test_bubbles_stay_inside_their_panel(self, scene):
        for panel in scene.panels:
            for bubble in panel.bubbles:
                assert panel.rect.contains_rect(bubble.rect)

    def test_bubbles_never_overlap(self, scene):
        for panel in scene.panels:
            for a, b in itertools.combinations(panel.bubbles, 2):
                assert not a.rect.intersects(b.rect)

    def test_bubbles_follow_reading_order(self, scene):
        for panel in scene.panels:
            for previous, current in itertools.pairwise(panel.bubbles):
                assert current.order > previous.order
                below = current.rect.top <= previous.rect.bottom + 1e-9
                right = current.rect.left > previous.rect.left
                assert below or right

    def test_every_tail_reaches_its_own_speaker(self, scene):
        for panel in scene.panels:
            mouths = {
                draw.label.split("/")[0]: draw
                for draw in panel.draws
                if draw.kind is DrawKind.BODY
            }
            for bubble in panel.bubbles:
                if bubble.tail is None:
                    continue
                assert bubble.speaker in mouths
                assert panel.rect.contains(bubble.tail.tip)

    def test_actors_are_z_sorted(self, scene):
        for panel in scene.panels:
            keys = [draw.sort_key for draw in panel.draws if draw.kind is not DrawKind.BACKGROUND]
            assert keys == sorted(keys)

    def test_this_page_raises_no_unresolved_problem(self, scene):
        """Fitting notices are fine; anything the engine could not resolve is not.

        A character scaled down to clear the bubbles is the composition order
        working. A character that still intrudes at its minimum size, dialogue
        that swallows its panel, or an actor off-frame are all things only the
        author can fix.
        """
        unresolved = [
            warning
            for warning in scene.all_warnings()
            if "was scaled to" not in warning
        ]
        assert unresolved == []

    def test_fitting_notices_name_the_panel_and_the_character(self, scene):
        notices = [w for w in scene.all_warnings() if "was scaled to" in w]
        assert notices == [
            "panel 2: 'human' was scaled to 81% to clear the space reserved "
            "for bubbles."
        ]

    def test_a_silent_panel_gives_a_character_its_full_height(self, scene):
        """Panel 3 has no dialogue, so nothing is reserved and nothing shrinks."""
        body = next(d for d in scene.panel(3).draws if d.kind is DrawKind.BODY)
        panel = scene.panel(3)
        # human: default_height 0.70, camera wide.
        assert body.rect.height == pytest.approx(0.70 * 0.62 * panel.rect.height)


class TestReproducibility:
    def test_two_builds_agree(self, library):
        script = parse_script(textwrap.dedent(FULL))
        assert build_scene(script, library) == build_scene(script, library)

    def test_the_fingerprint_covers_the_sprites_actually_used(self, library, scene):
        used = {
            draw.sprite.name
            for panel in scene.panels
            for draw in panel.draws
        }
        # 'happy' and 'annoyed' exist in the library but appear nowhere here.
        assert "happy" not in used
        assert scene.asset_fingerprint != library.fingerprint()

    def test_the_fingerprint_moves_when_an_asset_does(self, library, library_root, scene):
        from tests.conftest import write_sprite
        from inkpy.assets import AssetLibrary

        write_sprite(
            library_root / "characters" / "cat" / "face" / "bored.png", (48, 48), "#000"
        )
        rebuilt = build_scene(
            parse_script(textwrap.dedent(FULL)), AssetLibrary.load(library_root)
        )
        assert rebuilt.asset_fingerprint != scene.asset_fingerprint


class TestStyles:
    def test_the_scripts_style_is_used_by_default(self, scene):
        assert scene.style.name == "default"

    def test_an_override_wins(self, library):
        scene = build_scene(
            parse_script(textwrap.dedent(FULL)), library, get_style("compact")
        )
        assert scene.style.name == "compact"

    def test_a_denser_style_makes_smaller_bubbles(self, library):
        script = parse_script(textwrap.dedent(FULL))
        default = build_scene(script, library)
        compact = build_scene(script, library, get_style("compact"))
        assert compact.panels[0].bubbles[0].font_size < default.panels[0].bubbles[0].font_size


class TestValidationRunsFirst:
    def test_a_missing_asset_stops_the_build(self, library):
        script = parse_script(
            'comic:\n  title: t\n  page: {width: 400, height: 300}\n'
            '  layout: "1x1"\n  panels:\n'
            "    - {id: 1, actors: [{character: cat, pose: flying, at: [0.5, 0.1]}]}\n"
        )
        with pytest.raises(AssetError, match="has no pose 'flying'"):
            build_scene(script, library)
