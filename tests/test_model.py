"""The schema, and above all the messages it produces when the schema is broken.

Validation errors are part of the public surface: an author reads them far more
often than they read the docs.
"""

from __future__ import annotations

import textwrap

import pytest

from inkpy.errors import ScriptError
from inkpy.model import BubbleType, Camera, Layout, parse_script

MINIMAL = """
comic:
  title: "Monday Morning"
  page: {width: 1200, height: 900}
  layout: "1x1"
  panels:
    - id: 1
      background: kitchen
      actors:
        - character: cat
          pose: sitting
          expression: bored
          at: [0.30, 0.10]
      dialogue:
        - speaker: cat
          text: "I am awake. Unfortunately."
"""


def parse(text: str):
    return parse_script(textwrap.dedent(text), source="strip.yaml")


class TestHappyPath:
    def test_minimal_strip_parses(self):
        script = parse(MINIMAL)
        assert script.title == "Monday Morning"
        assert script.layout is Layout.ONE
        assert len(script.panels) == 1

    def test_defaults_are_applied(self):
        panel = parse(MINIMAL).panels[0]
        assert panel.camera is Camera.MEDIUM
        assert panel.dialogue[0].type is BubbleType.SPEECH
        assert panel.actors[0].z == 0
        assert panel.actors[0].flip is False
        assert panel.actors[0].scale is None

    def test_page_defaults(self):
        page = parse(MINIMAL).page
        assert (page.gutter, page.margin) == (16, 24)

    def test_asset_inventory_is_sorted_and_deduplicated(self):
        script = parse(
            """
            comic:
              title: t
              page: {width: 800, height: 400}
              layout: "2x1"
              panels:
                - id: 1
                  background: kitchen
                  actors: [{character: human, at: [0.5, 0.1]}]
                  objects: [{name: mug, at: [0.2, 0.3]}]
                - id: 2
                  background: kitchen
                  actors:
                    - {character: cat, at: [0.3, 0.1]}
                    - {character: human, at: [0.7, 0.1]}
            """
        )
        assert script.characters == ("cat", "human")
        assert script.backgrounds == ("kitchen",)
        assert script.props == ("mug",)

    def test_panel_lookup(self):
        script = parse(MINIMAL)
        assert script.panel(1).id == 1
        with pytest.raises(KeyError, match=r"Available ids: 1"):
            script.panel(7)


class TestDocumentShape:
    def test_empty_file(self):
        with pytest.raises(ScriptError, match="strip.yaml is empty"):
            parse("")

    def test_invalid_yaml(self):
        with pytest.raises(ScriptError, match="not valid YAML"):
            parse("comic: [unclosed")

    def test_missing_root_key(self):
        with pytest.raises(ScriptError, match=r"no top-level 'comic:' key. Found: strip"):
            parse("strip: {}")

    def test_extra_root_key(self):
        with pytest.raises(ScriptError, match="unexpected top-level keys: notes"):
            parse(MINIMAL + "\nnotes: hello\n")

    def test_root_is_not_a_mapping(self):
        with pytest.raises(ScriptError, match="must be a mapping"):
            parse("- one\n- two\n")


class TestFieldErrors:
    def test_unknown_field_is_rejected(self):
        with pytest.raises(ScriptError) as exc:
            parse(MINIMAL.replace("expression: bored", "expresion: bored"))
        assert "comic.panels[0].actors[0].expresion" in str(exc.value)
        assert "unknown field" in str(exc.value)

    def test_missing_field_is_located(self):
        with pytest.raises(ScriptError) as exc:
            parse(MINIMAL.replace("title: \"Monday Morning\"", "page_title: x"))
        message = str(exc.value)
        assert "comic.title: required field is missing." in message

    def test_coordinates_must_be_normalized(self):
        with pytest.raises(ScriptError) as exc:
            parse(MINIMAL.replace("at: [0.30, 0.10]", "at: [30, 10]"))
        assert "comic.panels[0].actors[0].at[0]" in str(exc.value)

    def test_asset_names_are_constrained(self):
        with pytest.raises(ScriptError) as exc:
            parse(MINIMAL.replace("character: cat", "character: Cat"))
        assert "lowercase" in str(exc.value)

    def test_all_problems_are_reported_at_once(self):
        with pytest.raises(ScriptError) as exc:
            parse(
                """
                comic:
                  title: t
                  page: {width: 0, height: -1}
                  layout: "1x1"
                  panels: [{id: 1}]
                """
            )
        assert "2 problems" in str(exc.value)


