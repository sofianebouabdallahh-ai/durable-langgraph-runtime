"""What a turn did, read back from what it committed (phase H6):
- the tools called: the ledger (`tool_invocations`, one row per call, recorded before
  the call runs and durable across a crash; a call refused or rejected never gets one),
  with each call's arguments from its `tool.called` event when there is one;
- the approvals asked: its `interrupt.raised` events;
- the answer: its result (a failed run's wrap-up answer too), else the transcript's last
  reply."""

from __future__ import annotations

import uuid
from typing import Any

from agent_runtime.db import Conn
from agent_runtime.evals.cases import Trajectory
from agent_runtime.runs.store import RunRepository
from agent_runtime.untrusted import unwrap


async def read(conn: Conn, run_id: uuid.UUID) -> Trajectory:
    repo = RunRepository(conn)
    run = await repo.get(run_id)
    args: dict[str, dict[str, Any]] = {}
    asked: list[str] = []
    after = 0
    while True:
        events = await repo.list_events(run_id, after_seq=after, limit=500)
        if not events:
            break
        for e in events:
            if e.type == "tool.called" and isinstance(e.payload.get("args"), dict):
                args.setdefault(str(e.payload.get("tool")), e.payload["args"])
            elif e.type == "interrupt.raised" and e.payload.get("tool"):
                asked.append(str(e.payload["tool"]))
        after = events[-1].seq
    cur = await conn.execute(
        "SELECT tool FROM tool_invocations WHERE run_id = %s ORDER BY created_at, key",
        (run_id,),
    )
    calls = [(r["tool"], args.get(r["tool"], {})) for r in await cur.fetchall()]
    return Trajectory(status=str(run.status), reason=run.reason, calls=calls, asked=asked,
                      answer=await answer(conn, run_id))  # fmt: skip


async def answer(conn: Conn, run_id: uuid.UUID) -> str:
    """The turn's last reply (the API reads only this: it can't read the ledger)."""
    result = await RunRepository(conn).get_result(run_id)
    answer = ((result or {}).get("output") or {}).get("answer")
    if isinstance(answer, str) and answer:
        return unwrap(answer)
    if isinstance(answer, list):  # a provider's content blocks
        text = "".join(b.get("text", "") for b in answer if isinstance(b, dict))
        if text:
            return text
    cur = await conn.execute(
        "SELECT content FROM session_messages WHERE run_id = %s AND type = 'assistant' "
        "ORDER BY seq DESC LIMIT 1",
        (run_id,),
    )
    row = await cur.fetchone()
    return str((row or {}).get("content", {}).get("text") or "") if row else ""
