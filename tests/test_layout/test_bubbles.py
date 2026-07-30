"""Bubble layout.

The assertions the README names as the point of having an IR live here: no
bubble covers a face, bubbles follow reading order, everything stays inside
its panel.
"""

from __future__ import annotations

import itertools
import textwrap

import pytest

from inkpy.geometry import Rect
from inkpy.layout.bubbles import band_for, layout_bubbles, plan_bubbles, wrap_text
from inkpy.layout.actors import place_panel_contents
from inkpy.model import parse_script
from inkpy.model.enums import BubbleType
from inkpy.styles import DEFAULT, PanelStyle

PANEL = Rect(0.0, 0.0, 600.0, 450.0)
STYLE = PanelStyle.resolve(DEFAULT, PANEL, 450.0)


def panel_of(body: str):
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


def lay_out(body: str, library, rect: Rect = PANEL, style: PanelStyle = STYLE):
    """Run the same two-pass reservation the composer does.

    Reserve a nominal band, place actors to find their mouths, measure the
    dialogue, then reserve for real and place again.
    """
    panel = panel_of(body)
    band = band_of(body, library, rect, style)
    reserved = ()
    if band is not None:
        draft = place_panel_contents(panel, rect, library, (style.band,))
        provisional = layout_bubbles(panel, rect, draft, style, band=band)
        reserved = tuple(bubble.rect for bubble in provisional.bubbles)
    placement = place_panel_contents(panel, rect, library, reserved)
    return panel, placement, layout_bubbles(panel, rect, placement, style, band=band)


def band_of(body: str, library, rect: Rect = PANEL, style: PanelStyle = STYLE):
    """The band the composer would reserve for this panel, or ``None``."""
    panel = panel_of(body)
    if not panel.dialogue:
        return None
    draft = place_panel_contents(panel, rect, library, (style.band,))
    return band_for(plan_bubbles(panel, rect, draft, style), rect, style)


TWO_SPEAKERS = """
actors:
  - {character: cat, at: [0.25, 0.05]}
  - {character: human, at: [0.75, 0.05]}
dialogue:
  - {speaker: human, text: "Are you finally awake?"}
  - {speaker: cat, text: "I am awake. Unfortunately."}
"""


class TestWrapping:
    def test_short_text_stays_on_one_line(self):
        assert wrap_text("Hi.", STYLE.typeface, 20.0, 500.0) == ["Hi."]

    def test_lines_never_exceed_the_measure(self):
        text = "The quick brown fox jumps over the lazy dog again and again."
        lines = wrap_text(text, STYLE.typeface, 20.0, 160.0)
        assert len(lines) > 1
        for line in lines:
            assert STYLE.typeface.width(line, 20.0) <= 160.0

    def test_no_word_is_lost(self):
        text = "The quick brown fox jumps over the lazy dog."
        lines = wrap_text(text, STYLE.typeface, 20.0, 120.0)
        assert " ".join(lines).split() == text.split()

    def test_explicit_newlines_are_honoured(self):
        assert wrap_text("one\ntwo", STYLE.typeface, 20.0, 500.0) == ["one", "two"]

    def test_a_word_too_long_for_the_measure_is_split(self):
        lines = wrap_text("supercalifragilistic", STYLE.typeface, 20.0, 60.0)
        assert len(lines) > 1
        assert "".join(lines) == "supercalifragilistic"
        for line in lines:
            assert STYLE.typeface.width(line, 20.0) <= 60.0

    def test_wrapping_is_measured_not_estimated(self):
        """Wide and narrow strings of equal length wrap differently."""
        wide = wrap_text("W" * 20, STYLE.typeface, 20.0, 200.0)
        narrow = wrap_text("i" * 20, STYLE.typeface, 20.0, 200.0)
        assert len(wide) > len(narrow)


