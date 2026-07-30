"""Page templates: a named layout becomes a list of panel rectangles.

Four panels maximum is the constraint that lets this file stay this short.
Every supported template is a stack of rows, each row an equal division into
columns, so one small routine covers the closed set:

    1x1 -> [1]      2x1 -> [2]      1x2 -> [1, 1]
    4x1 -> [4]      2x2 -> [2, 2]   1+2 -> [1, 2]   2+1 -> [2, 1]

Rectangles come back in reading order — top row first, left to right — and in
page space: origin bottom-left, y up, absolute pixels.
"""

from __future__ import annotations

from inkpy.errors import LayoutError
from inkpy.geometry import Rect
from inkpy.model.enums import Layout
from inkpy.model.script import Page

MIN_PANEL_SIDE = 16.0
"""Below this, a panel cannot hold anything legible. Better to say so."""

_ROWS: dict[Layout, tuple[int, ...]] = {
    Layout.ONE: (1,),
    Layout.TWO_ACROSS: (2,),
    Layout.TWO_DOWN: (1, 1),
    Layout.STRIP: (4,),
    Layout.GRID: (2, 2),
    Layout.ONE_OVER_TWO: (1, 2),
    Layout.TWO_OVER_ONE: (2, 1),
}


def rows_of(layout: Layout) -> tuple[int, ...]:
    """Column count per row, top row first."""
    return _ROWS[layout]


def content_area(page: Page) -> Rect:
    """The page minus its margins."""
    return Rect(
        x=float(page.margin),
        y=float(page.margin),
        width=float(page.width - 2 * page.margin),
        height=float(page.height - 2 * page.margin),
    )


def panel_rects(page: Page, layout: Layout) -> tuple[Rect, ...]:
    """Divide the page into panel rectangles, in reading order."""
    rows = rows_of(layout)
    area = content_area(page)

    gutter = float(page.gutter)
    total_gutter_h = gutter * (len(rows) - 1)
    row_height = (area.height - total_gutter_h) / len(rows)
    _reject_if_too_small(row_height, page, layout, axis="height")

    rects: list[Rect] = []
    for row_index, columns in enumerate(rows):
        # Rows are laid out from the top down, because that is reading order,
        # while y grows upward.
        top = area.top - row_index * (row_height + gutter)
        bottom = top - row_height

        total_gutter_w = gutter * (columns - 1)
        column_width = (area.width - total_gutter_w) / columns
        _reject_if_too_small(column_width, page, layout, axis="width")

        for column_index in range(columns):
            left = area.left + column_index * (column_width + gutter)
            rects.append(Rect(left, bottom, column_width, row_height))
    return tuple(rects)


def _reject_if_too_small(size: float, page: Page, layout: Layout, axis: str) -> None:
    if size >= MIN_PANEL_SIDE:
        return
    raise LayoutError(
        f"layout '{layout.value}' leaves {size:.1f}px of {axis} per panel on a "
        f"{page.width}x{page.height} page with margin {page.margin} and gutter "
        f"{page.gutter}. Panels need at least {MIN_PANEL_SIDE:.0f}px. "
        f"Enlarge the page, or reduce the margin and gutter."
    )