class TestCrossFieldRules:
    def test_panel_count_must_match_layout(self):
        with pytest.raises(ScriptError) as exc:
            parse(MINIMAL.replace('layout: "1x1"', 'layout: "2x2"'))
        assert "layout '2x2' holds exactly 4 panels, but 1 were given" in str(exc.value)

    def test_singular_wording_for_one_panel_layout(self):
        with pytest.raises(ScriptError, match="holds exactly 1 panel,"):
            parse(
                """
                comic:
                  title: t
                  page: {width: 800, height: 400}
                  layout: "1x1"
                  panels:
                    - {id: 1}
                    - {id: 2}
                """
            )

    def test_more_than_four_panels_is_rejected(self):
        panels = "\n".join(f"    - {{id: {i}}}" for i in range(1, 6))
        with pytest.raises(ScriptError) as exc:
            parse(
                "comic:\n  title: t\n  page: {width: 800, height: 400}\n"
                '  layout: "2x2"\n  panels:\n' + panels
            )
        assert "at most 4" in str(exc.value)

    def test_duplicate_panel_ids(self):
        with pytest.raises(ScriptError, match="panel id 1 is used more than once"):
            parse(
                """
                comic:
                  title: t
                  page: {width: 800, height: 400}
                  layout: "2x1"
                  panels:
                    - {id: 1}
                    - {id: 1}
                """
            )

    def test_same_character_twice_in_a_panel(self):
        with pytest.raises(ScriptError, match="places character 'cat' twice"):
            parse(
                """
                comic:
                  title: t
                  page: {width: 800, height: 400}
                  layout: "1x1"
                  panels:
                    - id: 1
                      actors:
                        - {character: cat, at: [0.2, 0.1]}
                        - {character: cat, at: [0.8, 0.1]}
                """
            )

    def test_speaker_must_be_in_the_panel(self):
        with pytest.raises(ScriptError) as exc:
            parse(MINIMAL.replace("speaker: cat", "speaker: dog"))
        assert "spoken by 'dog', who is not in the panel. Present: cat." in str(exc.value)

    def test_speech_needs_a_speaker(self):
        with pytest.raises(ScriptError, match="needs a speaker"):
            parse(MINIMAL.replace("speaker: cat", "type: speech"))

    def test_narration_refuses_a_speaker(self):
        with pytest.raises(ScriptError, match="cannot have a speaker"):
            parse(MINIMAL.replace("speaker: cat", "speaker: cat\n          type: narration"))

    def test_narration_without_speaker_is_fine(self):
        script = parse(MINIMAL.replace("speaker: cat", "type: narration"))
        assert script.panels[0].dialogue[0].type is BubbleType.NARRATION

    def test_margin_must_leave_room(self):
        with pytest.raises(ScriptError, match="leaves no room"):
            parse(MINIMAL.replace("height: 900}", "height: 900, margin: 600}"))


class TestEnums:
    def test_unknown_layout_lists_the_closed_set(self):
        with pytest.raises(ScriptError) as exc:
            parse(MINIMAL.replace('layout: "1x1"', 'layout: "3x3"'))
        assert "'1x1'" in str(exc.value) and "'2+1'" in str(exc.value)

    def test_capacities(self):
        assert [layout.capacity for layout in Layout] == [1, 2, 2, 4, 4, 3, 3]

    def test_medium_camera_is_the_reference(self):
        assert Camera.MEDIUM.scale_factor == 1.0
        assert Camera.WIDE.scale_factor < Camera.CLOSE.scale_factor

    def test_only_narration_lacks_a_tail(self):
        tailless = [b for b in BubbleType if not b.has_tail]
        assert tailless == [BubbleType.NARRATION]