class TestSizing:
    def test_a_bubble_encloses_its_own_text(self, library):
        _, _, result = lay_out(TWO_SPEAKERS, library)
        for bubble in result.bubbles:
            for line in bubble.lines:
                assert bubble.rect.left <= line.baseline.x
                assert line.baseline.x + line.width <= bubble.rect.right
                assert bubble.rect.bottom <= line.baseline.y <= bubble.rect.top

    def test_longer_text_makes_a_bigger_bubble(self, library):
        short = lay_out(
            'actors: [{character: cat, at: [0.5, 0.05]}]\n'
            'dialogue: [{speaker: cat, text: "No."}]',
            library,
        )[2]
        long = lay_out(
            'actors: [{character: cat, at: [0.5, 0.05]}]\n'
            'dialogue: [{speaker: cat, text: "No, and I would like to explain '
            'at some length exactly why not."}]',
            library,
        )[2]
        assert long.bubbles[0].rect.area > short.bubbles[0].rect.area

    def test_no_dialogue_means_no_bubbles(self, library):
        _, _, result = lay_out("actors: [{character: cat, at: [0.5, 0.05]}]", library)
        assert result.bubbles == () and result.warnings == ()

    def test_lines_do_not_overlap_each_other(self, library):
        _, _, result = lay_out(
            'actors: [{character: cat, at: [0.5, 0.05]}]\n'
            'dialogue: [{speaker: cat, text: "One two three four five six '
            'seven eight nine ten eleven twelve."}]',
            library,
        )
        bubble = result.bubbles[0]
        assert len(bubble.lines) >= 3
        for upper, lower in itertools.pairwise(bubble.lines):
            assert upper.baseline.y > lower.baseline.y


class TestPlacement:
    def test_bubbles_stay_inside_the_panel(self, library):
        _, _, result = lay_out(TWO_SPEAKERS, library)
        for bubble in result.bubbles:
            assert PANEL.contains_rect(bubble.rect)

    def test_bubbles_sit_in_the_reserved_band(self, library):
        band = band_of(TWO_SPEAKERS, library)
        _, _, result = lay_out(TWO_SPEAKERS, library)
        for bubble in result.bubbles:
            assert bubble.rect.top <= band.top + 1e-9
            assert bubble.rect.bottom >= band.bottom - 1e-9

    def test_the_band_grows_to_fit_what_must_be_said(self, library):
        """``bubble_band`` is a floor. Two stacked bubbles need more than the
        style's nominal share, and get it, rather than spilling over the art."""
        band = band_of(TWO_SPEAKERS, library)
        assert band.height > STYLE.band_height
        assert band.top == pytest.approx(PANEL.top)

    def test_bubbles_do_not_overlap_each_other(self, library):
        _, _, result = lay_out(TWO_SPEAKERS, library)
        for a, b in itertools.combinations(result.bubbles, 2):
            assert not a.rect.intersects(b.rect)

    def test_no_bubble_covers_a_face(self, library):
        _, placement, result = lay_out(TWO_SPEAKERS, library)
        for actor in placement.actors:
            for bubble in result.bubbles:
                assert not bubble.rect.intersects(actor.head_box)

    def test_a_bubble_gravitates_to_its_speaker(self, library):
        """Speakers in reading order keep their bubbles above their heads."""
        _, placement, result = lay_out(
            """
            actors:
              - {character: cat, at: [0.25, 0.05]}
              - {character: human, at: [0.75, 0.05]}
            dialogue:
              - {speaker: cat, text: "Morning."}
              - {speaker: human, text: "Morning."}
            """,
            library,
        )
        for bubble in result.bubbles:
            mouth = placement.actor(bubble.speaker).mouth
            assert abs(bubble.rect.center.x - mouth.x) < bubble.rect.width / 2

    def test_speakers_out_of_order_are_stacked_not_crossed(self, library):
        """The right-hand character speaks first.

        Side by side, reading order would force the first bubble to the left
        and the second to the right, running both tails across each other.
        Stacking them keeps each bubble over its own speaker and leaves the
        reading order unambiguous.
        """
        _, placement, result = lay_out(TWO_SPEAKERS, library)
        first, second = result.bubbles
        assert first.speaker == "human" and second.speaker == "cat"
        assert second.rect.top <= first.rect.bottom + 1e-9
        for bubble in result.bubbles:
            mouth = placement.actor(bubble.speaker).mouth
            assert abs(bubble.rect.center.x - mouth.x) < bubble.rect.width

    def test_a_lone_bubble_centres_on_its_speaker(self, library):
        _, placement, result = lay_out(
            'actors: [{character: cat, at: [0.3, 0.05]}]\n'
            'dialogue: [{speaker: cat, text: "Mm."}]',
            library,
        )
        assert result.bubbles[0].rect.center.x == pytest.approx(
            placement.actor("cat").mouth.x
        )

    def test_bubbles_wider_than_the_band_stack_into_rows(self, library):
        _, _, result = lay_out(
            """
            actors:
              - {character: cat, at: [0.25, 0.05]}
              - {character: human, at: [0.75, 0.05]}
            dialogue:
              - {speaker: human, text: "This is a fairly long first line of dialogue."}
              - {speaker: cat, text: "And this is an equally long reply to it."}
            """,
            library,
        )
        first, second = result.bubbles
        assert second.rect.top <= first.rect.bottom + 1e-9


