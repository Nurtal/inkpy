"""Placing characters and objects inside a panel.

Three things happen here, in this order.

**Scale comes from the camera, not from the author.** A manifest states how
tall a character is at ``camera: medium``; ``wide`` and ``close`` multiply that.
An explicit ``scale`` on an actor replaces the camera's factor, which is the
escape hatch and not the normal path.

**The anchor is the ground under the feet.** Not the sprite's centre, not its
bounding box. It is the only anchor that puts two characters of different
heights on the same horizon line, which is what makes a panel read as a space
rather than as a collage.

**Characters get what the bubbles left.** The reserved band is subtracted
before anything is placed, and a character too tall for the remainder is scaled
down rather than allowed to grow into it. Placing characters first is what
makes bubbles land on their heads.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from inkpy.assets.library import AssetLibrary
from inkpy.geometry import Rect, Vec2
from inkpy.layout.scene import DrawKind, Mark, SpriteDraw
from inkpy.model.enums import Anchor
from inkpy.model.script import Actor, Panel, Prop

MIN_SHRINK = 0.55
"""How far a character may be scaled down to clear the bubble band before the
engine gives up and warns instead. Below this it stops reading as the same
character across panels."""

SHRINK_TOLERANCE = 0.98
"""Shrinking by less than this much is normal fitting, not worth a warning."""


@dataclass(frozen=True, slots=True)
class PlacedActor:
    """A character resolved into pixels, plus the two points bubbles need."""

    character: str
    rect: Rect
    """The body sprite's box, in page space."""

    body: SpriteDraw
    face: SpriteDraw | None
    mouth: Vec2
    """Where a tail should point, in page space."""

    head: Vec2
    """Centre of the face, in page space. Bubbles must not cover it."""

    head_box: Rect
    """What counts as "the face" for collision purposes."""

    flip: bool

    @property
    def draws(self) -> tuple[SpriteDraw, ...]:
        return (self.body,) if self.face is None else (self.body, self.face)


@dataclass(frozen=True, slots=True)
class Placement:
    """Everything a panel's staging produced."""

    actors: tuple[PlacedActor, ...]
    draws: tuple[SpriteDraw, ...]
    """Actors and objects together, sorted back to front."""

    marks: tuple[Mark, ...]
    warnings: tuple[str, ...]

    def actor(self, character: str) -> PlacedActor | None:
        for candidate in self.actors:
            if candidate.character == character:
                return candidate
        return None


def place_panel_contents(
    panel: Panel,
    rect: Rect,
    library: AssetLibrary,
    reserved: Sequence[Rect] = (),
) -> Placement:
    """Resolve every actor and object of a panel into placed sprites.

    ``reserved`` is what the bubbles have already claimed — the nominal band on
    a first pass, the bubbles' own rectangles once they are known. Empty when
    the panel has no dialogue and characters may use its full height.

    A character only yields to the space above *itself*. Reserving a full-width
    band and shrinking everyone under it was the obvious first cut, and it
    punished a character standing under a gap for a bubble that is nowhere
    near them.
    """
    placed: list[PlacedActor] = []
    draws: list[SpriteDraw] = []
    marks: list[Mark] = []
    warnings: list[str] = []
    order = 0

    for actor in panel.actors:
        result, actor_warnings = _place_actor(
            actor, panel, rect, library, reserved, order
        )
        placed.append(result)
        draws.extend(result.draws)
        warnings.extend(actor_warnings)
        marks.extend(_actor_marks(result))
        order += 1

    for prop in panel.objects:
        drawn = _place_prop(prop, rect, library, order)
        draws.append(drawn)
        marks.append(Mark(kind="object", label=prop.name, rect=drawn.rect))
        order += 1

    # Stable sort: equal (z, order) keeps insertion order, which is what pins a
    # face immediately in front of its own body.
    draws.sort(key=lambda draw: draw.sort_key)

    for index, claimed in enumerate(reserved):
        marks.append(Mark(kind="band", label=f"reserved {index + 1}", rect=claimed))

    return Placement(
        actors=tuple(placed),
        draws=tuple(draws),
        marks=tuple(marks),
        warnings=tuple(warnings),
    )


def _ceiling_over(
    anchor_point: Vec2, width: float, rect: Rect, reserved: Sequence[Rect]
) -> float:
    """How high this actor may reach, given what sits above them.

    Only the reserved rectangles that actually overlap the actor's column
    count. A bubble on the far side of the panel is not in anybody's way.
    """
    left = anchor_point.x - width / 2
    right = anchor_point.x + width / 2
    ceiling = rect.top
    for claimed in reserved:
        if claimed.right <= left or claimed.left >= right:
            continue
        if claimed.bottom <= anchor_point.y:
            continue
        ceiling = min(ceiling, claimed.bottom)
    return ceiling


