"""The smoke test, run as a test.

The README documents four commands: draw a library, check, render, verify.
They are what someone runs on a fresh clone to find out whether the engine
works at all, so they are worth knowing to still work — a procedure that only
exists in prose rots the first time a flag is renamed.

This is deliberately end-to-end where the rest of the suite is not. It goes
through the real CLI, over a library drawn by the real generator, and it never
skips: unlike ``TestTheShippedExample`` it draws its own assets into a
temporary directory, so a checkout that has never run a generator still runs
it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from inkpy.cli import app
from inkpy.render.raster import read_provenance

runner = CliRunner()

REPO = Path(__file__).parent.parent
README = REPO / "README.md"
HELLO = REPO / "examples" / "hello"
GENERATOR = HELLO / "make_hello.py"
STRIP = HELLO / "hello.yaml"

STEPS = (
    "python examples/hello/make_hello.py",
    "inkpy check examples/hello/hello.yaml",
    "inkpy render examples/hello/hello.yaml -o out/hello.png",
    "inkpy verify examples/hello/hello.yaml out/hello.png",
)
"""The documented procedure, one string per step."""


@pytest.fixture(scope="module")
def library(tmp_path_factory) -> Path:
    """Step 1, run the way the README spells it: the script, from the shell."""
    root = tmp_path_factory.mktemp("hello") / "assets"
    done = subprocess.run(
        [sys.executable, str(GENERATOR), str(root)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("wrote the hello library to")
    return root


def run(*args: str):
    return runner.invoke(app, list(args))


def test_the_generator_draws_a_library_the_strip_can_name(library):
    """One character, one pose, one expression, one background: the minimum."""
    result = run("assets", "list", str(library))
    assert result.exit_code == 0, result.output
    assert "character blob" in result.output
    assert "poses:       idle" in result.output
    assert "expressions: neutral" in result.output
    assert "backgrounds: room" in result.output


def test_check_passes_without_warnings(library):
    """Step 2. A smoke test that warns teaches people to ignore warnings."""
    result = run("check", str(STRIP), "-a", str(library))
    assert result.exit_code == 0, result.output
    assert "1 panels, 1 bubbles, 0 warnings" in result.output


def test_render_produces_the_page(library, tmp_path):
    """Step 3, and the whole point: a YAML file becomes a picture."""
    out = tmp_path / "hello.png"
    result = run("render", str(STRIP), "-a", str(library), "-o", str(out))
    assert result.exit_code == 0, result.output
    with Image.open(out) as image:
        assert image.size == (800, 600)


def test_the_render_verifies_against_its_sources(library, tmp_path):
    """Step 4: the PNG carries where it came from, and says so."""
    out = tmp_path / "hello.png"
    run("render", str(STRIP), "-a", str(library), "-o", str(out))
    assert read_provenance(out)["inkpy:title"] == "Hello, InkPy"
    result = run("verify", str(STRIP), str(out), "-a", str(library))
    assert result.exit_code == 0, result.output
    assert "matches" in result.output


def test_two_renders_are_byte_identical(library, tmp_path):
    """The promise the project is built on, on the smallest case there is."""
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    for out in (first, second):
        run("render", str(STRIP), "-a", str(library), "-o", str(out))
    assert first.read_bytes() == second.read_bytes()


def test_the_readme_documents_these_exact_steps():
    """The test and the instructions have to be the same four commands.

    Asserted rather than assumed: this file is only useful as a guard on the
    procedure people actually follow, and that one lives in the README.
    """
    prose = re.sub(r"\s+", " ", README.read_text(encoding="utf-8"))
    missing = [step for step in STEPS if step not in prose]
    assert not missing, f"README no longer documents: {missing}"
