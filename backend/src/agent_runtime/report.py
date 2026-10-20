""" "Report this reply" (phase L5, local-release §4.8): a zip to attach to an issue.

    README.md    what this is, the version, the turn's outcome, what's included
    events.json  the turn's timeline: event types, times and structural fields only
                 (node, tool, status, duration, reason, owner…), unless the chat's
                 text is included, when the full payloads are
    agent.md     the agent's definition, when it's one you made (or agent.zip, with
                 its helpers and skills)
    chat.md      the conversation, only when the person ticked "include the text"

Nothing is uploaded: the person downloads the zip and attaches it themselves.
Pattern: a pure assembly over repositories; the API route is transport only.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from typing import Any

from agent_runtime.agents.studio import StudioService
from agent_runtime.db import Pool
from agent_runtime.runs.store import Event, RunRepository
from agent_runtime.sessions.export import to_markdown
from agent_runtime.sessions.store import SessionRepository

# Event payload keys that describe what happened without saying anything that was said.
STRUCTURAL = frozenset({
    "node", "tool", "status", "duration_ms", "cached", "owner", "reclaims", "reason",
    "decision", "kind", "steps", "handle", "agent", "budget_limited", "interrupt_type",
    "key", "graph", "parent_run_id", "subagent", "result_status", "call_id", "error",
})  # fmt: skip


def _event(e: Event, full: bool) -> dict[str, Any]:
    payload = e.payload if full else {
        k: v for k, v in e.payload.items()
        if k in STRUCTURAL and (v is None or isinstance(v, (bool, int, float, str)))
        and not (isinstance(v, str) and len(v) > 80)  # a short code, never a text
    }  # fmt: skip
    return {"seq": e.seq, "ts": e.ts.isoformat(), "epoch": e.epoch, "type": e.type,
            "payload": payload}  # fmt: skip


async def build(
    pool: Pool, studio: StudioService, run_id: uuid.UUID, *, include_chat: bool
) -> tuple[str, bytes]:
    """(filename, zip bytes) for one run (a chat turn, usually)."""
    async with pool.connection() as conn:
        runs = RunRepository(conn)
        run = await runs.get(run_id)
        events = await runs.list_events(run_id, after_seq=0, limit=10_000)
        cur = await conn.execute(
            "SELECT r.agent_name, r.agent_version, a.id AS agent_id FROM runs r "
            "LEFT JOIN agents a ON a.name = r.agent_name WHERE r.id = %s",
            (run_id,),
        )
        row = await cur.fetchone() or {}
        session = messages = None
        if include_chat and run.session_id is not None:
            sessions = SessionRepository(conn)
            session = await sessions.get(run.session_id)
            messages = await sessions.messages(run.session_id, limit=10_000)
    try:
        version: str | None = metadata.version("durable-agent-runtime")
    except metadata.PackageNotFoundError:
        version = None

    files: dict[str, bytes] = {}
    agent_note = "a built-in agent (its definition ships with Nuria)"
    if row.get("agent_id") is not None:
        try:
            name, data, _ = await studio.export(row["agent_id"], row.get("agent_version"))
            files["agent.zip" if name.endswith(".zip") else "agent.md"] = data
            agent_note = f"yours, version {row.get('agent_version')}: see {next(iter(files))}"
        except Exception:  # an agent that no longer exports still gets its report
            agent_note = "yours, but it couldn't be exported"
    files["events.json"] = json.dumps(
        [_event(e, include_chat) for e in events], indent=2, ensure_ascii=False
    ).encode()
    if session is not None and messages is not None:
        files["chat.md"] = to_markdown(session, messages).encode()
    readme = "\n".join([
        "# A Nuria reply, for a bug report",
        "",
        f"- Nuria {version or 'unknown'} · made {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        f"- Run `{run.id}` ({run.kind}): **{run.status}**"
        + (f" ({run.reason})" if run.reason else "")
        + f", {run.steps} steps, taken over after a crash {run.reclaims} time(s),"
        f" handed off {run.releases} time(s)",
        f"- Agent: {row.get('agent_name') or run.graph_name} ({agent_note})",
        "- The conversation's text: "
        + ("**included** (chat.md, full events)" if include_chat else "**not included**"),
        "",
        "Files: " + ", ".join(sorted(files)) + ".",
        "",
    ]).encode()  # fmt: skip
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", readme)
        for name, data in sorted(files.items()):
            zf.writestr(name, data)
    return f"nuria-report-{str(run.id)[:8]}.zip", out.getvalue()
