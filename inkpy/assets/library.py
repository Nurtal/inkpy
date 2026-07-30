"""Loading and validating an asset library.

The library is read once, up front, and validated as a whole. A strip that
references a missing pose must fail before any pixel is computed, with a
message that names the character, the pose and what was actually available.

Consistency is checked in both directions: a pose declared in the manifest
needs a file, and a file needs a declaration. A stray ``body/flying.png`` that
nothing can reach is a mistake worth reporting, not silence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from inkpy.assets.manifest import MANIFEST_NAME, CharacterManifest, load_manifest
from inkpy.errors import AssetError, did_you_mean

SPRITE_SUFFIX = ".png"
CHARACTERS_DIR = "characters"
OBJECTS_DIR = "objects"
BACKGROUNDS_DIR = "backgrounds"
BODY_DIR = "body"
FACE_DIR = "face"


@dataclass(frozen=True)
class Sprite:
    """One image file, with the dimensions layout needs to preserve its ratio."""

    name: str
    path: Path
    width: int
    height: int

    @property
    def aspect(self) -> float:
        """Width over height. Sprites are never distorted, only scaled."""
        return self.width / self.height

    @cached_property
    def sha256(self) -> str:
        """Content hash, written into render metadata for reproducibility."""
        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()


@dataclass(frozen=True)
class Character:
    """A manifest plus the sprites it promised."""

    manifest: CharacterManifest
    bodies: dict[str, Sprite] = field(default_factory=dict)
    faces: dict[str, Sprite] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.manifest.name

    def body(self, pose: str) -> Sprite:
        try:
            return self.bodies[pose]
        except KeyError:
            raise AssetError(
                f"Character '{self.name}' has no pose '{pose}'. "
                f"{did_you_mean(pose, list(self.bodies))}"
            ) from None

    def face(self, expression: str) -> Sprite | None:
        """``None`` when the character has no face layer at all."""
        if not self.manifest.has_face_layer:
            return None
        try:
            return self.faces[expression]
        except KeyError:
            raise AssetError(
                f"Character '{self.name}' has no expression '{expression}'. "
                f"{did_you_mean(expression, list(self.faces))}"
            ) from None

    def pose_spec(self, pose: str):
        """Geometry of a pose. Raises the same error as :meth:`body`."""
        try:
            return self.manifest.poses[pose]
        except KeyError:
            raise AssetError(
                f"Character '{self.name}' has no pose '{pose}'. "
                f"{did_you_mean(pose, list(self.manifest.poses))}"
            ) from None


@dataclass(frozen=True)
class AssetLibrary:
    """Everything an author supplied, validated and indexed by name."""

    root: Path
    characters: dict[str, Character] = field(default_factory=dict)
    objects: dict[str, Sprite] = field(default_factory=dict)
    backgrounds: dict[str, Sprite] = field(default_factory=dict)

    @classmethod
    def load(cls, root: str | Path) -> AssetLibrary:
        root = Path(root)
        if not root.is_dir():
            raise AssetError(
                f"asset library not found: {root} is not a directory. "
                f"Expected {CHARACTERS_DIR}/, {OBJECTS_DIR}/ and "
                f"{BACKGROUNDS_DIR}/ under it."
            )
        return cls(
            root=root,
            characters=_load_characters(root / CHARACTERS_DIR),
            objects=_load_flat_sprites(root / OBJECTS_DIR),
            backgrounds=_load_flat_sprites(root / BACKGROUNDS_DIR),
        )

    def character(self, name: str) -> Character:
        try:
            return self.characters[name]
        except KeyError:
            raise AssetError(
                f"Unknown character '{name}'. "
                f"{did_you_mean(name, list(self.characters))}"
            ) from None

    def obj(self, name: str) -> Sprite:
        try:
            return self.objects[name]
        except KeyError:
            raise AssetError(
                f"Unknown object '{name}'. {did_you_mean(name, list(self.objects))}"
            ) from None

    def background(self, name: str) -> Sprite:
        try:
            return self.backgrounds[name]
        except KeyError:
            raise AssetError(
                f"Unknown background '{name}'. "
                f"{did_you_mean(name, list(self.backgrounds))}"
            ) from None

    def sprites(self) -> list[Sprite]:
        """Every sprite in the library, in a stable order."""
        collected: list[Sprite] = []
        for character in sorted(self.characters.values(), key=lambda c: c.name):
            collected.extend(sorted(character.bodies.values(), key=lambda s: s.name))
            collected.extend(sorted(character.faces.values(), key=lambda s: s.name))
        collected.extend(sorted(self.objects.values(), key=lambda s: s.name))
        collected.extend(sorted(self.backgrounds.values(), key=lambda s: s.name))
        return collected

    def fingerprint(self, sprites: list[Sprite] | None = None) -> str:
        """A single hash over the sprites that went into a render.

        Order is fixed by ``name`` so the digest does not depend on filesystem
        iteration order.
        """
        chosen = self.sprites() if sprites is None else sprites
        digest = hashlib.sha256()
        for sprite in sorted(chosen, key=lambda s: (s.name, str(s.path))):
            digest.update(sprite.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(sprite.sha256.encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()


def _load_characters(directory: Path) -> dict[str, Character]:
    if not directory.is_dir():
        return {}
    characters: dict[str, Character] = {}
    for child in sorted(directory.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        character = _load_character(child)
        if character.name != child.name:
            raise AssetError(
                f"{child / MANIFEST_NAME} declares name '{character.name}' but "
                f"lives in directory '{child.name}'. The two must match: "
                f"strips reference characters by directory name."
            )
        characters[character.name] = character
    return characters


def _load_character(directory: Path) -> Character:
    manifest = load_manifest(directory / MANIFEST_NAME)
    bodies = _load_layer(
        directory / BODY_DIR,
        declared=manifest.pose_names,
        character=manifest.name,
        layer="pose",
        required=True,
    )
    faces = _load_layer(
        directory / FACE_DIR,
        declared=sorted(manifest.expressions),
        character=manifest.name,
        layer="expression",
        required=manifest.has_face_layer,
    )
    return Character(manifest=manifest, bodies=bodies, faces=faces)


def _load_layer(
    directory: Path,
    declared: list[str],
    character: str,
    layer: str,
    required: bool,
) -> dict[str, Sprite]:
    """Load one sprite folder and cross-check it against the manifest."""
    found: dict[str, Sprite] = {}
    if directory.is_dir():
        for child in sorted(directory.iterdir()):
            if child.is_dir() or child.name.startswith("."):
                continue
            if child.suffix.lower() != SPRITE_SUFFIX:
                raise AssetError(
                    f"{child} is not a {SPRITE_SUFFIX} file. Sprites must be "
                    f"PNG: the format is lossless and carries transparency, "
                    f"both of which compositing needs."
                )
            found[child.stem] = _read_sprite(child)
    elif required:
        raise AssetError(
            f"Character '{character}' declares {len(declared)} "
            f"{layer}(s) but has no {directory.name}/ directory. "
            f"Expected {directory}."
        )

    missing = [name for name in declared if name not in found]
    if missing:
        raise AssetError(
            f"Character '{character}' declares {layer}(s) "
            f"{', '.join(missing)} with no matching file. Expected "
            f"{directory / (missing[0] + SPRITE_SUFFIX)}."
        )

    undeclared = sorted(name for name in found if name not in declared)
    if undeclared:
        listing = ", ".join(declared) if declared else "(none)"
        raise AssetError(
            f"Character '{character}' has {layer} file(s) "
            f"{', '.join(undeclared)} that the manifest does not declare. "
            f"Add them under '{layer}s' in {MANIFEST_NAME}, or remove the "
            f"files. Declared: {listing}."
        )
    return found


def _load_flat_sprites(directory: Path) -> dict[str, Sprite]:
    if not directory.is_dir():
        return {}
    sprites: dict[str, Sprite] = {}
    for child in sorted(directory.iterdir()):
        if child.is_dir() or child.name.startswith("."):
            continue
        if child.suffix.lower() != SPRITE_SUFFIX:
            continue
        sprites[child.stem] = _read_sprite(child)
    return sprites


def _read_sprite(path: Path) -> Sprite:
    """Read a sprite's dimensions without decoding its pixels."""
    try:
        with Image.open(path) as image:
            width, height = image.size
    except UnidentifiedImageError as exc:
        raise AssetError(f"{path} is not a readable image.") from exc
    except OSError as exc:
        raise AssetError(f"cannot read sprite {path}: {exc}") from exc
    if width <= 0 or height <= 0:
        raise AssetError(f"sprite {path} has a zero dimension ({width}x{height}).")
    return Sprite(name=path.stem, path=path, width=width, height=height)
