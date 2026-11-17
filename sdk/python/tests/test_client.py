"""The client against a fake Nuria (tests/fake_nuria.py): the async API in full, the sync API
on the same scenarios (it's the same code, written by scripts/unasync.py)."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

import nuria
from nuria import _async, _sync
from nuria.types import MessageEvent, StatusEvent, TokenEvent
from tests.fake_nuria import SESSION, FakeNuria

URL = "http://nuria.test/api"


@pytest.fixture(autouse=True)
def instant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoffs and polls without the waiting."""

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(_async, "_sleep", no_wait)
    monkeypatch.setattr(_sync, "_sleep", lambda _: None)


@pytest.fixture
def fake() -> FakeNuria:
    return FakeNuria(async_mode=True)


@pytest.fixture
async def client(fake: FakeNuria) -> AsyncIterator[nuria.AsyncNuria]:
    async with nuria.AsyncNuria(URL, transport=fake.transport()) as c:
        yield c


def msg(
    fake: FakeNuria, seq: int, kind: str = "assistant", text: str | None = None
) -> tuple[Any, ...]:
    return ("event", "message.created", fake.add_message(seq, kind, text), seq)


def status(fake: FakeNuria, value: str) -> tuple[Any, ...]:
    payload = {"run_id": fake.run_id, "status": value, "event": "run.completed", "reason": None}
    return ("event", "turn.status", payload, None)


async def started(client: nuria.AsyncNuria) -> nuria.AsyncTurn:
    session = await client.sessions.create(agent="chat")
    return await session.send("What is 2 + 2?")


async def collect(turn: nuria.AsyncTurn) -> list[nuria.TurnEvent]:
    return [e async for e in turn.events()]


async def test_send_stream_and_wait(client: nuria.AsyncNuria, fake: FakeNuria) -> None:
    turn = await started(client)
    assert (turn.session_id, turn.run_id, turn.after_seq) == (SESSION, fake.run_id, 0)
    fake.connections = [[
        ("event", "token", {"text": "4"}, None),
        msg(fake, 2, "assistant", "4"), ("run", "completed"), status(fake, "completed"),
    ]]  # fmt: skip
    pieces = [t async for t in turn.text()]
    assert pieces == ["4"]
    assert fake.stream_headers == ["0"]  # from just before the user's message
    result = await turn.wait()
    assert isinstance(result, nuria.Completed)
    assert result == nuria.Completed(SESSION, fake.run_id, "4", result.messages)
    assert [m.type for m in result.messages] == ["user", "assistant"]


async def test_a_drain_a_drop_and_replays_each_stored_message_once(
    client: nuria.AsyncNuria, fake: FakeNuria
) -> None:
    """AC51 in miniature: every persisted event once, in order, through a drain and a drop."""
    turn = await started(client)
    m2, m3 = msg(fake, 2, "tool_call"), msg(fake, 3, "tool_result")
    fake.connections = [
        [msg(fake, 1, "user"), m2, ("drain", 2)],  # replica 1 drains
        [m2, m3, ("event", "token", {"text": "4"}, None), ("drop",)],  # a replay, then a cut
        [m3, msg(fake, 4, "assistant", "4"), ("run", "completed"), status(fake, "completed")],
    ]
    fake.messages = fake.messages[1:]  # the user message is #1 of the stream (and the store's)
    events = await collect(turn)
    stored = [e.message.seq for e in events if isinstance(e, MessageEvent)]
    assert stored == [1, 2, 3, 4]
    assert fake.stream_headers == ["0", "2", "3"]  # each reconnection resumes after its cursor
    assert (turn.reconnects, turn.drains) == (2, 1)
    assert isinstance(events[-1], StatusEvent) and events[-1].status == "completed"


async def test_a_status_lost_in_a_gap_is_read_from_the_run(
    client: nuria.AsyncNuria, fake: FakeNuria
) -> None:
    turn = await started(client)
    fake.add_message(2, "assistant", "4")  # stored while we were cut off
    fake.connections = [[("drop",)]]
    fake.statuses = ["running", "completed"]  # the turn ended during the gap
    events = await collect(turn)
    assert [type(e) for e in events] == [MessageEvent, MessageEvent, StatusEvent]
    assert events[-1] == StatusEvent("completed", None)


