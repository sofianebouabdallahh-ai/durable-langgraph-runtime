"""Notifications, delivered (phase H4): the relay of the transactional outbox.

`notify` writes `outbox_notifications` (keyed by the call's idempotency key, so a
retried call never queues twice), and a trigger gives each row its
`notification_deliveries` row. Every worker runs this relay:

    claim     UPDATE … status='sending', claim=<uuid>, claimed_until=now()+60 s
              WHERE key IN (due rows … FOR UPDATE SKIP LOCKED): two workers never
              claim the same notification
    renew     just before each send the claim is renewed (the row is skipped if it was
              lost), and the send has a 30 s deadline: a claim never expires while its
              sender may still POST, so two senders never send it at once
    check     the webhook address, with the outbound guard (net.py), at every attempt
              (a name that doesn't resolve right now is retried, not refused)
    send      POST, Standard Webhooks headers; redirects are not followed
    settle    guarded by the claim (a slow sender can't overwrite a newer claim):
              2xx → delivered · 4xx but 408/429 → failed · else → pending, backoff
              5 s · 2^(n-1) up to 1 h · after 30 attempts or 24 h → failed

Exactly once, honestly: delivery is AT LEAST once. A worker that dies after the POST and
before the settle sends it again once its claim expires, with the SAME `webhook-id`
(the notification's key), so a receiver that keeps the ids it saw acts exactly once.

Wire format (https://www.standardwebhooks.com): `webhook-id`, `webhook-timestamp` (unix
seconds) and `webhook-signature: v1,<base64 HMAC-SHA256(secret, "id.timestamp.body")>`.
A secret written `whsec_<base64>` is base64-decoded first, as the spec says.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from agent_runtime import logs, metrics
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.net import DestinationRefused, Guard, Unresolvable

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 30  # with the backoff: about 21 h of tries, inside MAX_AGE
MAX_AGE = timedelta(hours=24)
CLAIM_S = 60
SEND_DEADLINE_S = 30.0  # one attempt, address check and POST: well inside its claim
BATCH = 10
TIMEOUT_S = 10.0
BACKOFF_BASE_S = 5.0
BACKOFF_CAP_S = 3600.0
EVENT_TYPE = "notification.created"


def backoff_s(attempts: int) -> float:
    """Seconds before attempt `attempts + 1`: 5, 10, 20, … capped at an hour."""
    return float(min(BACKOFF_BASE_S * 2 ** max(attempts - 1, 0), BACKOFF_CAP_S))


def signing_key(secret: str) -> bytes:
    """Standard Webhooks: `whsec_<base64>` is decoded; any other string is used as is."""
    if secret.startswith("whsec_"):
        return base64.b64decode(secret.removeprefix("whsec_"))
    return secret.encode()


def sign(key: bytes, msg_id: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def verify(key: bytes, headers: Mapping[str, str], body: bytes, *, tolerance_s: int = 300) -> bool:
    """What a receiver checks: a v1 signature over this id, timestamp and body, and a
    timestamp within `tolerance_s` (replays). Used by the tests' receiver."""
    lower = {k.lower(): v for k, v in headers.items()}
    msg_id, stamp = lower.get("webhook-id", ""), lower.get("webhook-timestamp", "")
    if not msg_id or not stamp.isdigit() or abs(time.time() - int(stamp)) > tolerance_s:
        return False
    expected = sign(key, msg_id, int(stamp), body)
    offered = lower.get("webhook-signature", "").split()
    return any(hmac.compare_digest(expected, s) for s in offered)


@dataclass(frozen=True, slots=True)
class Due:
    """A claimed notification, ready to send."""

    key: str
    attempts: int  # including this one
    claim: uuid.UUID
    recipient: str
    message: str
    run_id: uuid.UUID
    session_id: uuid.UUID | None
    agent: str | None
    created_at: datetime

    def body(self) -> dict[str, Any]:
        return {
            "type": EVENT_TYPE,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "notification_id": self.key[:16], "to": self.recipient,
                "message": self.message, "agent": self.agent, "run_id": str(self.run_id),
                "session_id": str(self.session_id) if self.session_id else None,
                "created_at": self.created_at.isoformat(),
            },
        }  # fmt: skip


