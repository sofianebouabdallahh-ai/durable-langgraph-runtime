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
    linger_s: Annotated[float, Field(ge=0, le=30)] = 0.0


async def save_note(args: SaveNoteArgs, ctx: ToolContext) -> dict[str, Any]:
    """Save a short note for later. Saving the same note twice in a run keeps one copy."""
    async with ctx.pool.connection() as conn:
        # The idempotency key is the primary key: re-executing after a crash can't
        # create a second row (R2.6). The fencing trigger rejects a stale epoch.
        await conn.execute(
            "INSERT INTO notes (key, run_id, text, epoch) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (key) DO NOTHING",
            (ctx.key, ctx.run_id, args.text, ctx.epoch),
        )
    if args.linger_s:
        await asyncio.sleep(args.linger_s)
    return {"note_id": ctx.key[:16]}


# --------------------------------------------------------------------- notify


class NotifyArgs(ToolArgs):
    to: Annotated[str, Field(min_length=1, max_length=200)]
    message: Annotated[str, Field(min_length=1, max_length=2000)]


async def notify(args: NotifyArgs, ctx: ToolContext) -> dict[str, Any]:
    """Send a notification to someone. Requires human approval."""
    async with ctx.pool.connection() as conn:
        # Transactional outbox: a delivery process (out of scope) sends these. The
        # key makes the external effect happen once no matter how often we retry.
        await conn.execute(
            "INSERT INTO outbox_notifications (key, run_id, recipient, message, epoch) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING",
            (ctx.key, ctx.run_id, args.to, args.message, ctx.epoch),
        )
    return {"queued": True, "notification_id": ctx.key[:16]}


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
    registry.tool(
        "save_note", args=SaveNoteArgs, risk_class="write_internal", side_effect=True, max_calls=20
    )(save_note)
    registry.tool(
        "notify", args=NotifyArgs, risk_class="external_side_effect", side_effect=True, max_calls=5
    )(notify)
    from agent_runtime.agents import builder  # the Studio's builder agents' answers
    from agent_runtime.skills import tools as skill_tools  # granted by the harness
    from agent_runtime.subagents import tools as subagent_tools  # granted by the harness
    from agent_runtime.web import tools as web_tools  # the real tools (L6a)

    return web_tools.register(
        builder.register(skill_tools.register(subagent_tools.register(registry)))
    )
