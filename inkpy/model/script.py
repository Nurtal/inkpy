"""Typed authorial intent.

``ComicScript`` is what a strip file means, not yet where anything sits. No
pixel appears in this module: positions are normalized to ``[0, 1]`` within
their panel, sizes are derived later from the asset manifests. The layout
engine turns this into a ``Scene``.

Every model forbids unknown fields. A silently ignored ``expresion:`` typo
would surface as a wrong render hours later; a hard error surfaces now.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inkpy.geometry import Vec2
from inkpy.model.enums import BubbleType, Camera, Direction, EffectKind, Frame, Layout

Norm = Annotated[float, Field(ge=0.0, le=1.0)]
"""A coordinate normalized to its panel, origin bottom-left, y up."""

NormPoint = tuple[Norm, Norm]

Name = Annotated[str, Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
"""Asset identifiers: lowercase, safe on every filesystem, stable in Git."""


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Page(BaseModel):
    """Physical dimensions of the sheet, in pixels. One page per file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    width: int = Field(gt=0, le=20000)
    height: int = Field(gt=0, le=20000)
    gutter: int = Field(default=16, ge=0)
    margin: int = Field(default=24, ge=0)

    @model_validator(mode="after")
    def _margins_leave_room(self) -> Page:
        # A page whose margins swallow the content area produces zero-sized
        # panels, which fails much later and much more confusingly.
        inner_w = self.width - 2 * self.margin
        inner_h = self.height - 2 * self.margin
        if inner_w <= 0 or inner_h <= 0:
            raise ValueError(
                f"page margin {self.margin}px leaves no room inside a "
                f"{self.width}x{self.height} page. "
                f"Reduce margin below {min(self.width, self.height) // 2}."
            )
        return self


class Actor(Base):
    """A character instance in a panel."""

    character: Name
    pose: Name = "idle"
    expression: Name = "neutral"
    at: NormPoint
    z: int = 0
    flip: bool = False
    scale: float | None = Field(default=None, gt=0, le=10)
    """Per-actor override of the camera-derived scale. Rarely needed."""

    @property
    def position(self) -> Vec2:
        """Where the character's feet land, normalized to the panel."""
        return Vec2(*self.at)


class Prop(Base):
    """A static object in a panel. Named ``objects`` in the strip file."""

    name: Name
    at: NormPoint
    scale: float = Field(default=1.0, gt=0, le=10)
    z: int = 0
    flip: bool = False

    @property
    def position(self) -> Vec2:
        return Vec2(*self.at)


class Dialogue(Base):
    """One bubble. Array order is reading order."""

    text: str = Field(min_length=1)
    type: BubbleType = BubbleType.SPEECH
    speaker: Name | None = None

    @model_validator(mode="after")
    def _speaker_matches_type(self) -> Dialogue:
        if self.type.needs_speaker and self.speaker is None:
            raise ValueError(
                f"dialogue of type '{self.type.value}' needs a speaker "
                f"(text: {self.text!r}). Use type 'narration' for a caption "
                f"that nobody says."
            )
        if not self.type.needs_speaker and self.speaker is not None:
            raise ValueError(
                f"dialogue of type '{self.type.value}' cannot have a speaker "
                f"(got {self.speaker!r}): a narration caption has no tail and "
                f"points at nobody."
            )
        return self


class Effect(Base):
    """A drawn flourish. Not artwork — artwork is the author's job.

    Speed lines are the one thing an engine can add without pretending to
    draw: they are ruled strokes whose whole content is a direction.
    """

    type: EffectKind = EffectKind.SPEED_LINES
    at: NormPoint
    """Centre of the effect, normalized to the panel."""

    direction: Direction = Direction.RIGHT
    length: Norm = 0.3
    """How far the lines run, as a fraction of the panel's width or height."""

    spread: Norm = 0.25
    """How far across the lines are spaced, perpendicular to their direction."""

    count: int = Field(default=7, ge=1, le=64)
    z: int = 0