class NotificationRelay:
    """Sends what's due (one sweep per call), claim-fenced; safe in any number of workers."""

    def __init__(
        self, pool: Pool, settings: Settings, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._pool = pool
        self._url = settings.notify_webhook_url.strip()
        secret = settings.notify_webhook_secret
        self._key = signing_key(secret.get_secret_value()) if secret else None
        self._guard = Guard.of(settings)
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    async def sweep(self) -> int:
        """Claim what's due and send it; the number of notifications attempted."""
        if not self.enabled:
            return 0
        due = await self._claim()
        if not due:
            return 0
        client = self._client or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)
        try:
            for d in due:
                if not await self._renew(d):
                    continue  # its claim was lost (it took too long): another has it
                try:
                    async with asyncio.timeout(SEND_DEADLINE_S):
                        await self._deliver(client, d)
                except TimeoutError:
                    await self._settle(d, "pending", error="no answer in time")
        finally:
            if self._client is None:
                await client.aclose()
        return len(due)

    async def _claim(self) -> list[Due]:
        claim = uuid.uuid4()
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """
                WITH due AS (
                    SELECT key FROM notification_deliveries
                    WHERE (status = 'pending' AND next_at <= now())
                       OR (status = 'sending' AND claimed_until < now())
                    ORDER BY next_at
                    LIMIT %(n)s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE notification_deliveries d
                SET status = 'sending', claim = %(claim)s, attempts = d.attempts + 1,
                    claimed_until = now() + make_interval(secs => %(claim_s)s)
                FROM due WHERE d.key = due.key
                RETURNING d.key, d.attempts
                """,
                {"n": BATCH, "claim": claim, "claim_s": CLAIM_S},
            )
            claimed = {r["key"]: r["attempts"] for r in await cur.fetchall()}
            if not claimed:
                return []
            cur = await conn.execute(
                """
                SELECT n.key, n.recipient, n.message, n.run_id, n.created_at,
                       r.session_id, r.agent_name
                FROM outbox_notifications n JOIN runs r ON r.id = n.run_id
                WHERE n.key = ANY(%s)
                """,
                (list(claimed),),
            )
            rows = await cur.fetchall()
        return [
            Due(key=r["key"], attempts=claimed[r["key"]], claim=claim, recipient=r["recipient"],
                message=r["message"], run_id=r["run_id"], session_id=r["session_id"],
                agent=r["agent_name"], created_at=r["created_at"])
            for r in rows
        ]  # fmt: skip

    async def _renew(self, d: Due) -> bool:
        """Extend this sender's claim before it sends; False if it no longer holds it."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE notification_deliveries
                SET claimed_until = now() + make_interval(secs => %(claim_s)s)
                WHERE key = %(key)s AND claim = %(claim)s AND status = 'sending'
                RETURNING key
                """,
                {"key": d.key, "claim": d.claim, "claim_s": CLAIM_S},
            )
            return await cur.fetchone() is not None

    async def _deliver(self, client: httpx.AsyncClient, d: Due) -> None:
        if d.attempts > MAX_ATTEMPTS or datetime.now(UTC) - d.created_at > MAX_AGE:
            await self._settle(d, "failed", error=f"gave up after {d.attempts - 1} attempt(s)")
            return
        try:
            url = await self._guard.check(self._url)
        except Unresolvable as exc:  # a resolver blip, maybe: try again later
            await self._settle(d, "pending", error=str(exc))
            return
        except DestinationRefused as exc:  # checked at every attempt: DNS can change
            await self._settle(d, "failed", error=f"the webhook address is refused: {exc}",
                               outcome="refused")  # fmt: skip
            return
        body = json.dumps(d.body(), separators=(",", ":")).encode()
        stamp = int(time.time())
        headers = {
            "content-type": "application/json", "user-agent": "Nuria-Webhooks/1",
            "webhook-id": d.key, "webhook-timestamp": str(stamp),
        }  # fmt: skip
        if self._key is not None:
            headers["webhook-signature"] = sign(self._key, d.key, stamp, body)
        try:
            response = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            await self._settle(d, "pending", error=f"{type(exc).__name__}: {exc}"[:300])
            return
        code = response.status_code
        if 200 <= code < 300:
            await self._settle(d, "delivered", http_status=code)
        elif 400 <= code < 500 and code not in (408, 429):
            await self._settle(d, "failed", http_status=code,
                               error=f"the webhook answered {code}")  # fmt: skip
        else:
            await self._settle(d, "pending", http_status=code, error=f"the webhook answered {code}")

    async def _settle(
        self,
        d: Due,
        status: str,
        *,
        http_status: int | None = None,
        error: str | None = None,
        outcome: str | None = None,
    ) -> None:
        if status == "pending" and d.attempts >= MAX_ATTEMPTS:
            status, error = "failed", f"{error}; gave up after {d.attempts} attempts"
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE notification_deliveries SET
                    status = %(status)s, claim = NULL, claimed_until = NULL,
                    last_status = %(code)s, last_error = left(%(error)s, 500),
                    delivered_at = CASE WHEN %(status)s = 'delivered' THEN now() END,
                    next_at = CASE WHEN %(status)s = 'pending'
                                   THEN now() + make_interval(secs => %(wait)s) ELSE next_at END
                WHERE key = %(key)s AND claim = %(claim)s AND status = 'sending'
                RETURNING key
                """,
                {"status": status, "code": http_status, "error": error, "key": d.key,
                 "claim": d.claim, "wait": backoff_s(d.attempts)},
            )  # fmt: skip
            settled = await cur.fetchone() is not None
        result = outcome or {"pending": "retry"}.get(status, status)
        metrics.notification(result)
        logs.event(
            log, f"notification {d.key[:16]}: {result}", notification=d.key[:16],
            attempt=d.attempts, http_status=http_status, error=error, settled=settled or None,
            level=logging.INFO if status == "delivered" else logging.WARNING,
        )  # fmt: skip
