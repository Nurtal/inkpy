"""Page templates.

Assertions are on geometry, never on pixels: panels tile the content area, do
not overlap, and come back in reading order.
"""

from __future__ import annotations

import itertools

import pytest

from inkpy.errors import LayoutError
from inkpy.layout.page import MIN_PANEL_SIDE, content_area, panel_rects
from inkpy.model.enums import Layout
from inkpy.model.script import Page

PAGE = Page(width=1200, height=900, gutter=16, margin=24)


def rects(layout: Layout, page: Page = PAGE):
    return panel_rects(page, layout)


class TestContentArea:
    def test_margins_are_subtracted_on_both_sides(self):
        area = content_area(PAGE)
        assert (area.left, area.bottom) == (24.0, 24.0)
        assert (area.right, area.top) == (1176.0, 876.0)


@pytest.mark.parametrize("layout", list(Layout))
class TestEveryTemplate:
    def test_panel_count_matches_capacity(self, layout: Layout):
        assert len(rects(layout)) == layout.capacity

    def test_panels_stay_inside_the_content_area(self, layout: Layout):
        area = content_area(PAGE)
        for rect in rects(layout):
            assert area.contains_rect(rect)

    def test_panels_do_not_overlap(self, layout: Layout):
        for a, b in itertools.combinations(rects(layout), 2):
            assert not a.intersects(b)

    def test_panels_have_usable_size(self, layout: Layout):
        for rect in rects(layout):
            assert rect.width >= MIN_PANEL_SIDE and rect.height >= MIN_PANEL_SIDE

    def test_reading_order(self, layout: Layout):
        """Each panel starts at or below the previous one; ties go left to right."""
        for previous, current in itertools.pairwise(rects(layout)):
            if previous.top == current.top:
                assert current.left > previous.left
            else:
                assert current.top < previous.top

    def test_content_area_is_fully_used(self, layout: Layout):
        """Panels plus gutters account for the whole content area."""
        panels = rects(layout)
        assert min(r.left for r in panels) == pytest.approx(content_area(PAGE).left)
        assert max(r.right for r in panels) == pytest.approx(content_area(PAGE).right)
        assert min(r.bottom for r in panels) == pytest.approx(content_area(PAGE).bottom)
        assert max(r.top for r in panels) == pytest.approx(content_area(PAGE).top)


class TestSpecificShapes:
    def test_single_panel_fills_the_content_area(self):
        assert rects(Layout.ONE)[0] == content_area(PAGE)

    def test_two_across_share_the_width_minus_one_gutter(self):
        left, right = rects(Layout.TWO_ACROSS)
        assert left.width == right.width
        assert right.left - left.right == pytest.approx(PAGE.gutter)
        assert left.height == content_area(PAGE).height

    def test_two_down_are_stacked_top_first(self):
        top, bottom = rects(Layout.TWO_DOWN)
        assert top.bottom > bottom.top
        assert top.bottom - bottom.top == pytest.approx(PAGE.gutter)

    def test_strip_is_four_columns(self):
        panels = rects(Layout.STRIP)
        assert len({p.top for p in panels}) == 1
        assert all(p.width == pytest.approx(panels[0].width) for p in panels)

    def test_grid_reads_top_left_top_right_bottom_left_bottom_right(self):
        tl, tr, bl, br = rects(Layout.GRID)
        assert tl.top == tr.top and bl.top == br.top
        assert tl.left == bl.left and tr.left == br.left
        assert tl.top > bl.top

    def test_one_over_two_has_a_wide_panel_on_top(self):
        wide, left, right = rects(Layout.ONE_OVER_TWO)
        assert wide.width == pytest.approx(content_area(PAGE).width)
        assert wide.width > left.width
        assert left.width == pytest.approx(right.width)
        assert wide.bottom > left.top

    def test_two_over_one_has_a_wide_panel_below(self):
        left, right, wide = rects(Layout.TWO_OVER_ONE)
        assert wide.width == pytest.approx(content_area(PAGE).width)
        assert left.bottom > wide.top
        assert left.top == right.top


class TestDegenerateePages:
    def test_zero_gutter_makes_panels_touch(self):
        page = Page(width=800, height=600, gutter=0, margin=0)
        left, right = panel_rects(page, Layout.TWO_ACROSS)
        assert left.right == right.left

    def test_page_too_small_for_the_layout(self):
        page = Page(width=200, height=60, gutter=16, margin=8)
        with pytest.raises(LayoutError) as exc:
            panel_rects(page, Layout.GRID)
        assert "layout '2x2' leaves" in str(exc.value)
        assert "at least 16px" in str(exc.value)

    def test_error_names_the_offending_axis(self):
        page = Page(width=60, height=1000, gutter=16, margin=8)
        with pytest.raises(LayoutError, match="of width per panel"):
            panel_rects(page, Layout.STRIP)

    def test_determinism(self):
        assert panel_rects(PAGE, Layout.GRID) == panel_rects(PAGE, Layout.GRID)
