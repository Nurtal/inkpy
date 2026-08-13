"""The command line.

One verb for v0.1. ``inkpy render strip.yaml`` and a PNG comes out — that is
the whole exit criterion, and the CLI has no business being larger than it.

Errors are the interesting part. Everything InkPy raises deliberately is an
``InkPyError`` carrying a message written for the person editing the strip, so
they are printed as-is and exit non-zero, with no traceback. A traceback here
would only ever mean a bug in the engine, and that one is worth seeing in full.
"""

from __future__ import annotations

import json
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from inkpy import __version__
from inkpy.assets.library import AssetLibrary
from inkpy.errors import InkPyError
from inkpy.layout.compose import build_scene
from inkpy.layout.scene import Scene
from inkpy.model.loader import ROOT_KEY, load_script
from inkpy.model.script import ComicScript
from inkpy.render.raster import (
    ASSETS_KEY,
    SCRIPT_KEY,
    STYLE_KEY,
    TITLE_KEY,
    VERSION_KEY,
    read_provenance,
    render_pdf,
    render_png,
    render_svg_file,
)
from inkpy.render.svg import SvgOptions, render_svg
from inkpy.styles.theme import get_style, style_names

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Assemble short comic strips from a description and a library of assets.",
)


class Format(str, Enum):
    PNG = "png"
    SVG = "svg"
    PDF = "pdf"


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _resolve_assets(strip: Path, given: Path | None) -> Path:
    """Assets live beside the strip unless told otherwise."""
    if given is not None:
        return given
    return strip.parent / "assets"


@app.command()
def render(
    strip: Annotated[Path, typer.Argument(help="The strip file to render.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output file. Defaults to the strip's name."),
    ] = None,
    assets: Annotated[
        Path | None,
        typer.Option("--assets", "-a", help="Asset library. Defaults to ./assets next to the strip."),
    ] = None,
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="Output format.")
    ] = Format.PNG,
    style: Annotated[
        str | None,
        typer.Option("--style", "-s", help=f"Override the strip's style. One of: {', '.join(style_names())}."),
    ] = None,
    scale: Annotated[
        float, typer.Option("--scale", help="Multiply the output resolution.")
    ] = 1.0,
    wireframe: Annotated[
        bool,
        typer.Option("--wireframe", help="Overlay bounding boxes, anchors and reserved zones."),
    ] = False,
    bare: Annotated[
        bool,
        typer.Option("--bare", help="With --wireframe, drop the artwork and keep the diagram."),
    ] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress warnings.")] = False,
) -> None:
    """Render a strip to PNG, SVG or PDF."""
    try:
        script = load_script(strip)
        library = AssetLibrary.load(_resolve_assets(strip, assets))
        theme = get_style(style) if style else None
        scene = build_scene(script, library, theme)
        svg = render_svg(
            scene,
            SvgOptions(wireframe=wireframe, artwork=not (bare and wireframe)),
        )

        destination = out or strip.with_suffix(f".{fmt.value}")
        if fmt is Format.SVG:
            written = render_svg_file(svg, destination)
        elif fmt is Format.PDF:
            written = render_pdf(scene, svg, destination)
        else:
            written = render_png(scene, svg, destination, scale=scale)
    except InkPyError as exc:
        _fail(str(exc))
        return

    if not quiet:
        for warning in scene.all_warnings():
            typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)
    typer.echo(f"{written} ({scene.width}x{scene.height}, {len(scene.panels)} panels)")


@app.command()
def check(
    strip: Annotated[Path, typer.Argument(help="The strip file to validate.")],
    assets: Annotated[Path | None, typer.Option("--assets", "-a")] = None,
) -> None:
    """Validate a strip and its assets, and report what layout would warn about.

    Everything ``render`` does except writing a file, which makes it the fast
    way to find a typo in a pose name without waiting on a rasteriser.
    """
    try:
        script = load_script(strip)
        library = AssetLibrary.load(_resolve_assets(strip, assets))
        scene = build_scene(script, library)
    except InkPyError as exc:
        _fail(str(exc))
        return

    warnings = scene.all_warnings()
    for warning in warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)
    typer.echo(
        f"{strip}: {len(scene.panels)} panels, "
        f"{sum(len(p.bubbles) for p in scene.panels)} bubbles, "
        f"{len(warnings)} warnings"
    )


