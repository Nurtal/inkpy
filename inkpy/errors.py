"""Error hierarchy.

Every error raised by InkPy carries a message meant to be read by the author of
a strip, not by a Python developer: it names the offending element, says what
was expected, and lists what was available. The test suite asserts on these
messages.
"""

from __future__ import annotations


class InkPyError(Exception):
    """Base class for every error InkPy raises deliberately."""


class ScriptError(InkPyError):
    """The strip file is malformed or internally inconsistent."""


class AssetError(InkPyError):
    """The asset library is missing something, or declares something it lacks."""


class LayoutError(InkPyError):
    """The requested composition cannot be resolved into a scene."""


class RenderError(InkPyError):
    """The scene cannot be turned into pixels."""


def did_you_mean(name: str, available: list[str]) -> str:
    """Render an ``Available x: a, b, c`` suffix, with a suggestion when close.

    Kept deliberately simple: no edit-distance library, just a prefix match,
    which covers the common typo of a truncated or over-long name.
    """
    ordered = sorted(available)
    listing = ", ".join(ordered) if ordered else "(none)"
    lowered = name.lower()
    for candidate in ordered:
        low = candidate.lower()
        if low.startswith(lowered) or lowered.startswith(low):
            return f"Did you mean '{candidate}'? Available: {listing}."
    return f"Available: {listing}."
