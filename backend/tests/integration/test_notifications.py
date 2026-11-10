"""Phase H4: an approved notification reaches a real webhook, signed, exactly once per
receiver that keeps the ids it saw; retried when the receiver is down, never twice at
once, never to an address the outbound guard refuses."""

import asyncio
import base64
import socket
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn
from pydantic import SecretStr

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.devtools.fake_model import create_app
from agent_runtime.graphs import default_registry
from agent_runtime.notifications.delivery import NotificationRelay
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import Run

pytestmark = pytest.mark.integration
GRAPHS = default_registry()
SECRET = "whsec_" + base64.b64encode(b"test-webhook-secret-0123456789ab").decode()
NOTIFY = [
    {"tool_calls": [{"name": "notify", "args": {"to": "ceo", "message": "ship it"}}]},
    {"content": "Notified."},
]


@pytest.fixture
async def receiver(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """The fake model server's webhook receiver (devtools), over real HTTP."""
    monkeypatch.setenv("NOTIFY_WEBHOOK_SECRET", SECRET)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(create_app(), port=port, log_level="warning",
                                           lifespan="on"))  # fmt: skip
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 — uvicorn offers no "started" event
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


def webhook(settings: Settings, url: str) -> Settings:
    return settings.model_copy(update={
        "notify_webhook_url": url, "notify_webhook_secret": SecretStr(SECRET)})  # fmt: skip


async def received(base: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        got: list[dict[str, Any]] = (await client.get(f"{base}/webhook/received")).json()
        return got


async def approved_notification(pool: Pool, settings: Settings) -> tuple[Run, str]:
    """A turn that called notify, approved: its notification is queued. Its key."""
    service = RunService(pool, settings, GRAPHS)
    run = await service.create_run("assistant", {"message": "tell the ceo", "script": NOTIFY})
    paused = await RunExecutor(pool, settings, GRAPHS).execute(run.id)
    assert paused.status is S.WAITING_APPROVAL
    await service.decide_approval(run.id, "approve")
    done = await RunExecutor(pool, settings, GRAPHS).execute(run.id)
    assert done.status is S.COMPLETED
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT key FROM outbox_notifications WHERE run_id = %s",
                                 (run.id,))  # fmt: skip
        (row,) = await cur.fetchall()
    return done, str(row["key"])


async def delivery(pool: Pool, key: str) -> dict[str, Any]:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM notification_deliveries WHERE key = %s", (key,))
        row = await cur.fetchone()
    assert row is not None
    return dict(row)


