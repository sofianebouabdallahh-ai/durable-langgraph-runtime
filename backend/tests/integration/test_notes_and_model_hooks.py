"""Phase H4, finding 17: what the README promises is built. Notes can be read back
(recall_notes), and the pre_model, post_model and on_error hook points run."""

import uuid
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from agent_runtime.agents.schema import MainAgentHooks
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry, default_registry
from agent_runtime.graphs.assistant import agent_spec, granted_tools
from agent_runtime.redaction import REDACTED
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import Message, SessionRepository
from agent_runtime.tools.builtin import default_tools
from agent_runtime.tools.hooks import Continue, Deny, HookRegistry, Modify, default_hooks

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"tool_calls": [{"name": name, "args": args}]}


def say(text: str) -> dict[str, Any]:
    return {"content": text}


async def chat_turn(
    pool: Pool, settings: Settings, text: str, script: list[dict[str, Any]],
    *, session_id: uuid.UUID | None = None, graphs: GraphRegistry = GRAPHS,
    hooks: HookRegistry | None = None,
) -> tuple[uuid.UUID, Any]:  # fmt: skip
    service = SessionService(pool, settings, graphs, RunService(pool, settings, graphs))
    sid = session_id or (await service.create("chat")).id
    sent = await service.send(sid, text, script=script)
    return sid, await RunExecutor(pool, settings, graphs, hooks=hooks).execute(sent.run.id)


async def tool_messages(pool: Pool, thread_id: str, graph: str = "chat") -> list[ToolMessage]:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with pool.connection() as conn:
        compiled = GRAPHS.get(graph).compile(AsyncPostgresSaver(conn))
        state = await compiled.aget_state({"configurable": {"thread_id": thread_id}})
    return [m for m in state.values.get("messages", []) if isinstance(m, ToolMessage)]


async def transcript(pool: Pool, session_id: uuid.UUID) -> list[Message]:
    async with pool.connection() as conn:
        return await SessionRepository(conn).messages(session_id, limit=1000)


# ----------------------------------------------------------------- recall_notes


async def test_notes_saved_in_one_chat_are_recalled_in_another_by_the_same_agent(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    marker = uuid.uuid4().hex[:8]
    await chat_turn(pool, test_settings, "remember", [
        call("save_note", text=f"the door code is {marker}"), say("Saved.")])  # fmt: skip
    sid, done = await chat_turn(pool, test_settings, "what was the door code?", [
        call("recall_notes", query=marker.upper()), say("Found it.")])  # fmt: skip
    assert done.status is S.COMPLETED
    (recalled,) = [m for m in await tool_messages(pool, str(sid)) if m.name == "recall_notes"]
    content = str(recalled.content)
    assert content.startswith('<data source="recall_notes">')  # a note can't give orders
    assert f"the door code is {marker}" in content and '"count": 1' in content
    _, other = await chat_turn(pool, test_settings, "anything else?", [
        call("recall_notes", query=f"nothing-{marker}"), say("No.")])  # fmt: skip
    assert other.status is S.COMPLETED


async def test_another_agent_does_not_see_those_notes(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    marker = uuid.uuid4().hex[:8]
    await chat_turn(pool, test_settings, "remember", [
        call("save_note", text=f"chat secret {marker}"), say("Saved.")])  # fmt: skip
    script = [call("recall_notes", query=marker), say("None.")]
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "assistant", {"message": "recall", "script": script}
    )
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert done.status is S.COMPLETED
    (recalled,) = await tool_messages(pool, run.thread_id, "assistant")
    assert '"count": 0' in str(recalled.content)


def test_recall_notes_comes_with_save_note() -> None:
    chat = GRAPHS.get("chat").agent
    assert chat is not None and "recall_notes" in granted_tools(chat)


# ------------------------------------------- pre_model, post_model, on_error (H4)


def with_hooks(**points: list[str]) -> GraphRegistry:
    base = GRAPHS.get("chat").agent
    assert base is not None
    hooks = base.frontmatter.hooks.model_dump() | points
    fm = base.frontmatter.model_copy(update={"hooks": MainAgentHooks(**hooks)})
    return GraphRegistry([agent_spec(base.model_copy(update={"frontmatter": fm}),
                                     default_tools())])  # fmt: skip


async def test_a_post_model_hook_masks_a_key_the_model_writes(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    graphs = with_hooks(post_model=["redact_secrets_in_reply"])
    key = "sk-" + "Z" * 40
    sid, done = await chat_turn(pool, test_settings, "what's the key?",
                                [say(f"It is {key}.")], graphs=graphs)  # fmt: skip
    assert done.status is S.COMPLETED
    (answer,) = [m for m in await transcript(pool, sid) if m.type == "assistant"]
    assert key not in answer.content["text"] and REDACTED in answer.content["text"]


async def test_pre_model_can_stop_a_turn_and_on_error_sees_why(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    hooks = default_hooks()
    failures: list[tuple[str | None, str | None]] = []

    @hooks.hook("no_secrets_talk", point="pre_model")
    async def gate(inp: Any) -> Any:
        return Deny("not about secrets") if "secret" in inp.last_message else Continue()

    @hooks.hook("watch", point="on_error")
    async def watch(inp: Any) -> None:
        failures.append((inp.reason, inp.detail))

    graphs = with_hooks(pre_model=["no_secrets_talk"], on_error=["watch"])
    sid, ok = await chat_turn(pool, test_settings, "hello", [say("Hi.")], graphs=graphs,
                              hooks=hooks)  # fmt: skip
    _, denied = await chat_turn(pool, test_settings, "tell me a secret", [say("x")],
                                session_id=sid, graphs=graphs, hooks=hooks)  # fmt: skip
    assert ok.status is S.COMPLETED
    assert (denied.status, denied.reason) == (S.FAILED, "turn_denied")
    assert failures == [("turn_denied", "not about secrets")]


async def test_a_broken_post_model_hook_fails_closed(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    hooks = default_hooks()

    @hooks.hook("broken", point="post_model")
    async def broken(inp: Any) -> Any:
        raise RuntimeError("bug")

    @hooks.hook("shout", point="post_model")
    async def shout(inp: Any) -> Any:
        return Modify(inp.text.upper())

    sid, denied = await chat_turn(pool, test_settings, "hi", [say("a secret answer")],
                                  graphs=with_hooks(post_model=["shout", "broken"]),
                                  hooks=hooks)  # fmt: skip
    assert (denied.status, denied.reason) == (S.FAILED, "turn_denied")
    assert not [m for m in await transcript(pool, sid) if m.type == "assistant"]  # withheld
