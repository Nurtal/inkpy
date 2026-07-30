"""Cross-checking a script against a library.

Layout resolves assets one at a time and would stop at the first missing one.
An author fixing a strip would rather see every dangling reference at once, so
this pass runs first and reports them together.
"""

from __future__ import annotations

from inkpy.assets.library import AssetLibrary
from inkpy.errors import AssetError, did_you_mean
from inkpy.model.script import ComicScript


def check_script(script: ComicScript, library: AssetLibrary) -> None:
    """Raise if the script references anything the library cannot provide."""
    problems: list[str] = []

    for panel in script.panels:
        if panel.background is not None and panel.background not in library.backgrounds:
            problems.append(
                f"panel {panel.id}: unknown background '{panel.background}'. "
                f"{did_you_mean(panel.background, list(library.backgrounds))}"
            )

        for prop in panel.objects:
            if prop.name not in library.objects:
                problems.append(
                    f"panel {panel.id}: unknown object '{prop.name}'. "
                    f"{did_you_mean(prop.name, list(library.objects))}"
                )

        for actor in panel.actors:
            character = library.characters.get(actor.character)
            if character is None:
                problems.append(
                    f"panel {panel.id}: unknown character '{actor.character}'. "
                    f"{did_you_mean(actor.character, list(library.characters))}"
                )
                continue

            if actor.pose not in character.bodies:
                problems.append(
                    f"panel {panel.id}: character '{actor.character}' has no "
                    f"pose '{actor.pose}'. "
                    f"{did_you_mean(actor.pose, list(character.bodies))}"
                )
            if character.manifest.has_face_layer:
                if actor.expression not in character.faces:
                    problems.append(
                        f"panel {panel.id}: character '{actor.character}' has "
                        f"no expression '{actor.expression}'. "
                        f"{did_you_mean(actor.expression, list(character.faces))}"
                    )
            elif actor.expression != "neutral":
                problems.append(
                    f"panel {panel.id}: character '{actor.character}' has no "
                    f"face layer, so expression '{actor.expression}' cannot be "
                    f"applied. Remove the field, or add expressions to its "
                    f"manifest."
                )
            if actor.flip and not character.manifest.flippable:
                problems.append(
                    f"panel {panel.id}: character '{actor.character}' is not "
                    f"flippable, but 'flip: true' was requested. Set "
                    f"'flippable: true' in its manifest if mirroring is safe "
                    f"for this artwork."
                )

    if problems:
        plural = "" if len(problems) == 1 else "s"
        listing = "\n".join(f"  {problem}" for problem in problems)
        raise AssetError(
            f"'{script.title}' references {len(problems)} missing or "
            f"inapplicable asset{plural}:\n{listing}"
        )
