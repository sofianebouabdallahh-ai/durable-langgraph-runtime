"""The e2e scenarios as tests (real processes; needs `make up`)."""

import pytest

from tests.e2e.scenarios import SCENARIOS, run_scenario

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


@pytest.mark.parametrize("name", list(SCENARIOS))
async def test_scenario(name: str) -> None:
    report, logs = await run_scenario(name)
    failed = [f"{check}: {detail}" for check, ok, detail in report.checks if not ok]
    assert report.passed, f"{report.scenario} failed: {failed}\n{logs}"
