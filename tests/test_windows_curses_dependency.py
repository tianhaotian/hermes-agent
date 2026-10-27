"""Windows CLI menus need the curses extension in a managed install (#144124)."""

import importlib
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement


@pytest.mark.parametrize(
    "system,machine,implementation,python_version,expected",
    [
        ("win32", "AMD64", "CPython", "3.14", True),
        ("win32", "x86", "CPython", "3.14", True),
        ("win32", "ARM64", "CPython", "3.14", False),
        ("win32", "AMD64", "PyPy", "3.14", False),
        ("win32", "AMD64", "CPython", "3.13", False),
        ("darwin", "arm64", "CPython", "3.14", False),
        ("linux", "x86_64", "CPython", "3.14", False),
    ],
)
def test_curses_dependency_matches_supported_windows_runtime(
    system, machine, implementation, python_version, expected,
):
    """Supply the shim where wheels exist without breaking other install targets."""
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    environment = {
        "sys_platform": system,
        "platform_machine": machine,
        "platform_python_implementation": implementation,
        "python_version": python_version,
    }
    selected = {
        requirement.name
        for requirement in map(Requirement, project["dependencies"])
        if requirement.marker is None or requirement.marker.evaluate(environment)
    }
    assert ("windows-curses" in selected) is expected


@pytest.mark.platforms("windows", arch="x86_64")
def test_managed_windows_runtime_can_import_the_menu_backend():
    """Exercise the same real import that selects the interactive plugins UI."""
    curses = importlib.import_module("curses")
    assert callable(curses.wrapper)
    assert callable(curses.initscr)