async def test_a_turn_that_ended_before_we_connected_is_caught_up(
    client: nuria.AsyncNuria, fake: FakeNuria
) -> None:
    turn = await started(client)
    fake.add_message(2, "assistant", "4")
    fake.run["status"] = "completed"
    rebuilt = client.turn(SESSION, turn.run_id)  # in another process, later
    events = await collect(rebuilt)
    assert [e.message.seq for e in events if isinstance(e, MessageEvent)] == [1, 2]
    assert fake.stream_headers == []  # never needed to connect


async def test_a_quiet_stream_asks_the_run(
    client: nuria.AsyncNuria, fake: FakeNuria, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_async, "QUIET_S", -1.0)  # every keep-alive is "too long"
    turn = await started(client)
    fake.connections = [[("ping",), ("run", "completed"), ("ping",), ("ping",)]]
    events = await collect(turn)
    assert events[-1] == StatusEvent("completed", None)


async def test_waiting_for_an_approval_ends_the_stream(
    client: nuria.AsyncNuria, fake: FakeNuria
) -> None:
    turn = await started(client)
    fake.connections = [[status(fake, "waiting_approval")]]
    events = await collect(turn)
    assert events == [StatusEvent("waiting_approval", None)]


async def test_a_404_stream_is_fatal(client: nuria.AsyncNuria, fake: FakeNuria) -> None:
    turn = await started(client)
    fake.connections = [[("status", 404)]]
    with pytest.raises(nuria.NotFound):
        await collect(turn)


async def test_a_503_stream_is_retried(client: nuria.AsyncNuria, fake: FakeNuria) -> None:
    turn = await started(client)
    fake.connections = [[("status", 503)], [("run", "completed"), status(fake, "completed")]]
    events = await collect(turn)
    assert events[-1] == StatusEvent("completed", None)
    assert len(fake.stream_headers) == 2


async def test_a_stream_that_keeps_breaking_gives_up(
    client: nuria.AsyncNuria, fake: FakeNuria
) -> None:
    turn = await started(client)
    fake.connections = [[("drop",)] for _ in range(10)]
    with pytest.raises(nuria.ConnectionFailed):
        await collect(turn)
    assert len(fake.stream_headers) == 6  # the first, then five attempts


async def test_a_retried_send_makes_one_turn(client: nuria.AsyncNuria, fake: FakeNuria) -> None:
    """AC53 in miniature: a 503, then a 409 duplicate-send, then the turn: one key, one turn."""
    fake.send_answers = [(503, "draining"), (409, "duplicate-send")]
    turn = await started(client)
    assert fake.turns_made == 1
    assert len(fake.sends) == 3 and len(set(fake.sends)) == 1 and fake.sends[0]
    assert turn.run_id == fake.run_id


async def test_a_send_that_conflicts_otherwise_is_not_retried(
    client: nuria.AsyncNuria, fake: FakeNuria
) -> None:
    fake.send_answers = [(409, "turn-active")]
    session = await client.sessions.create()
    with pytest.raises(nuria.Conflict) as raised:
        await session.send("again")
    assert raised.value.kind == "turn-active"
    assert len(fake.sends) == 1


async def test_your_own_idempotency_key_is_used(client: nuria.AsyncNuria, fake: FakeNuria) -> None:
    session = await client.sessions.create()
    first = await session.send("hi", idempotency_key="k-1")
    again = await session.send("hi", idempotency_key="k-1")
    assert first.run_id == again.run_id and fake.turns_made == 1 and fake.sends == ["k-1", "k-1"]


async def test_wait_waits_through_every_other_status(
    client: nuria.AsyncNuria, fake: FakeNuria
) -> None:
    turn = await started(client)
    fake.add_message(2, "assistant", "4")
    fake.statuses = [
        "queued",
        "running",
        "waiting_children",
        "a_status_from_a_newer_nuria",
        "completed",
    ]
    result = await turn.wait()
    assert isinstance(result, nuria.Completed) and result.answer == "4"


