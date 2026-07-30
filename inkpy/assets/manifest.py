"""Character manifests.

A body sprite is a picture; the engine needs to know where the head sits on it
and where the mouth points, otherwise it can neither pin a face nor aim a
bubble tail. That knowledge lives next to the artwork, in ``character.yaml``,
because it belongs to the asset and not to any particular strip.

All manifest coordinates are normalized to the **body sprite's own bounding
box**, origin bottom-left, y up — the same convention as everywhere else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from inkpy.errors import AssetError
from inkpy.geometry import Vec2
from inkpy.model.enums import Anchor
from inkpy.model.script import Name, NormPoint

MANIFEST_NAME = "character.yaml"


class PoseSpec(BaseModel):
    """Geometry of one body pose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    head_anchor: NormPoint
    """Where the face sprite's centre is pinned, in body-sprite space."""

    mouth_offset: NormPoint
    """What a speech-bubble tail aims at, in body-sprite space."""

    face_scale: Annotated[float, Field(gt=0, le=10)] = 1.0
    """Tuning multiplier. The face sprite is otherwise drawn at the same pixel
    scale as the body, so its own resolution sets its size."""

    @property
    def head(self) -> Vec2:
        return Vec2(*self.head_anchor)

    @property
    def mouth(self) -> Vec2:
        return Vec2(*self.mouth_offset)


class CharacterManifest(BaseModel):
    """``assets/characters/<name>/character.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Name
    anchor: Anchor = Anchor.FEET
    default_height: Annotated[float, Field(gt=0, le=1)] = 0.45
    """Height at ``camera: medium``, as a fraction of the panel height."""

    flippable: bool = True
    poses: dict[Name, PoseSpec] = Field(min_length=1)
    expressions: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def _expressions_are_distinct(self) -> CharacterManifest:
        seen: list[str] = []
        for expression in self.expressions:
            if expression in seen:
                raise ValueError(f"expression '{expression}' is listed twice")
            seen.append(expression)
        return self

    @property
    def has_face_layer(self) -> bool:
        """A character with no declared expressions is a single flat sprite."""
        return bool(self.expressions)

    @property
    def pose_names(self) -> list[str]:
        return sorted(self.poses)


def load_manifest(path: str | Path) -> CharacterManifest:
    """Read and validate one ``character.yaml``."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AssetError(
            f"character manifest not found: {path}. Every character directory "
            f"must contain a {MANIFEST_NAME} declaring its poses and anchors."
        ) from exc
    except OSError as exc:
        raise AssetError(f"cannot read {path}: {exc}") from exc

    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AssetError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(document, dict):
        raise AssetError(
            f"{path} must be a mapping, got "
            f"{type(document).__name__ if document is not None else 'an empty file'}."
        )

    try:
        return CharacterManifest.model_validate(document)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in problem['loc']) or 'manifest'}: "
            f"{problem['msg'].removeprefix('Value error, ')}"
            for problem in exc.errors()
        )
        raise AssetError(f"{path} is not a valid character manifest — {problems}") from exc
