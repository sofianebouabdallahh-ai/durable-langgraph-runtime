"""The `runtime` CLI as a real process, against the test database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime.config import Settings

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]


def runtime(settings: Settings, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_runtime.cli", *args],
        cwd=BACKEND,
        env=os.environ | {"POSTGRES_DB": settings.postgres_db, "LOG_LEVEL": "WARNING"},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_db_upgrade_is_idempotent(test_settings: Settings, test_db_url: str) -> None:
    for _ in range(2):  # a deploy may run the migrate Job again; it must be a no-op
        done = runtime(test_settings, "db", "upgrade")
        assert done.returncode == 0, done.stderr
        assert "schema at head; LangGraph checkpoint tables ready" in done.stdout


def test_run_creates_and_executes(test_settings: Settings, test_db_url: str) -> None:
    runtime(test_settings, "db", "upgrade")
    done = runtime(test_settings, "run", "--graph", "toy", "--input", '{"question": "cli?"}')
    assert done.returncode == 0, done.stderr
    assert ": completed" in done.stdout
    assert "node.completed   answer" in done.stdout


def test_run_reports_a_failed_run_with_exit_1(test_settings: Settings, test_db_url: str) -> None:
    done = runtime(
        test_settings, "run", "--graph", "toy",
        "--input", '{"question": "q", "fail_at": "plan"}',
    )  # fmt: skip
    assert done.returncode == 1
    assert "failed (error)" in done.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["run", "--graph", "nope", "--input", "{}"], "unknown graph 'nope'"),
        (["run", "--graph", "toy", "--input", '{"question": ""}'], "question"),
        (["run", "--graph", "toy", "--input", "{"], "not valid JSON"),
        (["run", "--graph", "toy", "--input", "[1]"], "must be a JSON object"),
        (
            [
                "run",
                "--graph",
                "toy",
                "--input",
                '{"question": "q"}',
                "--options",
                '{"max_steps": 9999}',
            ],
            "exceeds the server maximum",
        ),
    ],
)
def test_bad_requests_exit_2(
    test_settings: Settings, test_db_url: str, args: list[str], message: str
) -> None:
    done = runtime(test_settings, *args)
    assert done.returncode == 2
    assert message in done.stderr
