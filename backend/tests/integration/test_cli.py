"""The `runtime` CLI as a real process, against the test database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]


def runtime(
    settings: Settings, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_runtime.cli", *args],
        cwd=BACKEND,
        env=os.environ
        | {"POSTGRES_DB": settings.postgres_db, "LOG_LEVEL": "WARNING"}
        | (env or {}),
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


def test_supervisor_starts_n_workers_and_forwards_sigterm(
    test_settings: Settings, pool: Pool
) -> None:
    """`runtime worker --workers 2` (what `make worker` runs): both children start,
    and one SIGTERM to the supervisor drains and stops them all cleanly."""
    import signal
    import time
    import uuid

    env = os.environ | {
        "POSTGRES_DB": test_settings.postgres_db,
        "REDIS_URL": test_settings.redis_url.rsplit("/", 1)[0] + "/15",
        "WORK_STREAM": f"test:{uuid.uuid4()}",
        "LOG_LEVEL": "INFO",
    }
    cmd = ["worker", "--workers", "2", "--concurrency", "1"]
    proc = subprocess.Popen(
        [sys.executable, "-m", "agent_runtime.cli", *cmd],
        cwd=BACKEND,
        env=env,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stderr is not None
        lines: list[str] = []
        deadline = time.monotonic() + 30
        while sum("up (concurrency 1)" in line for line in lines) < 2:
            assert time.monotonic() < deadline, "workers did not start:\n" + "".join(lines)
            lines.append(proc.stderr.readline())
        assert any("supervising 2 workers" in line for line in lines)
        proc.send_signal(signal.SIGTERM)
        out = proc.communicate(timeout=30)[1]
        assert proc.returncode == 0, out
        assert out.count("stopped") >= 2  # each child drained and stopped
    finally:
        if proc.poll() is None:
            proc.kill()


def test_chat_streams_a_turn_in_the_terminal(test_settings: Settings, test_db_url: str) -> None:
    """`runtime chat --message …`: a session, a turn, tokens printed as they stream."""
    out = runtime(test_settings, "chat", "--message", "hello there",
                  env={"SCRIPTED_STREAMING": "true"})  # fmt: skip
    assert out.returncode == 0, out.stderr
    assert "with chat (provider: scripted)" in out.stdout
    assert "you> hello there" in out.stdout
    assert "chat> (script finished)" in out.stdout  # the streamed reply, live
    assert "[completed · 1 model calls · 0 tools" in out.stdout
