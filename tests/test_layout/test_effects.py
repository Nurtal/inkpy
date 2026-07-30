"""Effects and frame weight."""

from __future__ import annotations

import textwrap

import pytest

from inkpy.geometry import Rect
from inkpy.layout.compose import build_scene
from inkpy.layout.effects import TAPER, effect_bounds, place_effects
from inkpy.model import parse_script
from inkpy.model.enums import EffectKind, Frame

PANEL = Rect(0.0, 0.0, 600.0, 400.0)


def panel_of(body: str):
    keys = textwrap.indent(textwrap.dedent(body).strip("\n"), " " * 6)
    return parse_script(
        "comic:\n"
        "  title: t\n"
        "  page: {width: 1200, height: 900}\n"
        '  layout: "1x1"\n'
        "  panels:\n"
        "    - id: 1\n"
        f"{keys}\n"
    ).panels[0]


LINES = """
effects:
  - {type: speed_lines, at: [0.6, 0.5], direction: right, length: 0.4, spread: 0.3, count: 7}
"""


class TestSpeedLines:
    def test_one_bundle_per_effect(self):
        strokes = place_effects(panel_of(LINES), PANEL)
        assert len(strokes) == 1
        assert strokes[0].kind is EffectKind.SPEED_LINES
        assert len(strokes[0].lines) == 7

    def test_lines_trail_behind_the_point_they_aim_at(self):
        """``at`` is where the movement is heading; the lines record where it
        has been."""
        strokes = place_effects(panel_of(LINES), PANEL)[0]
        target = PANEL.left + 0.6 * PANEL.width
        for start, end in strokes.lines:
            assert end.x == pytest.approx(target)
            assert start.x < end.x

    def test_direction_reverses_them(self):
        left = place_effects(
            panel_of(LINES.replace("direction: right", "direction: left")), PANEL
        )[0]
        for start, end in left.lines:
            assert start.x > end.x

    def test_vertical_directions_run_on_the_other_axis(self):
        up = place_effects(
            panel_of(LINES.replace("direction: right", "direction: up")), PANEL
        )[0]
        for start, end in up.lines:
            assert start.x == pytest.approx(end.x)
            assert start.y < end.y

    def test_lines_are_spread_across_the_direction_of_travel(self):
        strokes = place_effects(panel_of(LINES), PANEL)[0]
        offsets = sorted(end.y for _, end in strokes.lines)
        assert offsets[-1] - offsets[0] == pytest.approx(0.3 * PANEL.height)

    def test_the_middle_line_is_the_longest(self):
        strokes = place_effects(panel_of(LINES), PANEL)[0]
        lengths = [abs(end.x - start.x) for start, end in strokes.lines]
        assert lengths[len(lengths) // 2] == max(lengths)
        assert min(lengths) == pytest.approx(max(lengths) * (1 - TAPER))

    def test_a_single_line_sits_on_the_centre(self):
        strokes = place_effects(panel_of(LINES.replace("count: 7", "count: 1")), PANEL)[0]
        start, end = strokes.lines[0]
        assert end.y == pytest.approx(PANEL.bottom + 0.5 * PANEL.height)

    def test_length_is_relative_to_the_panel(self):
        wide = place_effects(panel_of(LINES), Rect(0, 0, 1200, 400))[0]
        narrow = place_effects(panel_of(LINES), Rect(0, 0, 600, 400))[0]
        assert effect_bounds(wide).width == pytest.approx(
            2 * effect_bounds(narrow).width
        )

    def test_effects_sort_among_themselves_by_depth(self):
        panel = panel_of(
            """
            effects:
              - {type: speed_lines, at: [0.3, 0.5], z: 5}
              - {type: speed_lines, at: [0.7, 0.5], z: 1}
            """
        )
        strokes = place_effects(panel, PANEL)
        assert [s.z for s in strokes] == [1, 5]

    def test_no_effects_means_no_strokes(self):
        assert place_effects(panel_of("actors: []"), PANEL) == ()

    def test_placement_is_deterministic(self):
        panel = panel_of(LINES)
        assert place_effects(panel, PANEL) == place_effects(panel, PANEL)


class TestFrameWeight:
    WEIGHTS = """
    comic:
      title: t
      page: {width: 800, height: 600}
      layout: "2x2"
      panels:
        - {id: 1, frame: none}
        - {id: 2, frame: thin}
        - {id: 3, frame: normal}
        - {id: 4, frame: bold}
    """

    def test_weights_are_ordered(self):
        assert (
            Frame.NONE.weight
            < Frame.THIN.weight
            < Frame.NORMAL.weight
            < Frame.BOLD.weight
        )

    def test_normal_is_the_reference(self):
        assert Frame.NORMAL.weight == 1.0

    def test_none_removes_the_frame_entirely(self):
        assert Frame.NONE.weight == 0.0

    def test_the_weight_reaches_the_ir(self, library):
        scene = build_scene(parse_script(textwrap.dedent(self.WEIGHTS)), library)
        assert [panel.frame_weight for panel in scene.panels] == [
            0.0,
            Frame.THIN.weight,
            1.0,
            Frame.BOLD.weight,
        ]

    def test_frame_defaults_to_normal(self, library):
        scene = build_scene(
            parse_script(
                'comic:\n  title: t\n  page: {width: 400, height: 300}\n'
                '  layout: "1x1"\n  panels: [{id: 1}]\n'
            ),
            library,
        )
        assert scene.panels[0].frame_weight == 1.0


class TestInTheScene:
    def test_effects_are_carried_and_marked(self, library):
        scene = build_scene(
            parse_script(
                "comic:\n  title: t\n  page: {width: 600, height: 400}\n"
                '  layout: "1x1"\n  panels:\n    - id: 1\n'
                "      effects:\n"
                "        - {type: speed_lines, at: [0.5, 0.5], count: 5}\n"
            ),
            library,
        )
        panel = scene.panels[0]
        assert len(panel.effects) == 1
        assert panel.mark("effect", "speed_lines") is not None

    def test_effects_stay_inside_the_panel_they_belong_to(self, library):
        scene = build_scene(
            parse_script(
                "comic:\n  title: t\n  page: {width: 600, height: 400}\n"
                '  layout: "1x1"\n  panels:\n    - id: 1\n'
                "      effects:\n"
                "        - {type: speed_lines, at: [0.5, 0.5], length: 0.3, spread: 0.3}\n"
            ),
            library,
        )
        panel = scene.panels[0]
        assert panel.rect.contains_rect(effect_bounds(panel.effects[0]))
