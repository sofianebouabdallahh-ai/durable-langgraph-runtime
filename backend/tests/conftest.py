"""Suite-wide test configuration."""

import pytest

from tests import problem_contract


def pytest_configure(config: pytest.Config) -> None:
    """Every API error any test sees is checked against the spec (CR-007 R19.1)."""
    problem_contract.install()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """`live` tests call a real model provider: they run only when selected explicitly
    (`pytest -m live`, `make test-live`), never by default and never in CI."""
    if "live" in (config.option.markexpr or ""):
        return
    skip = pytest.mark.skip(reason="live: run with `make test-live` (needs make llm-up)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
