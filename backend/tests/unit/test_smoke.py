"""Proves the package imports and the toolchain (pytest, mypy, ruff) is wired up."""

from pathlib import Path

import pytest

import agent_runtime
from agent_runtime.cli import main

SHIPPED_AGENTS = Path(__file__).resolve().parents[2] / "agents"


def test_package_imports() -> None:
    assert agent_runtime.__doc__


def test_cli_without_subcommand_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_cli_validates_shipped_agents() -> None:
    assert main(["agents", "validate", "--path", str(SHIPPED_AGENTS)]) == 0