@app.command()
def verify(
    strip: Annotated[Path, typer.Argument(help="The strip the render claims to come from.")],
    image: Annotated[Path, typer.Argument(help="The PNG to check.")],
    assets: Annotated[Path | None, typer.Option("--assets", "-a")] = None,
    style: Annotated[
        str | None,
        typer.Option("--style", "-s", help="The style the image was rendered with, if not the strip's."),
    ] = None,
) -> None:
    """Check that a PNG still matches its strip and its assets.

    "Same input, same output" is worth stating only if it can be checked. Four
    things are written into the PNG at render time — the engine version, the
    style, a hash of every sprite used and a hash of the strip itself — and
    this recomputes all four from the sources and compares.

    The strip's hash is the one that makes the check worth running: without it
    a reworded line of dialogue passed as a match, because the artwork it was
    spoken over had not moved.
    """
    try:
        script = load_script(strip)
        library = AssetLibrary.load(_resolve_assets(strip, assets))
        theme = get_style(style) if style else None
        scene = build_scene(script, library, theme)
        stamped = read_provenance(image)
    except InkPyError as exc:
        _fail(str(exc))
        return

    if not stamped:
        _fail(f"{image} carries no InkPy provenance. It was not produced by this engine.")
        return

    problems: list[str] = []
    if stamped.get(ASSETS_KEY) != scene.asset_fingerprint:
        problems.append(
            f"assets differ: the image was rendered from {stamped.get(ASSETS_KEY, '?')[:12]}…, "
            f"the library now hashes to {scene.asset_fingerprint[:12]}…"
        )
    if stamped.get(VERSION_KEY) != scene.engine_version:
        problems.append(
            f"engine differs: rendered with {stamped.get(VERSION_KEY, '?')}, "
            f"running {scene.engine_version}"
        )
    problems.extend(_strip_problems(stamped, scene, strip))

    if problems:
        for problem in problems:
            typer.secho(f"  {problem}", fg=typer.colors.RED, err=True)
        _fail(f"{image} is out of date with respect to {strip}.")
        return
    typer.secho(f"{image} matches {strip}.", fg=typer.colors.GREEN)


def _strip_problems(stamped: dict[str, str], scene: Scene, strip: Path) -> list[str]:
    """What the image says it was rendered from, against what the strip says now.

    One message per cause. The title is part of the strip's hash, so a
    retitled strip already fails the general check — but "title differs" in
    those words is worth saying, and saying it twice is not.
    """
    problems: list[str] = []

    stamped_style = stamped.get(STYLE_KEY)
    if stamped_style != scene.style.name:
        named = repr(stamped_style) if stamped_style else "a style it did not record"
        hint = f" Re-check with --style {stamped_style}." if stamped_style else ""
        problems.append(
            f"style differs: the image was rendered with {named}, "
            f"this check used {scene.style.name!r}.{hint}"
        )

    if stamped.get(TITLE_KEY) != scene.title:
        problems.append(
            f"title differs: image says {stamped.get(TITLE_KEY, '?')!r}, "
            f"strip says {scene.title!r}"
        )
    elif SCRIPT_KEY not in stamped:
        problems.append(
            "the image records no hash of the strip it came from, so what it "
            "says cannot be checked. Re-render it."
        )
    elif stamped[SCRIPT_KEY] != scene.script_fingerprint:
        problems.append(
            f"the strip differs: the image was rendered from content hashing to "
            f"{stamped[SCRIPT_KEY][:12]}…, {strip} now hashes to "
            f"{scene.script_fingerprint[:12]}…"
        )
    return problems


