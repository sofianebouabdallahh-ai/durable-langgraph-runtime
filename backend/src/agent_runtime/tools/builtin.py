"""Phase 4 fixture tools: one per risk class that exists in-process.

They are deliberately small. They exist to exercise the pipeline: a pure read,
an internal side effect, and an external side effect that needs approval.
Real tools (search, retrieve, run_python) arrive in phases 6-8.
"""

from __future__ import annotations

import ast
import asyncio
import operator
from typing import Annotated, Any

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from agent_runtime.memory.store import SHOWN_ID, Memory, Note, scope_of
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry

# ---------------------------------------------------------------- calculator

_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}  # fmt: skip
_UNARY_OPS: dict[type[ast.unaryop], Any] = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_eval(expression: str) -> float:
    """Arithmetic only. Never `eval`: the expression comes from a model, i.e. untrusted."""

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        value = node.value if isinstance(node, ast.Constant) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exponent too large")
            return float(_BIN_OPS[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return float(_UNARY_OPS[type(node.op)](walk(node.operand)))
        raise ValueError(f"unsupported expression element: {type(node).__name__}")

    return walk(ast.parse(expression, mode="eval"))


class CalculatorArgs(ToolArgs):
    expression: Annotated[str, Field(min_length=1, max_length=200)]


async def calculator(args: CalculatorArgs, ctx: ToolContext) -> dict[str, Any]:
    """Evaluate an arithmetic expression, e.g. "(2 + 3) * 4"."""
    return {"value": safe_eval(args.expression)}


# ------------------------------------------------------------------ save_note


class SaveNoteArgs(ToolArgs):
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    # Demo/test knob: wait after writing, which widens the window between the
    # side effect and the step's checkpoint (the crash scenario kills a worker here).
    # Kept out of the schema the model sees: a model read it as how long to keep the
    # note, sent a day, and the note wasn't saved.
    linger_s: SkipJsonSchema[Annotated[float, Field(ge=0, le=30)]] = 0.0


async def save_note(args: SaveNoteArgs, ctx: ToolContext) -> dict[str, Any]:
    """Save a note the person wants kept, to remember in this chat or a later one: it
    shows under "What you remember" from then on. Saving the same note twice keeps one
    copy. Keys, passwords and card numbers are never kept."""
    async with ctx.pool.connection() as conn:
        # The idempotency key is the primary key: re-executing after a crash can't
        # create a second row (R2.6). The fencing trigger rejects a stale epoch.
        memory = Memory(conn)
        note, before = await memory.save(
            key=ctx.key, run_id=ctx.run_id, epoch=ctx.epoch, text=args.text, author=_author(ctx)
        )
        older = await memory.related(
            await scope_of(conn, ctx.run_id, _author(ctx)), note.text, besides=note.key
        )
    if args.linger_s:
        await asyncio.sleep(args.linger_s)
    out: dict[str, Any] = {"note_id": note.id}
    if before:
        out["already_remembered"] = True
    if older:  # a fact that changed: the old note would contradict the new one
        out["maybe_out_of_date"] = _listed(older)
        # Direct, like the claim check's note: offered "if…", qwen2.5:7b told the person the
        # old note "can be forgotten if needed" and left it (2 of 2).
        out["hint"] = (
            "These older notes look like the same thing. If the new note replaces one (the "
            "fact changed), forget the old one now with forget_note: don't leave it, and "
            "don't ask the person."
        )
    return out


# --------------------------------------------------------------------- notify


class NotifyArgs(ToolArgs):
    to: Annotated[str, Field(min_length=1, max_length=200)]
    message: Annotated[str, Field(min_length=1, max_length=2000)]


async def notify(args: NotifyArgs, ctx: ToolContext) -> dict[str, Any]:
    """Send a notification to someone. Requires human approval."""
    async with ctx.pool.connection() as conn:
        # Transactional outbox: every worker's relay sends these to the webhook
        # (notifications/delivery.py, H4). The key makes the external effect happen once
        # no matter how often we retry, and is the delivery's `webhook-id`.
        await conn.execute(
            "INSERT INTO outbox_notifications (key, run_id, recipient, message, epoch) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING",
            (ctx.key, ctx.run_id, args.to, args.message, ctx.epoch),
        )
    sent = bool(getattr(ctx.settings, "notify_webhook_url", ""))
    return {
        "queued": True, "notification_id": ctx.key[:16],
        # Honest about where it goes (H4): with no webhook it's kept, not sent.
        "delivery": "sending to the notifications webhook" if sent
        else "kept, not sent: no notifications webhook is set up",
    }  # fmt: skip


# --------------------------------------------------------------- recall_notes


def _author(ctx: ToolContext) -> str | None:
    """Who keeps the note: the helper calling the tool, or None for the agent itself."""
    sub = ctx.subagent
    return str(sub.defn.frontmatter.name) if sub is not None else None


class RecallNotesArgs(ToolArgs):
    query: Annotated[str | None, Field(max_length=200)] = None
    limit: Annotated[int, Field(ge=1, le=20)] = 10


async def recall_notes(args: RecallNotesArgs, ctx: ToolContext) -> dict[str, Any]:
    """Search all the notes you saved with save_note, in any chat with you: newest first,
    optionally only those containing `query`. The newest are under "What you remember"
    already; this finds older ones."""
    async with ctx.pool.connection() as conn:
        # This same agent's (or this same helper's) notes, in any chat (H4); a test keeps
        # to its own chat (H6). The scope is the run's, never the model's (memory/store.py).
        memory = Memory(conn)
        notes = await memory.search(
            await scope_of(conn, ctx.run_id, _author(ctx)), args.query, args.limit
        )
    return {
        "notes": [{"id": n.id, "text": n.text, "saved_at": n.saved_at.isoformat()}
                  for n in notes],
        "count": len(notes),
    }  # fmt: skip


class ForgetNoteArgs(ToolArgs):
    note_id: Annotated[str, Field(min_length=6, max_length=64)]


async def forget_note(args: ForgetNoteArgs, ctx: ToolContext) -> dict[str, Any]:
    """Forget one of your notes when the person asks you to, or when it's out of date:
    give its id from "What you remember" (or recall_notes). It leaves your memory at
    once; the person can still restore it from the agent's page."""
    async with ctx.pool.connection() as conn:
        memory, scope = Memory(conn), await scope_of(conn, ctx.run_id, _author(ctx))
        found = await memory.forget(
            scope, args.note_id, key=ctx.key, run_id=ctx.run_id, epoch=ctx.epoch
        )
        others = [] if found is None else await memory.related(scope, found.text, besides=found.key)
    if found is None:
        raise LookupError(f"no note {args.note_id!r} in your memory: nothing was forgotten")
    out: dict[str, Any] = {"forgotten": found.text, "note_id": found.id}
    if others:  # "forget my locker code" with two notes of it
        out["still_remembered"] = _listed(others)
        # Offered "if the person meant these too", it forgot one of two and asked (2 of 2).
        out["hint"] = (
            "These are still in your memory and look like what the person asked you to "
            "forget. Forget each of them now with forget_note, unless one is clearly about "
            "something else."
        )
    return out


def _listed(notes: list[Note]) -> list[dict[str, str]]:
    return [{"id": n.key[:SHOWN_ID], "text": n.text} for n in notes]


class SearchArgs(ToolArgs):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    k: Annotated[int, Field(ge=1, le=10)] = 5


async def search(args: SearchArgs, ctx: ToolContext) -> dict[str, Any]:
    """Search the web for a query. Returns titles, URLs, snippets and page content.
    Cite the URLs you use."""
    from agent_runtime.config import get_agent_settings
    from agent_runtime.tools import search as fixtures

    found = fixtures.search(get_agent_settings().search_fixtures_dir, args.query, args.k)
    return {"query": args.query, "results": found}


def default_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.tool("calculator", args=CalculatorArgs, risk_class="read", side_effect=False)(
        calculator
    )
    registry.tool("search", args=SearchArgs, risk_class="read", side_effect=False)(search)
    # The side effects below dedupe by the idempotency key (a primary or unique key), so
    # a call a crash cut off is made again safely (H7).
    registry.tool(
        "save_note",
        args=SaveNoteArgs,
        risk_class="write_internal",
        side_effect=True,
        max_calls=20,
        retry_after_crash=True,
    )(save_note)
    registry.tool(
        "recall_notes",
        args=RecallNotesArgs,
        risk_class="read",
        side_effect=False,
        repeatable=True,
    )(recall_notes)
    registry.tool(
        "forget_note",
        args=ForgetNoteArgs,
        risk_class="write_internal",
        side_effect=True,
        max_calls=20,
        retry_after_crash=True,  # a forget is keyed by the call: made again, it's a no-op
    )(forget_note)
    registry.tool(
        "notify",
        args=NotifyArgs,
        risk_class="external_side_effect",
        side_effect=True,
        max_calls=5,
        retry_after_crash=True,
    )(notify)
    from agent_runtime.agents import builder  # the Studio's builder agents' answers
    from agent_runtime.sandbox import tools as sandbox_tools  # code and shell (L6b)
    from agent_runtime.skills import tools as skill_tools  # granted by the harness
    from agent_runtime.subagents import tools as subagent_tools  # granted by the harness
    from agent_runtime.web import tools as web_tools  # the real tools (L6a)

    return sandbox_tools.register(
        web_tools.register(
            builder.register(skill_tools.register(subagent_tools.register(registry)))
        )
    )