class Panel(Base):
    """One case of the strip."""

    id: int = Field(ge=1)
    background: Name | None = None
    camera: Camera = Camera.MEDIUM
    frame: Frame = Frame.NORMAL
    actors: tuple[Actor, ...] = ()
    objects: tuple[Prop, ...] = ()
    effects: tuple[Effect, ...] = ()
    dialogue: tuple[Dialogue, ...] = ()

    @model_validator(mode="after")
    def _actors_are_distinct(self) -> Panel:
        # Dialogue addresses a speaker by character name, so the same character
        # twice in one panel would make the reference ambiguous.
        seen: list[str] = []
        for actor in self.actors:
            if actor.character in seen:
                raise ValueError(
                    f"panel {self.id} places character '{actor.character}' "
                    f"twice. Dialogue addresses speakers by name, so a "
                    f"character can only appear once per panel."
                )
            seen.append(actor.character)
        return self

    @model_validator(mode="after")
    def _speakers_are_present(self) -> Panel:
        cast = {actor.character for actor in self.actors}
        for line in self.dialogue:
            if line.speaker is not None and line.speaker not in cast:
                listing = ", ".join(sorted(cast)) if cast else "(no actors)"
                raise ValueError(
                    f"panel {self.id} has dialogue spoken by "
                    f"'{line.speaker}', who is not in the panel. "
                    f"Present: {listing}."
                )
        return self

    def actor(self, character: str) -> Actor | None:
        for candidate in self.actors:
            if candidate.character == character:
                return candidate
        return None


class ComicScript(Base):
    """A whole strip: the root of a validated strip file."""

    title: str = Field(min_length=1)
    page: Page
    layout: Layout
    style: Name = "default"
    panels: tuple[Panel, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _panel_count_matches_layout(self) -> ComicScript:
        expected = self.layout.capacity
        if len(self.panels) != expected:
            plural = "" if expected == 1 else "s"
            raise ValueError(
                f"layout '{self.layout.value}' holds exactly {expected} "
                f"panel{plural}, but {len(self.panels)} were given. "
                f"Pick a layout with matching capacity, or drop a panel."
            )
        return self

    @model_validator(mode="after")
    def _panel_ids_are_unique(self) -> ComicScript:
        seen: list[int] = []
        for panel in self.panels:
            if panel.id in seen:
                raise ValueError(
                    f"panel id {panel.id} is used more than once. "
                    f"Ids identify panels in warnings and debug output, so "
                    f"they must be unique."
                )
            seen.append(panel.id)
        return self

    def fingerprint(self) -> str:
        """A hash of everything in the strip that can change the render.

        Taken from the validated model, not from the file's bytes. A comment,
        a reordered mapping, a different way of quoting a string or a default
        written out in full are not changes to the strip, and a fingerprint
        that flagged them would teach people to ignore it. Change a word of
        dialogue, move an actor, swap a bubble type, and it moves.

        Field order comes from the class rather than from the file, so this is
        stable for a given engine version — and ``inkpy verify`` compares the
        engine version too, which is what covers the case of the models
        themselves changing shape.
        """
        canonical = self.model_dump_json()
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def panel(self, panel_id: int) -> Panel:
        for candidate in self.panels:
            if candidate.id == panel_id:
                return candidate
        available = ", ".join(str(p.id) for p in self.panels)
        raise KeyError(f"no panel with id {panel_id}. Available ids: {available}.")

    @property
    def characters(self) -> tuple[str, ...]:
        """Every character referenced anywhere, in stable sorted order."""
        names = {actor.character for panel in self.panels for actor in panel.actors}
        return tuple(sorted(names))

    @property
    def backgrounds(self) -> tuple[str, ...]:
        names = {p.background for p in self.panels if p.background is not None}
        return tuple(sorted(names))

    @property
    def props(self) -> tuple[str, ...]:
        names = {prop.name for panel in self.panels for prop in panel.objects}
        return tuple(sorted(names))