class TestReadingOrder:
    def test_array_order_is_reading_order(self, library):
        _, _, result = lay_out(
            """
            actors:
              - {character: cat, at: [0.25, 0.05]}
              - {character: human, at: [0.75, 0.05]}
            dialogue:
              - {speaker: cat, text: "First."}
              - {speaker: human, text: "Second."}
              - {speaker: cat, text: "Third."}
            """,
            library,
        )
        for previous, current in itertools.pairwise(result.bubbles):
            same_row = previous.rect.top == pytest.approx(current.rect.top)
            if same_row:
                assert current.rect.left > previous.rect.left
            else:
                assert current.rect.top <= previous.rect.top

    def test_order_survives_speakers_standing_the_wrong_way_round(self, library):
        """Whatever the staging, consecutive bubbles never read ambiguously:
        either one is clearly above the other, or clearly to its left."""
        _, _, result = lay_out(
            """
            actors:
              - {character: cat, at: [0.15, 0.05]}
              - {character: human, at: [0.85, 0.05]}
            dialogue:
              - {speaker: human, text: "Me first."}
              - {speaker: cat, text: "Then me."}
            """,
            library,
        )
        first, second = result.bubbles
        assert not first.rect.intersects(second.rect)
        assert second.rect.top <= first.rect.bottom or second.rect.left > first.rect.left

    def test_bubbles_keep_their_index(self, library):
        _, _, result = lay_out(TWO_SPEAKERS, library)
        assert [bubble.order for bubble in result.bubbles] == [0, 1]


class TestTails:
    def test_a_tail_points_at_the_speakers_mouth(self, library):
        _, placement, result = lay_out(TWO_SPEAKERS, library)
        for bubble in result.bubbles:
            speaker = placement.actor(bubble.speaker)
            assert bubble.tail is not None
            assert bubble.tail.tip.as_tuple() == pytest.approx(speaker.mouth.as_tuple())

    def test_a_tail_starts_on_the_bubble_outline(self, library):
        _, _, result = lay_out(TWO_SPEAKERS, library)
        for bubble in result.bubbles:
            root = bubble.tail.root
            # On the ellipse inscribed in the bubble's box.
            u = (root.x - bubble.rect.center.x) / (bubble.rect.width / 2)
            v = (root.y - bubble.rect.center.y) / (bubble.rect.height / 2)
            assert u * u + v * v == pytest.approx(1.0)

    def test_a_tail_leaves_on_the_bearing_of_the_mouth(self, library):
        _, placement, result = lay_out(TWO_SPEAKERS, library)
        for bubble in result.bubbles:
            mouth = placement.actor(bubble.speaker).mouth
            centre = bubble.rect.center
            # Root and mouth are on the same side of the bubble's centre.
            assert (bubble.tail.root.y - centre.y) * (mouth.y - centre.y) >= 0

    def test_flip_moves_the_tail_with_the_mouth(self, library):
        straight = lay_out(
            'actors: [{character: human, at: [0.5, 0.05]}]\n'
            'dialogue: [{speaker: human, text: "Hm."}]',
            library,
        )[2].bubbles[0]
        flipped = lay_out(
            'actors: [{character: human, at: [0.5, 0.05], flip: true}]\n'
            'dialogue: [{speaker: human, text: "Hm."}]',
            library,
        )[2].bubbles[0]
        assert flipped.tail.tip.x != straight.tail.tip.x

    def test_narration_has_no_tail(self, library):
        _, _, result = lay_out(
            'actors: [{character: cat, at: [0.5, 0.05]}]\n'
            'dialogue: [{text: "Later that morning.", type: narration}]',
            library,
        )
        assert result.bubbles[0].kind is BubbleType.NARRATION
        assert result.bubbles[0].tail is None


