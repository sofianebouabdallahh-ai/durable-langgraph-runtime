"""RuntimeMiddleware: adapts the runtime to LangChain's create_agent (Adapter).

- Tool calls: every call goes through the ToolPipeline; LangChain's own tool
  execution is never used. Unknown tool names reach us too (request.tool is
  None) and are denied and audited (phase 4 research).
- Model calls: each is charged against the run's budget first (R14.1), then
  served by the model chosen for this run (phase 4: the scripted model;
  phase 6 adds real providers behind the same seam).

Everything run-specific arrives through LangGraph's runtime context
(`RunContext`), set by the executor for each execution.

Sub-agents (CR-005) use the same middleware with `RunContext.subagent` set:
- a model call is charged to the sub-agent's max_turns AND the run's budget,
  after a cooperative cancel check (between steps, R16.4);
- once `return_result` was called, the next model call short-circuits to a
  final answer, which ends the sub-agent's loop without another model call;
- at the soft limit a wrap-up note is added to the request (R16.8).
A main agent with sub-agents (`RunContext.orchestrator`) gets the turn guard
(R16.9): a final answer while sub-agents run → wait for them, then one more
model call that sees their results.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NotRequired, Protocol, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    AgentState,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from langgraph.types import Command

from agent_runtime import genai, logs, metrics, telemetry
from agent_runtime.context import compact
from agent_runtime.context.fit import ContextOverflow, estimate, fit, overflow
from agent_runtime.fencing import FencedError
from agent_runtime.memory import prompt as memory_prompt
from agent_runtime.memory.prompt import Snapshot, with_memory
from agent_runtime.memory.store import Memory, Note, scope_of
from agent_runtime.models.retry import ModelCaller
from agent_runtime.models.scripted import ScriptedChatModel, ScriptTurn
from agent_runtime.runs.events import EventType
from agent_runtime.sessions.turns import script_offset
from agent_runtime.tools.hooks import (
    Continue,
    Deny,
    HookSpec,
    ModelHookInput,
    ModelReplyInput,
    SessionHookInput,
    TurnHookInput,
    run_context_hooks,
    run_model_hooks,
)
from agent_runtime.tools.invocations import BudgetExceeded, LoopDetected, charge_model_call
from agent_runtime.tools.pipeline import ToolCall, ToolPipeline, ToolRunContext, truncate
from agent_runtime.untrusted import as_data

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agent_runtime.runs.limits import RunLimits
    from agent_runtime.subagents.orchestrator import SubagentOrchestrator, SubagentRuntime


class TurnDenied(Exception):
    """A turn_start (or session_start) hook rejected the turn (R15.5)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UsageRecorder(Protocol):
    """Records a model call's tokens, cost and time the moment it returns (durably, in
    the run's totals: phase H2); returns the cost."""

    async def __call__(
        self, model: str, tokens_in: int, tokens_out: int, seconds: float = ...
    ) -> float: ...


@dataclass(frozen=True)
class TurnInfo:
    """Who this run is, for session and turn hooks (CR-004 R15.5, R15.6)."""

    run_id: uuid.UUID
    session_id: uuid.UUID | None
    agent: str
    message: str
    session_start: list[HookSpec] = field(default_factory=list)
    turn_start: list[HookSpec] = field(default_factory=list)
    pre_model: list[HookSpec] = field(default_factory=list)  # H4
    post_model: list[HookSpec] = field(default_factory=list)


class RuntimeState(AgentState[Any]):
    """The agent's state, plus what the harness must remember across turns."""

    session_started: NotRequired[bool]  # session_start ran (checkpointed: never twice)
    # What it remembers this turn (H8): taken when the turn starts, so a turn taken over
    # after a crash sees what it started with. In the system message, never the thread.
    memory: NotRequired[Snapshot]


