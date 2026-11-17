"""The client against a running Nuria (CR-007 AC51 to AC53), with its scripted model.

    NURIA_URL=http://127.0.0.1:3000/api NURIA_COMPOSE_PROJECT=<project> \\
        uv run pytest -m stack tests/stack        (NURIA_STACK_REPEAT=5 runs each 5 times)

The drain-and-cut scenario stops and starts the stack's containers (`docker`), so it runs
only with NURIA_COMPOSE_PROJECT set, and only against a stack of yours.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

import nuria
from nuria.types import MessageEvent

pytestmark = pytest.mark.stack

URL = os.environ.get("NURIA_URL", "http://127.0.0.1:3000/api")
PROJECT = os.environ.get("NURIA_COMPOSE_PROJECT", "")
REPEAT = range(int(os.environ.get("NURIA_STACK_REPEAT", "1")))
DOCKER = shutil.which("docker") or str(Path.home() / ".docker" / "bin" / "docker")


@pytest.fixture
async def client() -> AsyncIterator[nuria.AsyncNuria]:
    async with nuria.AsyncNuria(URL) as c:
        yield c


def slow_turn(steps: int, linger_s: float) -> list[dict[str, Any]]:
    """A turn that takes `steps * linger_s` seconds: each step saves a note slowly."""
    script: list[dict[str, Any]] = [
        {"tool_calls": [{"name": "save_note",
                         "args": {"text": f"kept {uuid.uuid4().hex[:8]}", "linger_s": linger_s}}]}
        for _ in range(steps)
    ]  # fmt: skip
    return [*script, {"content": "Kept."}]


def docker(*args: str) -> str:
    done = subprocess.run([DOCKER, *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def containers(service: str) -> list[str]:
    return docker("ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}",
                  "--filter", f"label=com.docker.compose.service={service}").split()  # fmt: skip


def wait_healthy(container: str, timeout_s: float = 90) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if docker("inspect", "-f", "{{.State.Health.Status}}", container) == "healthy":
            return
        time.sleep(0.5)
    raise AssertionError(f"{container} not healthy after {timeout_s}s")


def disrupt() -> list[str]:
    """Each API replica in turn drains (`docker stop`: SIGTERM, so open streams get
    `event: reconnect`) and comes back; then the proxy the client talks to is killed and
    restarted: a cut connection. The stream is on some replica, so one of the drains is its."""
    done = []
    for api in containers("api"):
        docker("stop", api)
        done.append(f"stopped api {api[:12]}")
        docker("start", api)
        wait_healthy(api)
    for ui in containers("ui"):
        docker("kill", ui)
        done.append(f"killed ui {ui[:12]}")
        docker("start", ui)
        wait_healthy(ui)
    return done


@pytest.mark.skipif(not PROJECT, reason="needs NURIA_COMPOSE_PROJECT: it stops containers")
@pytest.mark.parametrize("run", REPEAT)
async def test_ac51_a_turn_streams_through_a_drain_and_a_cut(
    client: nuria.AsyncNuria, run: int
) -> None:
    session = await client.sessions.create(agent="chat")
    turn = await session.send("keep these", script=slow_turn(steps=6, linger_s=7))
    seen: list[int] = []

    async def follow() -> None:
        async for event in turn.events():
            if isinstance(event, MessageEvent):
                seen.append(event.message.seq)

    following = asyncio.create_task(follow())
    await asyncio.sleep(2)
    actions = await asyncio.to_thread(disrupt)
    await asyncio.wait_for(following, timeout=180)
    result = await turn.wait()

    stored = [m.seq for m in await turn.messages()]
    assert isinstance(result, nuria.Completed), result
    assert result.answer == "Kept."
    assert seen == stored, f"stream {seen} vs stored {stored}"  # every message once, in order
    assert len(seen) == len(set(seen))
    assert turn.drains >= 1, (actions, turn.reconnects, turn.drains)  # a drain hit our stream
    assert turn.reconnects > turn.drains, (actions, turn.reconnects, turn.drains)  # and the cut
    print(f"run {run}: {len(seen)} messages once each; reconnects {turn.reconnects}, "
          f"drains {turn.drains}; {', '.join(actions)}")  # fmt: skip


NOTIFY: list[dict[str, Any]] = [
    {"tool_calls": [{"name": "notify", "args": {"to": "team", "message": "the build is green"}}]},
    {"content": "Sent."},
]

LATER = """
import sys
import nuria
with nuria.Nuria(sys.argv[1]) as client:
    result = client.turn(sys.argv[2], sys.argv[3]).wait(timeout_s=120)
print(type(result).__name__, result.answer if isinstance(result, nuria.Completed) else "")
"""


@pytest.mark.parametrize("run", REPEAT)
async def test_ac52_an_approval_is_a_result_and_the_person_decides(
    client: nuria.AsyncNuria, run: int
) -> None:
    session = await client.sessions.create(agent="chat")
    turn = await session.send("tell the team", script=NOTIFY)
    waiting = await turn.wait(timeout_s=60)
    assert isinstance(waiting, nuria.AwaitingApproval), waiting
    assert waiting.approval.tool == "notify" and waiting.approval.approval_id

    public = {name for obj in (client, client.sessions, session, turn) for name in dir(obj)
              if not name.startswith("_")}  # fmt: skip
    assert not {n for n in public if any(w in n for w in ("approv", "decide", "reject"))}

    # The person approves, in Nuria (here: its API, as the web app's Approve button does).
    async with httpx.AsyncClient(base_url=URL) as person:
        decision = {"decision": "approve", "approval_id": waiting.approval.approval_id}
        decided = await person.post(f"/sessions/{session.id}/approve", json=decision)
        assert decided.status_code == 202, decided.text

    later = await asyncio.to_thread(
        subprocess.run, [sys.executable, "-c", LATER, URL, session.id, turn.run_id],
        capture_output=True, text=True, timeout=180,
    )  # fmt: skip
    assert later.returncode == 0, later.stderr
    assert later.stdout.split()[0] == "Completed", later.stdout
    print(f"run {run}: awaiting {waiting.approval.tool} ({waiting.approval.approval_id}), "
          f"then in a new process: {later.stdout.strip()}")  # fmt: skip


class Counting(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self.sends: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if request.method == "POST" and request.url.path.endswith("/messages"):
            self.sends.append(response.status_code)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


@pytest.mark.parametrize("run", REPEAT)
async def test_ac53_a_send_retried_with_its_key_makes_one_turn(run: int) -> None:
    counting = Counting()
    async with nuria.AsyncNuria(URL, transport=counting) as client:
        session = await client.sessions.create(agent="chat")
        key = str(uuid.uuid4())
        turns = await asyncio.gather(*[
            session.send("once", idempotency_key=key, script=[{"content": "Once."}])
            for _ in range(5)
        ])  # fmt: skip
        assert len({t.run_id for t in turns}) == 1
        result = await turns[0].wait(timeout_s=60)
        assert isinstance(result, nuria.Completed)
        users = [m for m in await turns[0].messages() if m.type == "user"]
        assert len(users) == 1
        again = await session.send("once", idempotency_key=key, script=[{"content": "Once."}])
        assert again.run_id == turns[0].run_id
    conflicts = counting.sends.count(409)
    print(f"run {run}: 6 sends of one key → 1 turn; answers {sorted(counting.sends)}, "
          f"{conflicts} were 409 duplicate-send and retried")  # fmt: skip