class TestOverflowIsReported:
    def test_dialogue_that_swallows_the_panel_warns(self, library):
        _, _, result = lay_out(
            'actors: [{character: cat, at: [0.5, 0.05]}]\n'
            'dialogue:\n'
            '  - {speaker: cat, text: "' + "words " * 60 + '"}',
            library,
        )
        assert any("leaving almost no picture" in w for w in result.warnings)

    def test_the_warning_quantifies_the_problem(self, library):
        _, _, result = lay_out(
            'actors: [{character: cat, at: [0.5, 0.05]}]\n'
            'dialogue:\n'
            '  - {speaker: cat, text: "' + "words " * 60 + '"}',
            library,
        )
        assert any("% of the panel's height" in w for w in result.warnings)

    def test_a_normal_panel_is_silent(self, library):
        _, _, result = lay_out(TWO_SPEAKERS, library)
        assert result.warnings == ()


class TestCollisionResolution:
    """A bubble that lands on a face has to get off it, or say why it can't."""

    CROWDED = """
    actors:
      - {character: human, at: [0.5, 0.3]}
    dialogue:
      - {speaker: human, text: "Right in front of my face."}
    """

    def test_a_bubble_gets_off_a_face_it_would_have_covered(self, library):
        _, placement, result = lay_out(self.CROWDED, library)
        head = placement.actor("human").head_box
        assert not result.bubbles[0].rect.intersects(head)

    def test_shifting_is_preferred_to_shrinking(self, library):
        """The cheapest strategy first: the type size must survive."""
        _, _, result = lay_out(self.CROWDED, library)
        assert result.bubbles[0].font_size == pytest.approx(STYLE.font_size)

    IMPOSSIBLE = """
    actors:
      - {character: cat, at: [0.18, 0.55]}
      - {character: human, at: [0.5, 0.55]}
      - {character: cat2, at: [0.82, 0.55]}
    dialogue:
      - {speaker: human, text: "Three heads across the panel and no way past."}
    """

    def test_a_bubble_that_cannot_be_moved_says_so(self, three_across):
        """Heads spanning the width, high enough that shrinking cannot save them."""
        _, _, result = lay_out(self.IMPOSSIBLE, three_across)
        assert any("covers a face and cannot be moved clear" in w for w in result.warnings)

    def test_the_complaint_is_made_once(self, three_across):
        _, _, result = lay_out(self.IMPOSSIBLE, three_across)
        complaints = [w for w in result.warnings if "cannot be moved clear" in w]
        assert len(complaints) == 1

    def test_the_complaint_names_the_speaker_and_suggests_a_fix(self, three_across):
        _, _, result = lay_out(self.IMPOSSIBLE, three_across)
        complaint = next(w for w in result.warnings if "cannot be moved clear" in w)
        assert "the bubble for human" in complaint
        assert "Move the characters apart" in complaint

    def test_resolution_keeps_bubbles_inside_the_panel(self, library):
        _, _, result = lay_out(self.CROWDED, library)
        for bubble in result.bubbles:
            assert PANEL.contains_rect(bubble.rect)

    def test_resolution_preserves_reading_order(self, library):
        _, _, result = lay_out(
            """
            actors:
              - {character: cat, at: [0.3, 0.35]}
              - {character: human, at: [0.7, 0.3]}
            dialogue:
              - {speaker: cat, text: "One."}
              - {speaker: human, text: "Two."}
            """,
            library,
        )
        first, second = result.bubbles
        assert not first.rect.intersects(second.rect)
        assert second.rect.top <= first.rect.bottom + 1e-9 or second.rect.left > first.rect.left


class TestDeterminism:
    def test_same_input_same_geometry(self, library):
        first = lay_out(TWO_SPEAKERS, library)[2]
        second = lay_out(TWO_SPEAKERS, library)[2]
        assert first.bubbles == second.bubbles
