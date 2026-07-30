"""Shared fixtures.

Test assets are generated rather than committed: a few coloured rectangles are
enough to exercise loading, anchoring and compositing, and generating them
keeps the repository free of binary blobs that nobody can review in a diff.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image

from inkpy.assets import AssetLibrary


def write_sprite(path: Path, size: tuple[int, int], colour: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, colour).save(path)


def write_manifest(directory: Path, manifest: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "character.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )


CAT_MANIFEST = {
    "name": "cat",
    "anchor": "feet",
    "default_height": 0.45,
    "flippable": True,
    "poses": {
        "idle": {"head_anchor": [0.50, 0.78], "mouth_offset": [0.55, 0.74]},
        "sitting": {"head_anchor": [0.48, 0.66], "mouth_offset": [0.53, 0.62]},
    },
    "expressions": ["neutral", "bored"],
}

HUMAN_MANIFEST = {
    "name": "human",
    "anchor": "feet",
    "default_height": 0.70,
    "flippable": True,
    "poses": {"idle": {"head_anchor": [0.50, 0.88], "mouth_offset": [0.52, 0.85]}},
    "expressions": ["neutral", "happy"],
}


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    """A minimal but complete asset library on disk."""
    root = tmp_path / "assets"

    cat = root / "characters" / "cat"
    write_manifest(cat, CAT_MANIFEST)
    write_sprite(cat / "body" / "idle.png", (120, 200), "#8899aa")
    write_sprite(cat / "body" / "sitting.png", (140, 160), "#8899aa")
    write_sprite(cat / "face" / "neutral.png", (48, 48), "#ffddaa")
    write_sprite(cat / "face" / "bored.png", (48, 48), "#ffccaa")

    human = root / "characters" / "human"
    write_manifest(human, HUMAN_MANIFEST)
    write_sprite(human / "body" / "idle.png", (100, 300), "#aa9988")
    write_sprite(human / "face" / "neutral.png", (52, 52), "#ffeecc")
    write_sprite(human / "face" / "happy.png", (52, 52), "#ffeebb")

    write_sprite(root / "objects" / "mug.png", (60, 70), "#cc4433")
    write_sprite(root / "backgrounds" / "kitchen.png", (1200, 900), "#ddeeff")
    write_sprite(root / "backgrounds" / "garden.png", (1200, 900), "#cceecc")
    return root


@pytest.fixture
def library(library_root: Path) -> AssetLibrary:
    return AssetLibrary.load(library_root)


@pytest.fixture
def three_across(library_root: Path) -> AssetLibrary:
    """A library with a third character, for staging a panel with no gaps.

    Three heads spread across a panel leave a bubble nowhere to shift to,
    which is the case collision resolution has to give up on out loud.
    """
    second = library_root / "characters" / "cat2"
    write_manifest(second, dict(CAT_MANIFEST, name="cat2"))
    write_sprite(second / "body" / "idle.png", (120, 200), "#99aabb")
    write_sprite(second / "body" / "sitting.png", (140, 160), "#99aabb")
    write_sprite(second / "face" / "neutral.png", (48, 48), "#ffddaa")
    write_sprite(second / "face" / "bored.png", (48, 48), "#ffccaa")
    return AssetLibrary.load(library_root)
