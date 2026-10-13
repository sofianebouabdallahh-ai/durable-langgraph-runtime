"""Phase 1 "done when": SIGKILL a real executor process mid-run, then resume.

SIGKILL can't be caught: no `finally`, no cleanup, no lease release, exactly
like a power cut or an OOM kill. Recovery must come entirely from what was
durably committed: the checkpoints, their events and the lease's expiry.
"""

import asyncio
import os
import signal
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import RunRepository
from tests.integration.support import events, node_completed, summary, wait_until

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]
LEASE_TTL_S = 1.5


def runtime_process(settings: Settings, worker_id: str, *args: str) -> subprocess.Popen[bytes]:
    """`runtime <args>` as a separate OS process, pointed at the test database."""
    env = os.environ | {
        "POSTGRES_DB": settings.postgres_db,
        "LEASE_TTL_S": str(LEASE_TTL_S),
        "HEARTBEAT_S": "0.4",
        "WORKER_ID": worker_id,
        "LOG_LEVEL": "WARNING",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "agent_runtime.cli", *args],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


@pytest.fixture
async def run_id(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> AsyncIterator[uuid.UUID]:
    service = RunService(pool, test_settings, default_registry())
    run = await service.create_run("toy", {"question": "survive a crash?", "delay_s": 0.5})
    yield run.id


async def test_sigkill_mid_run_then_resume(
    pool: Pool, test_settings: Settings, run_id: uuid.UUID
) -> None:
    # 1. A worker process starts executing the run.
    victim = runtime_process(test_settings, "victim:1", "execute", str(run_id))

    # 2. Once `plan` is durably committed, kill it mid-`research` with SIGKILL.
    await wait_until(lambda: node_completed(pool, run_id, "plan"), timeout_s=20)
    victim.send_signal(signal.SIGKILL)
    assert victim.wait(timeout=5) == -signal.SIGKILL

    async with pool.connection() as conn:
        orphan = await RunRepository(conn).get(run_id)
    assert (orphan.status, orphan.owner, orphan.epoch) == (S.RUNNING, "victim:1", 1)

    # 3. Resuming while the dead worker's lease is still live is a no-op (R1.3).
    early = runtime_process(test_settings, "rescuer:2", "resume", str(run_id))
    assert early.wait(timeout=20) == 0
    async with pool.connection() as conn:
        assert (await RunRepository(conn).get(run_id)).epoch == 1  # untouched

    # 4. After the lease expires, another process reclaims and finishes it.
    await asyncio.sleep(LEASE_TTL_S + 0.3)
    rescuer = runtime_process(test_settings, "rescuer:2", "resume", str(run_id))
    out, _ = rescuer.communicate(timeout=30)
    assert rescuer.returncode == 0, out.decode()

    async with pool.connection() as conn:
        repo = RunRepository(conn)
        done = await repo.get(run_id)
        result = await repo.get_result(run_id)
    assert (done.status, done.epoch, done.steps, done.owner) == (S.COMPLETED, 2, 3, None)
    assert result is not None and result["output"]["answer"] == "Toy answer to 'survive a crash?'"

    evts = await events(pool, run_id)
    names = summary(evts)
    # The committed step never re-ran; exactly one reclaim was recorded.
    assert names.count((E.NODE_COMPLETED, "plan")) == 1
    assert names.count((E.RUN_RECLAIMED, None)) == 1
    # Nothing from the interrupted `research` attempt leaked into the log: its
    # step never committed, so its staged events were never written.
    assert [n for e, n in zip(evts, names, strict=True) if e.epoch == 1] == [
        (E.RUN_STARTED, None),
        (E.NODE_STARTED, "plan"),
        (E.NODE_COMPLETED, "plan"),
    ]
    assert [n for n in names if n[1] == "research"] == [
        (E.NODE_STARTED, "research"),
        (E.NODE_COMPLETED, "research"),
    ]
    assert [e.seq for e in evts] == list(range(1, len(evts) + 1))  # gap-free


async def test_resuming_a_completed_run_is_rejected(
    pool: Pool, test_settings: Settings, run_id: uuid.UUID
) -> None:
    first = runtime_process(test_settings, "w:1", "execute", str(run_id))
    assert first.wait(timeout=30) == 0
    again = runtime_process(test_settings, "w:2", "resume", str(run_id))
    out, _ = again.communicate(timeout=30)
    assert again.returncode == 2  # like HTTP 409
    assert b"is completed; it can't be resumed" in out
