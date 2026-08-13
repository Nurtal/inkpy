"""What the package declares, against what its code imports.

Two dependencies have shipped undeclared. fonttools, without which nothing in
the engine imported at all — a clean install produced a package that failed on
``import inkpy``. Then numpy, without which the rat generator stopped at its
first line. Both were found by someone running into them.

The check is cheap enough to make once and keep: walk the imports, subtract
the standard library and this repository's own packages, and require what is
left to appear in pyproject.toml.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).parent.parent
PYPROJECT = REPO / "pyproject.toml"

DISTRIBUTION = {"PIL": "pillow", "yaml": "pyyaml", "fontTools": "fonttools"}
"""Import name to distribution name, for the few where the two differ."""


def declared(*extras: str) -> set[str]:
    """The runtime dependencies, plus the named optional groups."""
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = document["project"]
    requirements = list(project["dependencies"])
    for extra in extras:
        requirements.extend(project["optional-dependencies"][extra])
    return {re.split(r"[<>=!~\[ ]", line, maxsplit=1)[0].lower() for line in requirements}


def imported(directory: Path) -> set[str]:
    """Third-party top-level modules imported anywhere under ``directory``.

    Imports inside functions count: ``inkpy.render.raster`` defers cairosvg so
    that layout never needs Cairo, and a deferred dependency is still one.
    """
    modules: set[str] = set()
    for path in sorted(directory.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return {
        DISTRIBUTION.get(module, module).lower()
        for module in modules
        if module not in sys.stdlib_module_names
        and not (REPO / module).is_dir()  # inkpy and tests are ours
    }


def test_the_engine_declares_what_it_imports():
    assert imported(REPO / "inkpy") <= declared()


def test_the_examples_declare_what_they_import():
    """They are not the engine, but they are run from this repository."""
    assert imported(REPO / "examples") <= declared("examples")


def test_the_test_suite_declares_what_it_imports():
    assert imported(REPO / "tests") <= declared("dev", "examples")


def test_the_engine_does_not_depend_on_the_extras():
    """dev and examples are extras because nothing in inkpy/ reaches for them."""
    assert not imported(REPO / "inkpy") & (declared("dev", "examples") - declared())