async def test_wait_returns_awaiting_approval_and_nothing_can_decide_it(
    client: nuria.AsyncNuria, fake: FakeNuria
) -> None:
    turn = await started(client)
    fake.run.update(status="waiting_approval", interrupt_payload={
        "approval_id": "a-1", "tool": "notify", "args": {"text": "hi"}, "hidden": 0,
        "call_id": "c", "reason": "notify has an external side effect"})  # fmt: skip
    result = await turn.wait()
    assert isinstance(result, nuria.AwaitingApproval)
    assert (result.approval.approval_id, result.approval.tool) == ("a-1", "notify")
    names = {n for obj in (client, turn, client.sessions) for n in dir(obj)}
    assert not {n for n in names if "approv" in n or "decide" in n or "reject" in n}  # R19.7


async def test_wait_with_a_timeout(client: nuria.AsyncNuria, fake: FakeNuria) -> None:
    turn = await started(client)
    with pytest.raises(TimeoutError):
        await turn.wait(timeout_s=0)


async def test_errors_carry_the_problem(client: nuria.AsyncNuria) -> None:
    with pytest.raises(nuria.NotFound) as raised:
        await client.sessions.get("44444444-4444-4444-4444-444444444444")
    assert raised.value.status == 404 and raised.value.kind == "not-found"


async def test_cancel_cancels_this_run(client: nuria.AsyncNuria, fake: FakeNuria) -> None:
    turn = await started(client)
    await turn.cancel()
    assert isinstance(await turn.wait(), nuria.Cancelled)


async def test_an_unreachable_nuria_is_connection_failed() -> None:
    def refuse(request: Any) -> Any:
        import httpx

        raise httpx.ConnectError("refused", request=request)

    import httpx

    async with nuria.AsyncNuria(URL, transport=httpx.MockTransport(refuse)) as c:
        with pytest.raises(nuria.ConnectionFailed):
            await c.sessions.get(SESSION)


# ------------------------------------------------------------------------- the sync API
@pytest.fixture
def sync_fake() -> FakeNuria:
    return FakeNuria(async_mode=False)


@pytest.fixture
def sync_client(sync_fake: FakeNuria) -> Iterator[nuria.Nuria]:
    with nuria.Nuria(URL, transport=sync_fake.transport()) as c:
        yield c


def test_sync_drain_drop_and_replays(sync_client: nuria.Nuria, sync_fake: FakeNuria) -> None:
    fake = sync_fake
    turn = sync_client.sessions.create().send("What is 2 + 2?")
    m2 = msg(fake, 2, "tool_call")
    fake.connections = [
        [msg(fake, 1, "user"), ("drain", 1)],
        [m2, ("event", "token", {"text": "4"}, None), ("drop",)],
        [m2, msg(fake, 3, "assistant", "4"), ("run", "completed"), status(fake, "completed")],
    ]
    fake.messages = fake.messages[1:]
    events = list(turn.events())
    assert [e.message.seq for e in events if isinstance(e, MessageEvent)] == [1, 2, 3]
    assert [e for e in events if isinstance(e, TokenEvent)] == [TokenEvent("4")]
    assert fake.stream_headers == ["0", "1", "2"]
    assert isinstance(turn.wait(), nuria.Completed)


def test_sync_retried_send_makes_one_turn(sync_client: nuria.Nuria, sync_fake: FakeNuria) -> None:
    sync_fake.send_answers = [(503, "draining"), (409, "duplicate-send")]
    sync_client.sessions.create().send("hi")
    assert sync_fake.turns_made == 1 and len(set(sync_fake.sends)) == 1


def test_sync_wait_awaiting_approval(sync_client: nuria.Nuria, sync_fake: FakeNuria) -> None:
    turn = sync_client.sessions.create().send("hi")
    sync_fake.run.update(status="waiting_approval", interrupt_payload={"approval_id": "a-2"})
    result = turn.wait()
    assert isinstance(result, nuria.AwaitingApproval) and result.approval.approval_id == "a-2"