async def due_now(pool: Pool, key: str) -> None:
    """Skip the backoff (the test doesn't wait 5 s)."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE notification_deliveries SET next_at = now() WHERE key = %s", (key,)
        )


async def tool_result(pool: Pool, run: Run) -> dict[str, Any]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT result FROM tool_invocations WHERE run_id = %s AND tool = 'notify'",
            (run.id,),
        )
        row = await cur.fetchone()
    assert row is not None
    result: dict[str, Any] = row["result"]
    return result


async def test_an_approved_notification_reaches_the_webhook_once_and_signed(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, receiver: str
) -> None:
    settings = webhook(test_settings, f"{receiver}/webhook")
    run, key = await approved_notification(pool, settings)
    assert (await tool_result(pool, run))["delivery"] == "sending to the notifications webhook"
    assert (await delivery(pool, key))["status"] == "pending"
    relay = NotificationRelay(pool, settings)
    assert await relay.sweep() >= 1
    (got,) = [r for r in await received(receiver) if r["id"] == key]
    assert got["verified"] is True  # the receiver checked the signature
    assert got["body"]["type"] == "notification.created"
    assert got["body"]["data"] | {"created_at": None} == {
        "notification_id": key[:16], "to": "ceo", "message": "ship it", "agent": "assistant",
        "run_id": str(run.id), "session_id": None, "created_at": None,
    }  # fmt: skip
    row = await delivery(pool, key)
    assert (row["status"], row["attempts"], row["last_status"]) == ("delivered", 1, 200)
    await relay.sweep()
    assert len([r for r in await received(receiver) if r["id"] == key]) == 1  # never again


async def test_two_workers_never_send_the_same_notification(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, receiver: str
) -> None:
    settings = webhook(test_settings, f"{receiver}/webhook")
    _, key = await approved_notification(pool, settings)
    a, b = NotificationRelay(pool, settings), NotificationRelay(pool, settings)
    await asyncio.gather(a.sweep(), b.sweep(), a.sweep(), b.sweep())
    assert len([r for r in await received(receiver) if r["id"] == key]) == 1
    assert (await delivery(pool, key))["status"] == "delivered"


async def test_a_receiver_that_is_down_gets_it_again_with_the_same_id(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, receiver: str
) -> None:
    settings = webhook(test_settings, f"{receiver}/webhook")
    _, key = await approved_notification(pool, settings)
    async with httpx.AsyncClient() as client:
        await client.post(f"{receiver}/webhook/fail", params={"times": 1})
    relay = NotificationRelay(pool, settings)
    await relay.sweep()
    row = await delivery(pool, key)
    assert (row["status"], row["attempts"], row["last_status"]) == ("pending", 1, 500)
    assert row["next_at"] > row["created_at"]  # backing off
    await relay.sweep()  # not due yet: nothing sent
    assert len([r for r in await received(receiver) if r["id"] == key]) == 1
    await due_now(pool, key)
    await relay.sweep()
    got = [r for r in await received(receiver) if r["id"] == key]
    assert [r["answered"] for r in got] == [500, 200]  # the same webhook-id both times
    assert (await delivery(pool, key))["status"] == "delivered"


async def test_a_refusal_by_the_receiver_is_not_retried(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, receiver: str
) -> None:
    settings = webhook(test_settings, f"{receiver}/no-such-hook")  # 404
    _, key = await approved_notification(pool, settings)
    relay = NotificationRelay(pool, settings)
    await relay.sweep()
    row = await delivery(pool, key)
    assert (row["status"], row["last_status"]) == ("failed", 404)
    await due_now(pool, key)
    await relay.sweep()
    assert (await delivery(pool, key))["attempts"] == 1


async def test_a_worker_that_dies_after_sending_is_covered_by_the_same_id(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, receiver: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    settings = webhook(test_settings, f"{receiver}/webhook")
    _, key = await approved_notification(pool, settings)
    relay = NotificationRelay(pool, settings)
    real = NotificationRelay._settle

    async def dies(self: NotificationRelay, *a: Any, **kw: Any) -> None:
        raise ConnectionError("the worker died before it could write 'delivered'")

    monkeypatch.setattr(NotificationRelay, "_settle", dies)
    with pytest.raises(ConnectionError):
        await relay.sweep()
    assert (await delivery(pool, key))["status"] == "sending"
    monkeypatch.setattr(NotificationRelay, "_settle", real)
    await relay.sweep()  # its claim hasn't expired: nobody takes it
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE notification_deliveries SET claimed_until = now() WHERE key = %s", (key,)
        )
    await relay.sweep()
    got = [r for r in await received(receiver) if r["id"] == key]
    assert len(got) == 2 and all(r["verified"] for r in got)  # at least once, one id
    row = await delivery(pool, key)
    assert (row["status"], row["attempts"]) == ("delivered", 2)


async def test_a_webhook_address_the_guard_refuses_gets_nothing(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    settings = webhook(test_settings, "http://169.254.169.254/latest/meta-data/")
    _, key = await approved_notification(pool, settings)
    await NotificationRelay(pool, settings).sweep()
    row = await delivery(pool, key)
    assert row["status"] == "failed" and "metadata" in row["last_error"]


async def test_with_no_webhook_it_is_kept_and_the_agent_is_told(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    settings = test_settings.model_copy(update={"notify_webhook_url": ""})
    run, key = await approved_notification(pool, settings)
    assert (await tool_result(pool, run))["delivery"].startswith("kept, not sent")
    relay = NotificationRelay(pool, settings)
    assert not relay.enabled and await relay.sweep() == 0
    assert (await delivery(pool, key))["status"] == "pending"


async def test_a_sender_whose_claim_was_taken_does_not_send(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, receiver: str
) -> None:
    """A slow sender's claim expired and another worker took the row: it must not POST
    too (it renews its claim just before each send)."""
    settings = webhook(test_settings, f"{receiver}/webhook")
    _, key = await approved_notification(pool, settings)
    slow = NotificationRelay(pool, settings)
    (due,) = [d for d in await slow._claim() if d.key == key]
    async with pool.connection() as conn:  # expired, and claimed by another worker
        await conn.execute(
            "UPDATE notification_deliveries SET claim = gen_random_uuid() WHERE key = %s", (key,)
        )
    assert not await slow._renew(due)
    assert [r for r in await received(receiver) if r["id"] == key] == []


async def test_a_webhook_name_that_does_not_resolve_is_tried_again(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    settings = webhook(test_settings, "http://nuria-webhook.invalid/hook")
    _, key = await approved_notification(pool, settings)
    await NotificationRelay(pool, settings).sweep()
    row = await delivery(pool, key)
    assert row["status"] == "pending" and "Nothing answers" in row["last_error"]
