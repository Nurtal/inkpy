"""Layout: authorial intent in, resolved geometry out."""

from inkpy.layout.actors import PlacedActor, Placement, place_panel_contents
from inkpy.layout.bubbles import layout_bubbles, wrap_text
from inkpy.layout.compose import build_scene
from inkpy.layout.page import content_area, panel_rects
from inkpy.layout.scene import (
    Bubble,
    DrawKind,
    Mark,
    PanelScene,
    Scene,
    SpriteDraw,
    Tail,
    TextLine,
)

__all__ = [
    "Bubble",
    "DrawKind",
    "Mark",
    "PanelScene",
    "PlacedActor",
    "Placement",
    "Scene",
    "SpriteDraw",
    "Tail",
    "TextLine",
    "build_scene",
    "content_area",
    "layout_bubbles",
    "panel_rects",
    "place_panel_contents",
    "wrap_text",
]
