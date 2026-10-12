"""Proves the package imports and the toolchain (pytest, mypy, ruff) is wired up."""

import runtime
from runtime.cli import main


def test_package_imports() -> None:
    assert runtime.__doc__


def test_cli_without_subcommand_fails() -> None:
    assert main() == 1
