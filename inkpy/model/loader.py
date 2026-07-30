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
    problems = exc.errors()
    plural = "" if len(problems) == 1 else "s"
    lines = [f"{source} is not a valid strip ({len(problems)} problem{plural}):"]
    for problem in problems:
        lines.append(f"  {_location(problem['loc'])}: {_message(problem)}")
    return "\n".join(lines)


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
    return message