@dataclass
class RunContext:
    tools: ToolRunContext
    pipeline: ToolPipeline
    max_model_calls: int | None = None
    script: list[ScriptTurn] = field(default_factory=list)
    orchestrator: SubagentOrchestrator | None = None  # a main agent with sub-agents
    subagent: SubagentRuntime | None = None  # this graph IS a sub-agent
    turn: TurnInfo | None = None  # main agents: session and turn hooks
    caller: ModelCaller = field(default_factory=ModelCaller)  # retries + breaker (R14.7)
    limits: RunLimits | None = None  # the run's budgets, for the soft limit (R14.2)
    soft_limit_ratio: float = 0.8
    # (model, in, out tokens) → cost in USD
    record_usage: UsageRecorder | None = None
    # The chat model for one call (the provider's; R3.1). Given the scripted model's
    # offset; the default is the scripted model with this run's script.
    chat_model: Callable[[int], BaseChatModel] | None = None
    # The model's context window (tokens), pinned with the run's bindings (phase H5);
    # lowered for the rest of the run when the provider states a smaller one.
    context_tokens: int = 128_000
    trim_reported: int = 0  # how much fitting was last reported (no event per call)

    def model_for(self, offset: int) -> BaseChatModel:
        if self.chat_model is not None:
            return self.chat_model(offset)
        return ScriptedChatModel(script=self.script, offset=offset)

    async def soft_limit(self) -> str | None:
        """The first budget at ≥ soft_limit_ratio of its limit, as a failure reason."""
        if self.limits is None:
            return None
        async with self.tools.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT model_calls, tool_calls_total, tokens, cost FROM runs WHERE id = %s",
                (self.tools.fence.run_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        for reason, used, limit in (
            ("budget:model_calls", row["model_calls"], self.max_model_calls),
            ("budget:tool_calls", row["tool_calls_total"], self.limits.max_tool_calls),
            ("budget:tokens", row["tokens"], self.limits.max_tokens),
            ("budget:cost", float(row["cost"]), self.limits.max_cost_usd),
        ):
            if limit and used >= self.soft_limit_ratio * limit:
                return reason
        return None


def call_index(messages: list[Any], tool_call_id: str) -> int:
    """Position of this tool call among all tool calls in the conversation.

    Derived from the checkpointed messages, so a replay computes the same index
    and therefore the same idempotency key (R2.6)."""
    index = 0
    for message in messages:
        if isinstance(message, AIMessage):
            for tc in message.tool_calls:
                if tc["id"] == tool_call_id:
                    return index
                index += 1
    return index


class RuntimeMiddleware(AgentMiddleware[Any, RunContext]):
    state_schema = RuntimeState

    async def abefore_agent(
        self, state: Any, runtime: Runtime[RunContext]
    ) -> dict[str, Any] | None:
        """At the start of every run (a node, so its result is checkpointed):
        session_start once per session (the flag lives in the thread's state, so a
        reclaimed first turn doesn't repeat it), then turn_start. Both may add
        context; a deny rejects the turn. Fail closed (R15.8). First, for an agent or
        helper with notes, what it remembers (H8)."""
        ctx = runtime.context
        if ctx is None:
            return None
        update: dict[str, Any] = {}
        if (remembered := await self._remember(ctx)) is not None:
            update["memory"] = remembered
        turn = ctx.turn
        if turn is None:
            return update or None
        texts: list[str] = []
        session_texts: list[str] = []
        if turn.session_id is not None and not state.get("session_started"):
            started = await run_context_hooks(
                turn.session_start, SessionHookInput(str(turn.session_id), turn.agent)
            )
            if isinstance(started, Deny):
                raise TurnDenied(started.reason)
            session_texts = started.texts
            update["session_started"] = True
        begun = await run_context_hooks(turn.turn_start, TurnHookInput(
            str(turn.run_id), str(turn.session_id) if turn.session_id else None,
            turn.agent, turn.message,
        ))  # fmt: skip
        if isinstance(begun, Deny):
            raise TurnDenied(begun.reason)
        texts += begun.texts
        # session_start's context is said once per chat: its id marks it, so compaction
        # keeps it word for word (H5); turn_start's is per turn.
        added = [SystemMessage(content=t, id=compact.session_context_id(turn.run_id, k))
                 for k, t in enumerate(session_texts)]  # fmt: skip
        added += [SystemMessage(content=t) for t in texts]
        # A long chat's older turns become one summary, here: before this turn writes a
        # transcript row or records a tool call, so every id and key it makes is computed
        # from the compacted thread (phase H5, context/compact.py).
        kept = await self._compact(ctx, list(state.get("messages", [])), turn)
        if kept is not None:
            update["messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES), *kept, *added]
        elif added:
            update["messages"] = added
        return update or None

    @staticmethod
    async def _remember(ctx: RunContext) -> Snapshot | None:
        """The turn's memory snapshot, for an agent or helper granted save_note: its own
        notes, scoped by the run row (memory/store.py)."""
        if "save_note" not in ctx.tools.grants:
            return None
        sub = ctx.subagent
        author = str(sub.defn.frontmatter.name) if sub is not None else None
        async with ctx.tools.pool.connection() as conn:
            scope = await scope_of(conn, ctx.tools.fence.run_id, author)
            return await memory_prompt.snapshot(Memory(conn), scope)

    async def _compact(
        self, ctx: RunContext, messages: list[Any], turn: TurnInfo
    ) -> list[Any] | None:
        """The thread's messages after compaction, or None when it fits."""
        planned = compact.plan(messages, ctx.context_tokens, run_id=turn.run_id)
        if planned is None:
            return None
        text, how = await self._summarise(ctx, planned.old)
        kept = [compact.summary_message(text, turn.run_id), *planned.keep]
        after = estimate(kept)
        ctx.tools.emit(EventType.CONTEXT_COMPACTED, {
            "turns": planned.turns, "tokens_before": planned.tokens_before,
            "tokens_after": after, "how": how, "window": ctx.context_tokens,
        })  # fmt: skip
        logs.event(log, f"context compacted: {planned.turns} turn(s) summarised", how=how,
                   tokens_before=planned.tokens_before, tokens_after=after)  # fmt: skip
        return kept

    async def _summarise(self, ctx: RunContext, old: list[Any]) -> tuple[str, str]:
        """The summary of `old`: by the agent's own model (charged like any call, its
        retries and breaker; nothing streamed), else extracted without a model (the
        scripted model, or the call failed)."""
        max_chars = max(int(ctx.context_tokens * 4 * 0.15), 1_000)  # ≤ ~15% of the window
        model = ctx.model_for(0)
        if not isinstance(model, ScriptedChatModel):
            room = max(int((ctx.context_tokens - 2_000) * 4 * 0.8), 4_000)
            history = compact.transcript(old)
            if len(history) > room:  # the start (an earlier summary) and the latest turns
                history = f"{history[: room // 3]}\n…\n{history[-(room * 2 // 3) :]}"
            prompt = [SystemMessage(content=compact.SUMMARY_PROMPT),
                      HumanMessage(content=as_data("conversation", history))]  # fmt: skip

            async def call() -> Any:
                return await model.ainvoke(prompt, config={"callbacks": []})

            try:
                reply = await ctx.caller.call(call, charge=lambda: self._charge(ctx))
                await self._account(ctx, ModelResponse(result=[reply]))
                text = str(reply.text).strip()
                if text:
                    return text[:max_chars], "model"
            except (BudgetExceeded, FencedError):
                raise  # the budget is spent or the run was taken over: not a fallback
            except Exception:
                log.warning("summarising with the model failed; extracting instead",
                            exc_info=True)  # fmt: skip
        return compact.extract(old, max_chars=max_chars), "extract"

    async def awrap_model_call(
        self,
        request: ModelRequest[RunContext],
        handler: Callable[[ModelRequest[RunContext]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """One model step, with every guardrail around it:

        charge (before each attempt, R14.7) → soft limit (R14.2: main agents get one
        wrap-up call with no tools; sub-agents a note) → call, with retries and the
        breaker → usage (tokens, cost) staged with the step → no-progress check
        (R14.4) → turn guard (R16.9)."""
        ctx = request.runtime.context
        sub = ctx.subagent
        if sub is not None and sub.returned is not None:  # return_result: end the loop here
            return ModelResponse(result=[AIMessage(content=str(sub.returned["summary"]))])
        turn = ctx.turn if sub is None else None
        await _pre_model(turn, request, request.messages)
        model = ctx.model_for(script_offset(request.state.get("messages", [])))
        wrap_up: list[str | None] = [None]

        attempts = [0]

        async def charge() -> None:
            attempts[0] += 1
            if sub is not None:
                await sub.before_model()  # cancel check + its own and the run's budget
                return
            # The soft limit is checked BEFORE the charge, so the wrap-up call (R14.2) is
            # charged as the one call allowed past a limit (phase H2).
            if wrap_up[0] is None and (kind := await ctx.soft_limit()):
                metrics.budget_warning(kind)
                logs.event(log, f"budget nearly used: {kind}", budget=kind,
                           level=logging.WARNING)  # fmt: skip
                wrap_up[0] = kind
            await self._charge(ctx, wrap_up=wrap_up[0] is not None)

        async def charge_again() -> None:
            """A follow-up call (the empty-reply nudge, the turn guard): charged like any
            call. It keeps its tools, so it never takes the wrap-up's allowance."""
            attempts[0] += 1
            if sub is not None:
                await sub.before_model()
            else:
                await self._charge(ctx)

        async def attempt() -> ModelResponse[Any]:
            req = request.override(model=model)
            if sub is not None and sub.orchestrator.wrap_up:
                from agent_runtime.subagents.orchestrator import WRAP_UP_NOTE

                req = req.override(messages=[*req.messages, HumanMessage(content=WRAP_UP_NOTE)])
            elif (kind := wrap_up[0]) is not None:  # R14.2: one wrap-up call, with no tools
                req = req.override(tools=[], messages=[*req.messages, SystemMessage(
                    content=WRAP_UP_TURN.format(kind=kind.removeprefix("budget:")))])  # fmt: skip
            return await _send(ctx, handler, req)

        response = await self._call(ctx, attempt, charge, attempts)
        if _is_empty(response) and wrap_up[0] is None:  # once, charged like any call
            logs.event(log, "empty model reply: asking once more", level=logging.WARNING)
            nudged: list[Any] = [*request.messages, *response.result, HumanMessage(EMPTY_REPLY)]
            await _pre_model(turn, request, nudged)  # every call the model gets

            async def again() -> ModelResponse[Any]:
                return await _send(ctx, handler, request.override(model=model, messages=nudged))

            response = await self._call(ctx, again, charge_again, attempts)
        orchestrator = ctx.orchestrator
        names = _tool_names(request)
        if wrap_up[0] is None:  # the wrap-up has no tools: nothing to repair
            response = _from_text_calls(response, names)
            # Not while helpers work (one may be saving it), nor near a limit: the answer
            # in hand is better than a turn that fails on the extra call.
            helping = orchestrator is not None and orchestrator.running()
            tool = None if helping else _claims_undone(request.messages, response, names)
            if tool and (sub is not None or await ctx.soft_limit() is None):  # once, charged
                response = await self._honest(ctx, request, handler, model, turn, response,
                                              tool, charge_again, attempts)  # fmt: skip
                response = _from_text_calls(response, names)
        _check_progress(request.state.get("messages", []), response)
        if wrap_up[0] is not None:
            return await _post_model(turn, _budget_limited(response, wrap_up[0]))
        if orchestrator is not None and _is_final(response) and orchestrator.running():
            outcomes = await orchestrator.wait_all()
            # The outcomes are the helpers' words: data, like wait_subagents' output (H4).
            results = truncate(json.dumps(outcomes, default=str), ctx.pipeline.max_result_chars)
            note = HumanMessage(
                content="[runtime] Your sub-agents were still running, so the runtime waited "
                "for them before you finish. Their results:\n" + as_data("subagents", results)
            )
            messages: list[Any] = [*request.messages, *response.result, note]
            await _pre_model(turn, request, messages)  # it carries the helpers' words

            async def guarded() -> ModelResponse[Any]:
                return await _send(ctx, handler, request.override(model=model, messages=messages))

            response = _from_text_calls(
                await self._call(ctx, guarded, charge_again, attempts), names
            )
        return await _post_model(turn, response)

    async def _honest(
        self,
        ctx: RunContext,
        request: ModelRequest[RunContext],
        handler: Callable[[ModelRequest[RunContext]], Awaitable[ModelResponse[Any]]],
        model: BaseChatModel,
        turn: TurnInfo | None,
        reply: ModelResponse[Any],
        tool: str,
        charge: Callable[[], Awaitable[None]],
        attempts: list[int],
    ) -> ModelResponse[Any]:
        """The model asked once more, after a reply saying `tool` did what it didn't. If
        that call can't be made (a budget, the provider), the first reply stands: a turn
        that ends with it beats one that fails."""
        from agent_runtime.runs.executor import CancelRequested, LeaseLost, ReleaseRequested
        from agent_runtime.subagents.orchestrator import SubagentCancelled

        logs.event(log, "a reply says a tool did what it didn't: asking once more",
                   tool=tool, level=logging.WARNING)  # fmt: skip
        claimed: list[Any] = [*request.messages, *reply.result, HumanMessage(CLAIMED[tool])]
        await _pre_model(turn, request, claimed)

        async def honest() -> ModelResponse[Any]:
            return await _send(ctx, handler, request.override(model=model, messages=claimed))

        try:
            return await self._call(ctx, honest, charge, attempts)
        except (FencedError, LeaseLost, CancelRequested, ReleaseRequested, SubagentCancelled):
            raise  # taken over, stopped (Stop raises from the token stream), handed over
        except Exception:
            log.warning("asking once more failed; keeping the first reply", exc_info=True)
            return reply

    async def _call(
        self,
        ctx: RunContext,
        attempt: Callable[[], Awaitable[ModelResponse[Any]]],
        charge: Callable[[], Awaitable[None]],
        attempts: list[int],
    ) -> ModelResponse[Any]:
        """One model call (with its retries) in an `llm.call` span (R7.1): model,
        tokens, cost and attempts as attributes; usage staged with the step."""
        first = attempts[0]
        attrs = {"subagent": ctx.subagent.defn.frontmatter.name} if ctx.subagent else {}
        with telemetry.child_span("llm.call", attrs) as span:
            t0 = time.monotonic()
            response = await ctx.caller.call(attempt, charge=charge)
            seconds = time.monotonic() - t0
            span.set_attribute("llm.attempts", attempts[0] - first)
            for model, tokens_in, tokens_out, cost in await self._account(ctx, response, seconds):
                metrics.llm_latency(model, seconds)
                span.set_attributes({
                    "llm.model": model, "llm.tokens_in": tokens_in,
                    "llm.tokens_out": tokens_out, "llm.cost_usd": cost,
                    **genai.chat(model, tokens_in, tokens_out),
                })  # fmt: skip
                logs.event(
                    log, f"model call: {model}", model=model, tokens_in=tokens_in,
                    tokens_out=tokens_out, cost=round(cost, 6),
                    duration_ms=round(seconds * 1000), attempts=attempts[0] - first,
                )  # fmt: skip
            span.set_attribute("llm.tool_calls", sum(
                len(m.tool_calls) for m in response.result if isinstance(m, AIMessage)
            ))  # fmt: skip
        return response

    @staticmethod
    async def _charge(ctx: RunContext, *, wrap_up: bool = False) -> None:
        limits = ctx.limits
        async with ctx.tools.pool.connection() as conn:
            await charge_model_call(
                conn, fence=ctx.tools.fence, max_calls=ctx.max_model_calls,
                max_tokens=limits.max_tokens if limits else None,
                max_cost_usd=limits.max_cost_usd if limits else None, wrap_up=wrap_up,
            )  # fmt: skip

    @staticmethod
    async def _account(
        ctx: RunContext, response: ModelResponse[Any], seconds: float = 0.0
    ) -> list[tuple[str, int, int, float]]:
        """Tokens and cost, recorded the moment the call returns (R14.1, phase H2).
        Returns (model, tokens in, tokens out, cost) per message, for the span."""
        usage: list[tuple[str, int, int, float]] = []
        for m in response.result:
            if isinstance(m, AIMessage) and m.usage_metadata:
                u = m.usage_metadata
                model = str(m.response_metadata.get("model_name", "scripted"))
                tokens_in, tokens_out = (
                    int(u.get("input_tokens", 0)),
                    int(u.get("output_tokens", 0)),
                )
                cost = (
                    await ctx.record_usage(model, tokens_in, tokens_out, seconds)
                    if ctx.record_usage
                    else 0.0
                )
                usage.append((model, tokens_in, tokens_out, cost))
        return usage

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        ctx: RunContext = request.runtime.context  # type: ignore[assignment]
        if ctx.subagent is not None:
            await ctx.subagent.before_tool()  # a cancel stops it before its tool call (R16.4)
        tc = request.tool_call
        call = ToolCall(
            id=str(tc["id"]),
            name=tc["name"],
            args=dict(tc["args"]),
            index=call_index(request.state["messages"], str(tc["id"])),
            node=ctx.tools.node,
        )
        result = await ctx.pipeline.run(call, ctx.tools)
        return ToolMessage(
            content=result.content, tool_call_id=call.id, name=call.name, status=result.status
        )


async def _send(
    ctx: RunContext,
    handler: Callable[[ModelRequest[RunContext]], Awaitable[ModelResponse[Any]]],
    req: ModelRequest[RunContext],
) -> ModelResponse[Any]:
    """Send `req` fitted to the model's context window (phase H5): old tool results
    cleared, then long older messages cut, in what's SENT only. A provider that still
    says it's too long gets it fitted again, smaller, once; then ContextOverflow. What it
    remembers is filled in for the window as it stands (H8)."""
    original = req
    memory = await _memory_of(ctx, req)
    req = _remembering(ctx, original, memory)
    system = estimate([req.system_message]) if req.system_message else 0
    window = ctx.context_tokens - system
    fitted = fit(req.messages, window, req.tools)
    if fitted.changed and fitted.cleared + fitted.shortened > ctx.trim_reported:
        ctx.trim_reported = fitted.cleared + fitted.shortened  # an event when it grows only
        ctx.tools.emit(EventType.CONTEXT_TRIMMED, {
            "cleared": fitted.cleared, "shortened": fitted.shortened,
            "tokens_before": fitted.tokens_before, "tokens_after": fitted.tokens_after,
        })  # fmt: skip
    try:
        return await handler(req.override(messages=fitted.messages) if fitted.changed else req)
    except Exception as exc:
        too_long, stated = overflow(exc)
        if not too_long:
            raise
        if stated:  # the model's real window: the rest of the run is fitted to it
            ctx.context_tokens = min(ctx.context_tokens, stated)
            req = _remembering(ctx, original, memory)  # less memory for a smaller window
            system = estimate([req.system_message]) if req.system_message else 0
        smaller = int(min((stated or ctx.context_tokens) - system, window) * 0.7)
        refit = fit(req.messages, smaller, req.tools, trim_at=0.4, shorten_at=0.6,
                    keep_results=0, protect_latest=False)  # fmt: skip
        logs.event(log, "the model said the request was too long: fitting it again",
                   level=logging.WARNING, window=stated, tokens=refit.tokens_after)  # fmt: skip
        ctx.tools.emit(EventType.CONTEXT_TRIMMED, {
            "cleared": refit.cleared, "shortened": refit.shortened, "refused": True,
            "tokens_before": refit.tokens_before, "tokens_after": refit.tokens_after,
        })  # fmt: skip
        try:
            return await handler(req.override(messages=refit.messages))
        except Exception as again:
            if overflow(again)[0]:
                raise ContextOverflow(str(again)[:500]) from again
            raise


async def _memory_of(
    ctx: RunContext, req: ModelRequest[RunContext]
) -> tuple[Snapshot | None, list[Note]] | None:
    """The turn's snapshot and its notes as they stand now, for an agent or helper granted
    save_note (H8); None for any other."""
    if "save_note" not in ctx.tools.grants or req.system_message is None:
        return None
    snap = cast("Snapshot | None", req.state.get("memory"))
    if snap is None:
        return None, []
    async with ctx.tools.pool.connection() as conn:
        return snap, await memory_prompt.remembered(Memory(conn), snap)


def _remembering(
    ctx: RunContext, req: ModelRequest[RunContext],
    memory: tuple[Snapshot | None, list[Note]] | None,
) -> ModelRequest[RunContext]:  # fmt: skip
    """`req` with what it remembers in its system message, for the window as it stands."""
    if memory is None or req.system_message is None:
        return req
    body = memory_prompt.section(*memory, ctx.context_tokens)
    text = with_memory(req.system_message.text, body)
    return req.override(system_message=SystemMessage(content=text))


async def _pre_model(
    turn: TurnInfo | None, request: ModelRequest[RunContext], messages: list[Any]
) -> None:
    """pre_model hooks (H4), before each of a main agent's model calls (with the
    messages that call sends): continue, or deny the turn. Fail closed."""
    if turn is None or not turn.pre_model:
        return
    last = messages[-1] if messages else None
    tools = [str(getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else ""))
             for t in request.tools]  # fmt: skip
    decided = await run_model_hooks(turn.pre_model, ModelHookInput(
        str(turn.run_id), str(turn.session_id) if turn.session_id else None, turn.agent,
        last.text if last is not None else "", tools,
    ))  # fmt: skip
    if isinstance(decided, Deny):
        logs.event(log, "a pre_model hook denied the turn", reason=decided.reason,
                   level=logging.WARNING)  # fmt: skip
        raise TurnDenied(decided.reason)


async def _post_model(turn: TurnInfo | None, response: ModelResponse[Any]) -> ModelResponse[Any]:
    """post_model hooks (H4): continue, change the reply's text (its tool calls stay),
    or deny the turn. Fail closed."""
    if turn is None or not turn.post_model:
        return response
    at = next((i for i in range(len(response.result) - 1, -1, -1)
               if isinstance(response.result[i], AIMessage)), None)  # fmt: skip
    if at is None:
        return response
    reply = response.result[at]
    assert isinstance(reply, AIMessage)
    decided = await run_model_hooks(turn.post_model, ModelReplyInput(
        str(turn.run_id), str(turn.session_id) if turn.session_id else None, turn.agent,
        reply.text, [{"name": c["name"], "args": c["args"]} for c in reply.tool_calls],
    ))  # fmt: skip
    if isinstance(decided, Deny):
        logs.event(log, "a post_model hook denied the reply", reason=decided.reason,
                   level=logging.WARNING)  # fmt: skip
        raise TurnDenied(decided.reason)
    if isinstance(decided, Continue):
        return response
    result = list(response.result)
    result[at] = reply.model_copy(update={"content": _with_text(reply.content, decided.value)})
    return ModelResponse(result=result, structured_response=response.structured_response)


def _with_text(content: str | list[Any], text: str) -> str | list[Any]:
    """The reply's content with its text replaced by `text`, its other blocks (a
    provider's reasoning, its signatures) kept as they were."""
    if isinstance(content, str):
        return text
    kept = [b for b in content if isinstance(b, dict) and b.get("type") != "text"]
    return [*kept, {"type": "text", "text": text}]


def _is_empty(response: ModelResponse[Any]) -> bool:
    """No text and no tool call: what a small model's unparsable tool call becomes (seen
    on qwen2.5:7b via Ollama: 183 tokens written, nothing usable). The agent would end
    with an empty answer, so it's asked once more."""
    ai = [m for m in response.result if isinstance(m, AIMessage)]
    return bool(ai) and not any(m.tool_calls or m.text.strip() for m in ai)


def _tool_names(request: ModelRequest[RunContext]) -> set[str]:
    """The names of the tools this call offers the model."""
    names: set[str] = set()
    for tool in request.tools:
        if isinstance(tool, dict):
            fn = tool.get("function")
            name = fn.get("name") if isinstance(fn, dict) else tool.get("name")
        else:
            name = getattr(tool, "name", None)
        if isinstance(name, str):
            names.add(name)
    return names


_CALL_OPEN = re.compile(r"([A-Za-z_][\w-]*)\s*\(\s*")
_FENCE = re.compile(r"^```[\w-]*\s*|\s*```$")
# A last block may lack its closing tag (a small model stops, or is cut off).
_TAGGED = re.compile(r"<tool_call>(.*?)(?:</tool_call>|\Z)", re.DOTALL)


def _text_calls(text: str, names: set[str]) -> list[dict[str, Any]] | None:
    """The tool calls a reply's whole text writes out instead of making them, or None
    when the text is anything else. Seen on qwen2.5:7b via Ollama, about half the time:
    `save_note({"text": "demo is on Friday"})` as the reply, the note never saved. The
    forms: `name({...})` or `name()`, `<tool_call>{"name": …, "arguments": {…}}</tool_call>`,
    and that JSON bare, each for a tool offered, one after another and nothing else."""
    s = _FENCE.sub("", text.strip())
    if "<tool_call>" in s:  # only the tagged blocks, and nothing around them
        if _TAGGED.sub("", s).strip():
            return None
        s = "\n".join(_TAGGED.findall(s))
    decoder = json.JSONDecoder()
    calls: list[dict[str, Any]] = []
    i = 0
    while True:
        while i < len(s) and s[i] in " \t\r\n;,":
            i += 1
        if i == len(s):
            return calls or None
        name: Any
        args: Any
        try:
            if opened := _CALL_OPEN.match(s, i):  # name({...}) or name()
                name, i = opened.group(1), opened.end()
                args = {}
                if s[i : i + 1] != ")":
                    args, i = decoder.raw_decode(s, i)
                while i < len(s) and s[i].isspace():
                    i += 1
                if s[i : i + 1] != ")":
                    return None
                i += 1
            else:  # {"name": ..., "arguments": {...}}
                obj, i = decoder.raw_decode(s, i)
                if not isinstance(obj, dict):
                    return None
                name, args = obj.get("name"), obj.get("arguments", obj.get("parameters"))
                if isinstance(args, str):
                    args = json.loads(args)
        except ValueError:
            return None
        # A JSON answer that merely has a "name" ({"name": {"first": "Ada"}}) is an answer.
        if not isinstance(name, str) or name not in names or not isinstance(args, dict):
            return None
        calls.append({"name": name, "args": args})


def _from_text_calls(response: ModelResponse[Any], names: set[str]) -> ModelResponse[Any]:
    """A reply that only writes out tool calls, made into those calls: they go through
    the pipeline like any other (grants, approvals, the ledger), and the person never
    sees the call as the answer. Anything unexpected keeps the reply as it was."""
    result = list(response.result)
    for at, m in enumerate(result):
        if not isinstance(m, AIMessage) or m.tool_calls or not m.text.strip():
            continue
        try:
            calls = _text_calls(m.text, names)
        except Exception:  # a repair never fails a turn
            log.warning("reading a reply as tool calls failed; keeping it", exc_info=True)
            continue
        if calls is None:
            continue
        logs.event(log, "a tool call written as text: made it",
                   tools=",".join(c["name"] for c in calls), level=logging.WARNING)  # fmt: skip
        # 9 letters and digits: the strictest id an OpenAI-compatible service asks for.
        result[at] = m.model_copy(update={"content": "", "tool_calls": [
            {"name": c["name"], "args": c["args"], "id": uuid.uuid4().hex[:9],
             "type": "tool_call"} for c in calls
        ]})  # fmt: skip
    return ModelResponse(result=result, structured_response=response.structured_response)


# What a reply may claim a tool did ("I've saved that", "has been sent"), by tool; what
# the person's message asks for, for that claim to be one; and words that undo a claim
# ("nothing has been saved", "as I noted").
_APOS = "['\u2019]"
_I = r"\b(?:I(?:" + _APOS + r"ve| have| just)?\s+(?:\w+ly\s+|also\s+|now\s+|just\s+)?"
# A reply that names the tool as called ("save_note called with…") claims it too.
_CALLED = r"|called\s+{t}|{t}\s+(?:was\s+|has\s+been\s+)?called"
_CLAIMS = {
    "save_note": re.compile(
        _I + r"(?:saved|noted|stored|recorded|remembered)"
        r"|(?:has|have)\s+been\s+(?:saved|noted|stored)"
        + _CALLED.format(t="save_note") + r")\b", re.IGNORECASE,
    ),
    "notify": re.compile(
        _I + r"(?:sent|notified|let\s+\w+(?:\s+\w+)?\s+know)"
        r"|(?:has|have)\s+been\s+(?:sent|notified)|\b(?:message|notification)\s+sent"
        + _CALLED.format(t="notify") + r")\b", re.IGNORECASE,
    ),
    # "Forgotten", or deleted from its notes: "I've removed the onions" is about a list.
    "forget_note": re.compile(
        _I + r"(?:forgotten|(?:deleted|removed|erased)\b[^.?!]{0,30}\b(?:notes?|memory))"
        r"|(?:has|have)\s+been\s+forgotten|\bnote\s+(?:has\s+been\s+)?(?:deleted|removed|erased)"
        + _CALLED.format(t="forget_note") + r")\b", re.IGNORECASE,
    ),
}  # fmt: skip
# Asked of the agent: not "send me…" or "tell me…", the answer itself; not "keep it short".
_ASKS = {
    "save_note": re.compile(
        r"\b(?:remember|note|notes|save|keep\s+in\s+mind|keep\s+track|don" + _APOS
        + r"?t\s+forget|write\s+(?:it|this|that)\s+down|jot)\b", re.IGNORECASE,
    ),
    "notify": re.compile(
        r"\b(?:notify|notification|(?:send|tell|text|message|ping|email)(?!\s+me\b)"
        r"|let\s+(?!me\b)\w+\s+know)\b", re.IGNORECASE,
    ),
    # "Forget" something remembered ("my locker code", "what I told you"), not "don't
    # forget …" (that's a note) nor "forget it" / "forget the onions"; deleting only
    # what's remembered ("remove the onions" is about a recipe).
    "forget_note": re.compile(
        r"(?<!n" + _APOS + r"t\s)(?<!dont\s)(?<!not\s)(?<!never\s)\bforget\b[^.?!]{0,40}?"
        r"\b(?:notes?|memory|memories|code|number|address|password|birthday|name|"
        r"what\s+I|that\s+I|everything\s+(?:about|you))\b"
        r"|\b(?:delete|remove|erase|clear)\b[^.?!]{0,40}\b(?:notes?|memory|memories)\b",
        re.IGNORECASE,
    ),
}  # fmt: skip
# A question about what was done before ("Did you save that?", "Do you remember…?").
_ABOUT_BEFORE = re.compile(
    r"^\W*(?:did|have|has|had|was|were|what\s+did|when\s+did|do\s+you\s+(?:still\s+)?"
    r"remember|can\s+you\s+remember\s+what)\b",
    re.IGNORECASE,
)
_UNDONE = re.compile(
    r"\b(?:no|not|nothing|never|yet\s+to)\b|n" + _APOS + r"t\b|\bas\s*$", re.IGNORECASE
)
_QUOTED = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d")
# "I" that starts a clause ("Great, I've sent it"), not one inside it ("the link I sent").
_CLAUSE = re.compile(
    r"(?:^|[,:;\u2014\u2013-]|\b(?:and|so|ok|okay|great|done|sure|yes|alright|thanks))\s*$",
    re.IGNORECASE,
)
_CLAUSE_BREAK = re.compile(r"[,;:\u2014\u2013]|\s-\s")


def _claimed(tool: str, text: str) -> bool:
    for found in _CLAIMS[tool].finditer(text):
        start = max(text.rfind(c, 0, found.start()) for c in ".!?\n") + 1
        before = text[start : found.start()]
        first_person = found.group(0)[:1] in "Ii" and found.group(0)[1:2] in " '\u2019"
        if first_person and not _CLAUSE.search(before):
            continue
        # Only this clause can undo it, and not words in quotes: "No problem, I've saved
        # it" and 'Note: "Sam does not eat meat" has been saved' are claims.
        clause = _QUOTED.sub("", before)
        breaks = list(_CLAUSE_BREAK.finditer(clause))
        if _UNDONE.search(clause[breaks[-1].end() :] if breaks else clause):
            continue
        return True
    return False


def _claims_undone(
    messages: list[Any], response: ModelResponse[Any], names: set[str]
) -> str | None:
    """The tool a final reply says did something (a note saved, a message sent) that it
    didn't, else None: the person asked for it in their message, the agent has the tool,
    and no such call succeeded since that message. What qwen2.5:7b says instead of
    calling save_note, often; it's asked once more, naming the tool. Not a claim: an
    answer to a question about what was done before ("Did you save that?"), nor one
    about notes it read back this turn (recall_notes)."""
    if not _is_final(response):
        return None
    done: set[str] = set()
    asked = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and not str(m.content).startswith("[runtime]"):
            asked = " ".join(str(m.content).split())  # "do not  forget" is "do not forget"
            break
        if isinstance(m, ToolMessage) and m.status != "error" and isinstance(m.name, str):
            done.add(m.name)
    if _ABOUT_BEFORE.search(asked):
        return None
    if "recall_notes" in done:
        done.add("save_note")  # what it says it saved, it read back
    text = [m for m in response.result if isinstance(m, AIMessage)][-1].text
    return next((t for t in _CLAIMS if t in names and t not in done
                 and _ASKS[t].search(asked) and _claimed(t, text)), None)  # fmt: skip


def _is_final(response: ModelResponse[Any]) -> bool:
    """The model answered without asking for a tool: the agent would stop here."""
    ai = [m for m in response.result if isinstance(m, AIMessage)]
    return bool(ai) and not ai[-1].tool_calls


WRAP_UP_TURN = (
    "[runtime] This run has used most of its {kind} budget. Tools are no longer "
    "available. Give your best final answer now with what you already have, and say "
    "briefly what is left undone."
)
EMPTY_REPLY = (
    "[runtime] Your last reply came back empty: no text and no tool call. Answer now, or "
    "call one of your tools."
)
# Asked only when the person's message asked for it (see _claims_undone), so it can say
# plainly that it isn't done. Measured on qwen2.5:7b, over 15 "remember…" messages: 8
# claims were asked again; a note that left a way out ("if they asked you to…") got none
# saved, this one 6 (13 of 15 saved in all).
CLAIMED = {
    "save_note": "[runtime] Your reply says it was saved, but save_note wasn't called in "
    "this turn, so it isn't saved yet. Call save_note now with what they asked you to "
    "remember.",
    "notify": "[runtime] Your reply says it was sent, but notify wasn't called in this "
    "turn, so it isn't sent yet. Call notify now with who it's for and the message they "
    "asked you to send.",
    "forget_note": "[runtime] Your reply says it was forgotten, but forget_note wasn't "
    "called in this turn, so it is still in your memory. Call forget_note now with the id "
    "of the note they asked you to forget, from What you remember.",
}
STOPPED_EARLY = "I had to stop early: this run reached its budget before I could finish."
NO_PROGRESS_LIMIT = 5


def _budget_limited(response: ModelResponse[Any], reason: str) -> ModelResponse[Any]:
    """The wrap-up answer (R14.2): never a tool call, whatever the model returned, and
    marked so the run ends `failed(budget:*)` with this answer stored."""
    out: list[Any] = []
    for m in response.result:
        if isinstance(m, AIMessage):
            text = m.content if isinstance(m.content, str) and m.content else STOPPED_EARLY
            m = AIMessage(
                content=text, id=m.id, usage_metadata=m.usage_metadata,
                response_metadata=m.response_metadata,
                additional_kwargs={**m.additional_kwargs, "budget_limited": reason},
            )  # fmt: skip
        out.append(m)
    return ModelResponse(result=out, structured_response=response.structured_response)


def _signature(m: AIMessage) -> str:
    calls = [(tc["name"], tc["args"]) for tc in m.tool_calls]
    return json.dumps([str(m.content), calls], sort_keys=True, default=str)


def _check_progress(state_messages: list[Any], response: ModelResponse[Any]) -> None:
    """R14.4 no-progress: 5 consecutive model outputs that are identical (the same text
    and the same tool calls, e.g. polling a sub-agent forever) end the run."""
    new = next((m for m in response.result if isinstance(m, AIMessage)), None)
    if new is None:
        return
    signature, same = _signature(new), 1
    for m in reversed(state_messages):
        if isinstance(m, ToolMessage):
            continue
        if not isinstance(m, AIMessage) or _signature(m) != signature:
            break
        same += 1
    if same >= NO_PROGRESS_LIMIT:
        raise LoopDetected(f"no progress: {same} identical model outputs in a row")
