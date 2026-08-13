"""Assembling a scene: the composition order, in one place.

    1. Background
    2. Reserve bubble space        <- before anything is placed
    3. Place characters in what is left
    4. Objects
    5. Bubbles and text
    6. Panel frame                 <- the backend's job

Step 2 is the one that is easy to get wrong and impossible to fix later. Place
characters first and the bubbles have nowhere to go but over their heads.
"""

from __future__ import annotations

from inkpy import __version__
from inkpy.assets.library import AssetLibrary, Sprite
from inkpy.assets.validate import check_script
from inkpy.geometry import Rect
from inkpy.layout.actors import place_panel_contents
from inkpy.layout.bubbles import band_for, layout_bubbles, plan_bubbles
from inkpy.layout.effects import effect_bounds, place_effects
from inkpy.layout.page import panel_rects
from inkpy.layout.scene import DrawKind, Mark, PanelScene, Scene, SpriteDraw
from inkpy.model.script import ComicScript, Panel
from inkpy.styles.theme import PanelStyle, Style, get_style


def build_scene(
    script: ComicScript,
    library: AssetLibrary,
    style: Style | None = None,
) -> Scene:
    """Turn authorial intent into resolved geometry.

    Pure: same script and same library in, same scene out. Nothing is read
    from the environment, no collection is iterated out of order.
    """
    check_script(script, library)
    theme = style if style is not None else get_style(script.style)
    rects = panel_rects(script.page, script.layout)
    page_side = float(min(script.page.width, script.page.height))

    panels: list[PanelScene] = []
    used: list[Sprite] = []
    for panel, rect in zip(script.panels, rects):
        scene_panel, panel_sprites = _build_panel(panel, rect, library, theme, page_side)
        panels.append(scene_panel)
        used.extend(panel_sprites)

    return Scene(
        title=script.title,
        width=script.page.width,
        height=script.page.height,
        style=theme,
        panels=tuple(panels),
        engine_version=__version__,
        asset_fingerprint=library.fingerprint(used),
        script_fingerprint=script.fingerprint(),
        background_colour=theme.page_colour,
    )


def _build_panel(
    panel: Panel,
    rect: Rect,
    library: AssetLibrary,
    theme: Style,
    page_side: float,
) -> tuple[PanelScene, list[Sprite]]:
    style = PanelStyle.resolve(theme, rect, page_side)

    # 1. Background.
    background = _background_draw(panel, rect, library)

    # 2. Reserve, but only when something will actually be said: a silent panel
    #    has no reason to give up a third of its height.
    #
    #    The reservation and the mouths it points at depend on each other, so
    #    this converges rather than solves. Against the style's nominal band,
    #    place the cast well enough to know where everyone's mouth is; measure
    #    the dialogue and lay the bubbles out; then re-place the cast against
    #    the bubbles' actual rectangles instead of the whole band. A character
    #    standing under a gap between two bubbles keeps its full height, which
    #    a full-width band would have cost it for nothing.
    #
    #    Two rounds is the fixed point in practice: re-placing only ever
    #    changes a character's height, a mouth moves by a fraction of its own
    #    sprite, and no bubble changes rows over that.
    reserved: tuple[Rect, ...] = ()
    band: Rect | None = None
    if panel.dialogue:
        draft = place_panel_contents(panel, rect, library, (style.band,))
        band = band_for(plan_bubbles(panel, rect, draft, style), rect, style)
        provisional = layout_bubbles(panel, rect, draft, style, band=band)
        reserved = tuple(bubble.rect for bubble in provisional.bubbles)

    # 3 and 4. Characters, then objects, z-sorted together.
    placement = place_panel_contents(panel, rect, library, reserved)

    # 5. Bubbles, now that the mouths they point at have real coordinates.
    bubbles = layout_bubbles(panel, rect, placement, style, band=band)

    draws: tuple[SpriteDraw, ...] = placement.draws
    if background is not None:
        draws = (background,) + draws

    # 4, continued: effects sit at the end of the artwork, in front of it.
    effects = place_effects(panel, rect)

    marks = (Mark(kind="panel", label=str(panel.id), rect=rect),)
    marks += placement.marks + bubbles.marks
    marks += tuple(
        Mark(kind="effect", label=strokes.kind.value, rect=effect_bounds(strokes))
        for strokes in effects
    )

    sprites = [draw.sprite for draw in draws]
    return (
        PanelScene(
            id=panel.id,
            rect=rect,
            draws=draws,
            effects=effects,
            bubbles=bubbles.bubbles,
            marks=marks,
            warnings=placement.warnings + bubbles.warnings,
            frame_weight=panel.frame.weight,
        ),
        sprites,
    )


def _background_draw(
    panel: Panel, rect: Rect, library: AssetLibrary
) -> SpriteDraw | None:
    """Scale a background to cover its panel, keeping its aspect ratio.

    Cover rather than fit: a letterboxed background would show the page
    through the gap. The overflow is clipped to the panel by the backend.
    """
    if panel.background is None:
        return None
    sprite = library.background(panel.background)
    scale = max(rect.width / sprite.width, rect.height / sprite.height)
    width = sprite.width * scale
    height = sprite.height * scale
    return SpriteDraw(
        sprite=sprite,
        rect=Rect(
            rect.center.x - width / 2,
            rect.center.y - height / 2,
            width,
            height,
        ),
        kind=DrawKind.BACKGROUND,
        label=panel.background,
        z=-1_000_000,
        order=-1,
    )