@app.command()
def watch(
    strip: Annotated[Path, typer.Argument(help="The strip file to watch.")],
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    assets: Annotated[Path | None, typer.Option("--assets", "-a")] = None,
    fmt: Annotated[Format, typer.Option("--format", "-f")] = Format.PNG,
    wireframe: Annotated[bool, typer.Option("--wireframe")] = False,
    interval: Annotated[
        float, typer.Option("--interval", help="Seconds between checks.")
    ] = 0.4,
) -> None:
    """Re-render whenever the strip or any of its assets changes.

    Polling rather than filesystem events: one fewer dependency, and at these
    scales the difference is imperceptible. An error does not stop the watch —
    a typo you are in the middle of fixing is the normal case here, so it is
    reported and the loop keeps going.
    """
    library_root = _resolve_assets(strip, assets)
    destination = out or strip.with_suffix(f".{fmt.value}")
    typer.echo(f"watching {strip} and {library_root} — Ctrl-C to stop")

    previous: dict[Path, float] | None = None
    try:
        while True:
            current = _snapshot(strip, library_root)
            if current != previous:
                previous = current
                _render_once(strip, library_root, destination, fmt, wireframe)
            time.sleep(interval)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        typer.echo("\nstopped")


def _snapshot(strip: Path, library_root: Path) -> dict[Path, float]:
    """Modification times of everything a render depends on."""
    watched = [strip, *sorted(library_root.rglob("*"))]
    stamps: dict[Path, float] = {}
    for path in watched:
        try:
            if path.is_file():
                stamps[path] = path.stat().st_mtime
        except OSError:
            # A file being written as we look at it: the next tick will see it.
            continue
    return stamps


def _render_once(
    strip: Path, library_root: Path, destination: Path, fmt: Format, wireframe: bool
) -> None:
    try:
        script = load_script(strip)
        library = AssetLibrary.load(library_root)
        scene = build_scene(script, library)
        svg = render_svg(scene, SvgOptions(wireframe=wireframe))
        if fmt is Format.SVG:
            render_svg_file(svg, destination)
        elif fmt is Format.PDF:
            render_pdf(scene, svg, destination)
        else:
            render_png(scene, svg, destination)
    except InkPyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        return
    for warning in scene.all_warnings():
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)
    typer.secho(f"wrote {destination}", fg=typer.colors.GREEN)


@app.command()
def schema(
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write to a file instead of stdout."),
    ] = None,
) -> None:
    """Export the strip format as JSON Schema.

    Free, because the schema is already declared: Pydantic derives this from
    the same models that do the validating, so an editor's autocompletion can
    never drift from what the engine actually accepts.
    """
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"InkPy strip ({__version__})",
        "type": "object",
        "required": [ROOT_KEY],
        "additionalProperties": False,
        "properties": {ROOT_KEY: ComicScript.model_json_schema()},
    }
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if out is None:
        typer.echo(text, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"{out} ({len(text)} bytes)")


assets_app = typer.Typer(no_args_is_help=True, help="Inspect an asset library.")
app.add_typer(assets_app, name="assets")


@assets_app.command("list")
def assets_list(
    library: Annotated[
        Path, typer.Argument(help="The asset library to inspect.")
    ] = Path("assets"),
) -> None:
    """List what a library provides, so a strip can be written against it."""
    try:
        loaded = AssetLibrary.load(library)
    except InkPyError as exc:
        _fail(str(exc))
        return

    typer.secho(f"{library}", bold=True)
    if not loaded.characters:
        typer.echo("  characters: (none)")
    for character in sorted(loaded.characters.values(), key=lambda c: c.name):
        manifest = character.manifest
        typer.echo(f"  character {character.name}")
        typer.echo(
            f"    poses:       {', '.join(sorted(character.bodies))}"
        )
        typer.echo(
            f"    expressions: {', '.join(sorted(character.faces)) or '(none)'}"
        )
        typer.echo(
            f"    height {manifest.default_height:.2f} of the panel"
            f"{', flippable' if manifest.flippable else ''}"
        )
    typer.echo(f"  objects:     {', '.join(sorted(loaded.objects)) or '(none)'}")
    typer.echo(f"  backgrounds: {', '.join(sorted(loaded.backgrounds)) or '(none)'}")
    typer.echo(f"  fingerprint: {loaded.fingerprint()[:16]}…")


@app.command()
def styles() -> None:
    """List the styles a strip may name."""
    for name in style_names():
        typer.echo(name)


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(f"inkpy {__version__}")


def main() -> None:  # pragma: no cover - entry point
    try:
        app()
    except InkPyError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":  # pragma: no cover
    main()
