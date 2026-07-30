"""Geometric primitives shared by the layout engine and the intermediate
representation.

One convention, applied everywhere upstream of the backends:

- origin at the **bottom-left**;
- ``y`` axis points **up**;
- lengths in absolute pixels once layout has run, normalized to ``[0, 1]``
  while still in authorial intent.

The flip to SVG's y-down space happens in exactly one place: the SVG backend.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Vec2:
    """A point or a vector, in whatever space the holder documents."""

    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def scaled(self, factor: float) -> Vec2:
        return Vec2(self.x * factor, self.y * factor)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True, slots=True)
class Rect:
    """An axis-aligned rectangle anchored at its bottom-left corner."""

    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y

    @property
    def top(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Vec2:
        return Vec2(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, point: Vec2) -> bool:
        return self.left <= point.x <= self.right and self.bottom <= point.y <= self.top

    def contains_rect(self, other: Rect) -> bool:
        return (
            other.left >= self.left
            and other.right <= self.right
            and other.bottom >= self.bottom
            and other.top <= self.top
        )

    def intersects(self, other: Rect) -> bool:
        """Touching edges do not count as an intersection."""
        return not (
            other.left >= self.right
            or other.right <= self.left
            or other.bottom >= self.top
            or other.top <= self.bottom
        )

    def intersection_area(self, other: Rect) -> float:
        dx = min(self.right, other.right) - max(self.left, other.left)
        dy = min(self.top, other.top) - max(self.bottom, other.bottom)
        if dx <= 0 or dy <= 0:
            return 0.0
        return dx * dy

    def inset(self, amount: float) -> Rect:
        """Shrink on all four sides. Negative amounts grow the rectangle."""
        return Rect(
            self.x + amount,
            self.y + amount,
            max(0.0, self.width - 2 * amount),
            max(0.0, self.height - 2 * amount),
        )

    def moved_to(self, x: float, y: float) -> Rect:
        return Rect(x, y, self.width, self.height)

    def translated(self, dx: float, dy: float) -> Rect:
        return Rect(self.x + dx, self.y + dy, self.width, self.height)

    def to_local(self, point: Vec2) -> Vec2:
        """Map an absolute point into this rectangle's normalized space."""
        return Vec2(
            (point.x - self.x) / self.width if self.width else 0.0,
            (point.y - self.y) / self.height if self.height else 0.0,
        )

    def from_local(self, point: Vec2) -> Vec2:
        """Map a point normalized to this rectangle back into absolute space."""
        return Vec2(self.x + point.x * self.width, self.y + point.y * self.height)
