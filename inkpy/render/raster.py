"""SVG to PNG and PDF.

Rasterisation is delegated; what this module owns is the promise around it.
The render carries its own provenance — the engine version, the style, a hash
of every sprite that went into it and a hash of the strip that described it —
written into the file's metadata rather than kept in a sidecar that can drift.
``verify`` reads it back and says whether a PNG still matches the strip and the
assets it claims to come from.

All four are needed to answer that question. The sprites alone leave the strip
itself unchecked, which made a reworded line of dialogue pass as a match.

Nothing here reads the clock. A PNG produced twice from the same inputs is the
same PNG, byte for byte, which is a property that has to be testable to be
worth asserting.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, PngImagePlugin

from inkpy.errors import RenderError
from inkpy.layout.scene import Scene

VERSION_KEY = "inkpy:version"
ASSETS_KEY = "inkpy:assets"
SCRIPT_KEY = "inkpy:script"
STYLE_KEY = "inkpy:style"
TITLE_KEY = "inkpy:title"


def render_png(scene: Scene, svg: str, path: str | Path, scale: float = 1.0) -> Path:
    """Rasterise to PNG and stamp the result with its provenance."""
    path = Path(path)
    raw = _rasterise(svg, scene, scale)

    info = PngImagePlugin.PngInfo()
    info.add_text(VERSION_KEY, scene.engine_version)
    info.add_text(ASSETS_KEY, scene.asset_fingerprint)
    info.add_text(SCRIPT_KEY, scene.script_fingerprint)
    info.add_text(STYLE_KEY, scene.style.name)
    info.add_text(TITLE_KEY, scene.title)

    with Image.open(io.BytesIO(raw)) as image:
        _write(path)
        # optimize=True is deterministic for a given Pillow build and keeps the
        # embedded sprites from doubling the file size.
        image.save(path, format="PNG", pnginfo=info, optimize=True)
    return path


def render_pdf(scene: Scene, svg: str, path: str | Path) -> Path:
    """Vector export. Nearly free, since the render is already vector."""
    path = Path(path)
    cairosvg = _cairosvg()
    _write(path)
    try:
        cairosvg.svg2pdf(
            bytestring=svg.encode("utf-8"),
            write_to=str(path),
            output_width=scene.width,
            output_height=scene.height,
        )
    except Exception as exc:
        raise RenderError(f"cannot write PDF {path}: {exc}") from exc
    return path


def render_svg_file(svg: str, path: str | Path) -> Path:
    path = Path(path)
    _write(path)
    path.write_text(svg, encoding="utf-8")
    return path


def read_provenance(path: str | Path) -> dict[str, str]:
    """Read back what a PNG says about how it was made.

    Returns an empty mapping for a PNG InkPy did not produce, rather than
    raising: "this file carries no provenance" is an answer, not a failure.
    """
    path = Path(path)
    try:
        with Image.open(path) as image:
            return {
                key: value
                for key, value in (image.info or {}).items()
                if isinstance(key, str)
                and isinstance(value, str)
                and key.startswith("inkpy:")
            }
    except OSError as exc:
        raise RenderError(f"cannot read {path}: {exc}") from exc


def _rasterise(svg: str, scene: Scene, scale: float) -> bytes:
    if scale <= 0:
        raise RenderError(f"scale must be positive, got {scale}.")
    cairosvg = _cairosvg()
    try:
        return cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            output_width=round(scene.width * scale),
            output_height=round(scene.height * scale),
        )
    except Exception as exc:
        raise RenderError(f"rasterisation failed: {exc}") from exc


def _cairosvg():
    """Imported late: the layout engine and its tests must not need Cairo."""
    try:
        import cairosvg
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RenderError(
            "rasterising needs cairosvg and its Cairo library. Install with "
            "'pip install cairosvg', or export SVG instead with "
            "'inkpy render --format svg'."
        ) from exc
    return cairosvg


def _write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