def _place_actor(
    actor: Actor,
    panel: Panel,
    rect: Rect,
    library: AssetLibrary,
    reserved: Sequence[Rect],
    order: int,
) -> tuple[PlacedActor, list[str]]:
    character = library.character(actor.character)
    body_sprite = character.body(actor.pose)
    spec = character.pose_spec(actor.pose)
    warnings: list[str] = []

    factor = actor.scale if actor.scale is not None else panel.camera.scale_factor
    nominal_height = character.manifest.default_height * factor * rect.height

    anchor_point = rect.from_local(actor.position)
    height = nominal_height
    # The column is measured at full size: a character that shrinks does not
    # get to slide out from under the bubble that made it shrink.
    ceiling = _ceiling_over(
        anchor_point, nominal_height * body_sprite.aspect, rect, reserved
    )
    available = ceiling - anchor_point.y
    if available > 0 and height > available:
        shrunk = max(available, nominal_height * MIN_SHRINK)
        if shrunk / nominal_height < SHRINK_TOLERANCE:
            warnings.append(
                f"panel {panel.id}: '{actor.character}' was scaled to "
                f"{shrunk / nominal_height:.0%} to clear the space reserved "
                f"for bubbles."
            )
        if shrunk > available:
            warnings.append(
                f"panel {panel.id}: '{actor.character}' still reaches into the "
                f"bubble band even at its minimum size. Move it down, use a "
                f"wider camera, or shorten the dialogue."
            )
        height = shrunk

    width = height * body_sprite.aspect
    body_rect = _anchored_rect(anchor_point, width, height, character.manifest.anchor)

    if not rect.intersects(body_rect):
        warnings.append(
            f"panel {panel.id}: '{actor.character}' is placed entirely outside "
            f"the panel at {tuple(actor.at)} and will not be visible."
        )

    body_draw = SpriteDraw(
        sprite=body_sprite,
        rect=body_rect,
        kind=DrawKind.BODY,
        label=f"{actor.character}/{actor.pose}",
        z=actor.z,
        flip=actor.flip,
        order=order,
    )

    face_sprite = character.face(actor.expression)
    head_local = _mirrored(spec.head, actor.flip)
    head_point = body_rect.from_local(head_local)

    face_draw: SpriteDraw | None = None
    head_box = Rect(head_point.x, head_point.y, 0.0, 0.0)
    if face_sprite is not None:
        # The face rides at the body's own pixel scale, so a manifest never has
        # to restate a size that the artwork already carries.
        pixel_scale = body_rect.height / body_sprite.height * spec.face_scale
        face_width = face_sprite.width * pixel_scale
        face_height = face_sprite.height * pixel_scale
        head_box = Rect(
            head_point.x - face_width / 2,
            head_point.y - face_height / 2,
            face_width,
            face_height,
        )
        face_draw = SpriteDraw(
            sprite=face_sprite,
            rect=head_box,
            kind=DrawKind.FACE,
            label=f"{actor.character}/{actor.expression}",
            z=actor.z,
            flip=actor.flip,
            order=order,
        )

    mouth_point = body_rect.from_local(_mirrored(spec.mouth, actor.flip))

    return (
        PlacedActor(
            character=actor.character,
            rect=body_rect,
            body=body_draw,
            face=face_draw,
            mouth=mouth_point,
            head=head_point,
            head_box=head_box,
            flip=actor.flip,
        ),
        warnings,
    )


def _place_prop(prop: Prop, rect: Rect, library: AssetLibrary, order: int) -> SpriteDraw:
    """Objects are sized as a fraction of the panel height, like characters,
    so that ``scale: 0.4`` means the same thing everywhere."""
    sprite = library.obj(prop.name)
    height = prop.scale * rect.height * _OBJECT_BASE_HEIGHT
    width = height * sprite.aspect
    anchor_point = rect.from_local(prop.position)
    return SpriteDraw(
        sprite=sprite,
        rect=_anchored_rect(anchor_point, width, height, Anchor.FEET),
        kind=DrawKind.OBJECT,
        label=prop.name,
        z=prop.z,
        flip=prop.flip,
        order=order,
    )


_OBJECT_BASE_HEIGHT = 0.30
"""What ``scale: 1.0`` means for an object, as a fraction of panel height."""


def _anchored_rect(point: Vec2, width: float, height: float, anchor: Anchor) -> Rect:
    if anchor is Anchor.CENTER:
        return Rect(point.x - width / 2, point.y - height / 2, width, height)
    # Anchor.FEET: the point is the ground under the sprite, horizontally centred.
    return Rect(point.x - width / 2, point.y, width, height)


def _mirrored(point: Vec2, flip: bool) -> Vec2:
    """Manifest coordinates are authored for the unflipped sprite."""
    return Vec2(1.0 - point.x, point.y) if flip else point


def _actor_marks(actor: PlacedActor) -> list[Mark]:
    return [
        Mark(kind="actor", label=actor.character, rect=actor.rect),
        Mark(kind="head", label=actor.character, at=actor.head, rect=actor.head_box),
        Mark(kind="mouth", label=actor.character, at=actor.mouth),
        Mark(
            kind="feet",
            label=actor.character,
            at=Vec2(actor.rect.center.x, actor.rect.bottom),
        ),
    ]
