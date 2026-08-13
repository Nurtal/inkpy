"""Reading a strip file into a validated ``ComicScript``.

Pydantic's own ``ValidationError`` is precise but reads like a stack trace. It
gets reshaped here into something an author can act on, keyed by the YAML path
that caused it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from inkpy.errors import ScriptError
from inkpy.model.script import ComicScript

ROOT_KEY = "comic"


def load_script(path: str | Path) -> ComicScript:
    """Parse and validate a strip file."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ScriptError(f"strip file not found: {path}") from exc
    except OSError as exc:
        raise ScriptError(f"cannot read strip file {path}: {exc}") from exc
    return parse_script(raw, source=str(path))


def parse_script(text: str, source: str = "<string>") -> ComicScript:
    """Parse and validate a strip from YAML text."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ScriptError(f"{source} is not valid YAML: {exc}") from exc

    if document is None:
        raise ScriptError(f"{source} is empty.")
    if not isinstance(document, dict):
        raise ScriptError(
            f"{source} must be a mapping with a top-level '{ROOT_KEY}:' key, "
            f"got {type(document).__name__}."
        )
    if ROOT_KEY not in document:
        keys = ", ".join(sorted(map(str, document))) or "(none)"
        raise ScriptError(
            f"{source} has no top-level '{ROOT_KEY}:' key. Found: {keys}."
        )
    extra = sorted(k for k in document if k != ROOT_KEY)
    if extra:
        raise ScriptError(
            f"{source} has unexpected top-level keys: {', '.join(map(str, extra))}. "
            f"Everything belongs under '{ROOT_KEY}:'."
        )

    body = document[ROOT_KEY]
    if not isinstance(body, dict):
        raise ScriptError(
            f"{source}: '{ROOT_KEY}:' must be a mapping, "
            f"got {type(body).__name__}."
        )

    try:
        return ComicScript.model_validate(body)
    except ValidationError as exc:
        raise ScriptError(format_validation_error(exc, source)) from exc


def format_validation_error(exc: ValidationError, source: str) -> str:
    """Turn a Pydantic error into an author-facing report."""
    problems = _without_consequences(exc.errors())
    plural = "" if len(problems) == 1 else "s"
    lines = [f"{source} is not a valid strip ({len(problems)} problem{plural}):"]
    for problem in problems:
        lines.append(f"  {_location(problem['loc'])}: {_message(problem)}")
    return "\n".join(lines)


def _without_consequences(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the errors that are only side effects of other errors.

    Pydantic removes an item that failed validation and *then* checks how many
    are left, so one misspelt field inside the only panel of a strip is
    reported twice: once where it is, and once as ``panels`` being empty. The
    second is not a problem the author has — fixing it is not even possible —
    and counting it made the report open by claiming two.

    Only a length complaint about a container that already has a failing child
    is dropped. A genuinely empty ``panels:`` has no child to blame and is
    reported as itself.
    """
    locations = [problem["loc"] for problem in problems]
    return [
        problem
        for problem in problems
        if problem.get("type") != "too_short"
        or not any(_is_inside(loc, problem["loc"]) for loc in locations)
    ]


def _is_inside(loc: tuple[Any, ...], container: tuple[Any, ...]) -> bool:
    """Is ``loc`` strictly below ``container`` in the document tree?"""
    return len(loc) > len(container) and loc[: len(container)] == container


def _location(loc: tuple[Any, ...]) -> str:
    """Render a Pydantic error location as a YAML-ish path."""
    if not loc:
        return ROOT_KEY
    parts: list[str] = [ROOT_KEY]
    for item in loc:
        if isinstance(item, int):
            parts[-1] = f"{parts[-1]}[{item}]"
        else:
            parts.append(str(item))
    return ".".join(parts)


def _message(problem: dict[str, Any]) -> str:
    """Prefer our own validator text; rewrite Pydantic's terser codes."""
    kind = problem.get("type", "")
    message = problem.get("msg", "invalid value")
    if kind == "value_error":
        # Raised by our own model validators: the message is already written
        # for an author, minus Pydantic's "Value error, " prefix.
        return message.removeprefix("Value error, ")
    if kind == "extra_forbidden":
        return "unknown field. Check the spelling against the field reference."
    if kind == "missing":
        return "required field is missing."
    if kind == "string_pattern_mismatch":
        return (
            "asset names must be lowercase letters, digits, '_' or '-', "
            f"and start with a letter or digit (got {problem.get('input')!r})."
        )
    if kind in {"too_short", "too_long"}:
        # Pydantic says "Tuple should have at most 4 items after validation",
        # and "after validation" is a fact about the validator, not about the
        # file. The author wants the two numbers.
        context = problem.get("ctx", {})
        given = context.get("actual_length", "?")
        if kind == "too_short":
            least = context.get("min_length", 1)
            return f"too few entries: at least {least} required, {given} given."
        most = context.get("max_length", "?")
        return f"too many entries: at most {most} allowed, {given} given."
    return message
