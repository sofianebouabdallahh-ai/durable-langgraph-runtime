"""Suite-wide test configuration."""

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """`live` tests call a real model provider: they run only when selected explicitly
    (`pytest -m live`, `make test-live`), never by default and never in CI."""
    if "live" in (config.option.markexpr or ""):
        return
    skip = pytest.mark.skip(reason="live: run with `make test-live` (needs make llm-up)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
