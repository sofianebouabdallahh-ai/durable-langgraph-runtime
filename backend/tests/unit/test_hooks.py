import asyncio

import pytest

from agent_runtime.redaction import REDACTED, redact
from agent_runtime.tools.hooks import (
    Ask,
    Continue,
    Deny,
    HookDecision,
    HookRegistry,
    Modify,
    ToolHookInput,
    UnknownHook,
    default_hooks,
    run_hooks,
)


def reg_with(*hooks: tuple[str, str, object]) -> HookRegistry:
    reg = HookRegistry()
    for name, point, fn in hooks:
        reg.hook(name, point=point, timeout_s=0.2)(fn)  # type: ignore[arg-type]
    return reg


async def test_modify_then_continue_applies_modified_args() -> None:
    async def upper(inp: ToolHookInput) -> HookDecision:
        return Modify({**inp.args, "text": inp.args["text"].upper()})

    async def ok(inp: ToolHookInput) -> HookDecision:
        return Continue()

    reg = reg_with(("upper", "pre_tool", upper), ("ok", "pre_tool", ok))
    out = await run_hooks([reg.get("upper"), reg.get("ok")], ToolHookInput("t", {"text": "hi"}))
    assert isinstance(out.decision, Continue)
    assert out.input.args == {"text": "HI"}
    assert out.audit == [{"hook": "upper", "point": "pre_tool", "decision": "modify"}]


async def test_first_deny_wins_and_later_hooks_do_not_run() -> None:
    ran = []

    async def no(inp: ToolHookInput) -> HookDecision:
        return Deny("blocked")

    async def never(inp: ToolHookInput) -> HookDecision:
        ran.append(1)
        return Continue()

    reg = reg_with(("no", "pre_tool", no), ("never", "pre_tool", never))
    out = await run_hooks([reg.get("no"), reg.get("never")], ToolHookInput("t", {}))
    assert out.decision == Deny("blocked") and ran == []


async def test_ask_stops_the_chain() -> None:
    async def ask(inp: ToolHookInput) -> HookDecision:
        return Ask({"why": "risky"})

    reg = reg_with(("ask", "pre_tool", ask))
    out = await run_hooks([reg.get("ask")], ToolHookInput("t", {}))
    assert out.decision == Ask({"why": "risky"})


@pytest.mark.parametrize("failure", ["raise", "timeout"])
async def test_a_broken_hook_fails_closed(failure: str) -> None:
    async def broken(inp: ToolHookInput) -> HookDecision:
        if failure == "raise":
            raise RuntimeError("bug")
        await asyncio.sleep(5)
        return Continue()

    reg = reg_with(("broken", "post_tool", broken))
    out = await run_hooks([reg.get("broken")], ToolHookInput("t", {}, result="secret"))
    assert isinstance(out.decision, Deny)
    assert out.decision.reason.startswith("hook_error:broken:")


async def test_ask_after_execution_is_refused() -> None:
    async def ask(inp: ToolHookInput) -> HookDecision:
        return Ask({})

    reg = reg_with(("late", "post_tool", ask))
    out = await run_hooks([reg.get("late")], ToolHookInput("t", {}, result=1))
    assert isinstance(out.decision, Deny) and "ask_not_allowed" in out.decision.reason


def test_registry_rules() -> None:
    reg = default_hooks()
    assert reg.catalog() == {
        "redact_secrets_in_args": "pre_tool",
        "redact_secrets_in_result": "post_tool",
        "session_clock": "session_start",
        "summarize_session": "session_end",
    }
    with pytest.raises(UnknownHook):
        reg.get("nope")
    with pytest.raises(ValueError, match="twice"):
        reg.hook("redact_secrets_in_args", point="pre_tool")(lambda i: Continue())  # type: ignore[arg-type,return-value]


# Assembled at runtime so no secret-shaped literal sits in the source: the
# pre-commit secret scanners (rightly) refuse such files, and an allowlist
# would weaken them for real secrets too.
_PEM = "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIE\n-----END RSA " + "PRIVATE KEY-----"
FAKE_SECRETS = [
    "sk-" + "abcdefghijklmnopqrstuvwxyz0123",
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "ghp_" + "a" * 36,
    "Bearer " + "abcdefghijklmnop1234",
    _PEM,
]


@pytest.mark.parametrize("secret", FAKE_SECRETS)
def test_redact_finds_secrets_anywhere(secret: str) -> None:
    value = {"a": [f"use {secret} please"], "b": 3}
    out = redact(value)
    assert secret not in str(out) and REDACTED in str(out) and out["b"] == 3


def test_redact_passwords_in_urls_but_keeps_the_rest() -> None:
    assert redact("postgresql://agent:hunter2@db:5432/x") == f"postgresql://{REDACTED}@db:5432/x"


async def test_builtin_redaction_hooks() -> None:
    reg = default_hooks()
    out = await run_hooks(
        [reg.get("redact_secrets_in_result")],
        ToolHookInput("t", {}, result={"token": FAKE_SECRETS[0]}),
    )
    assert isinstance(out.decision, Continue) and out.input.result == {"token": REDACTED}
    clean = await run_hooks([reg.get("redact_secrets_in_args")], ToolHookInput("t", {"x": "fine"}))
    assert clean.audit == []  # nothing to redact: not even audited


async def test_context_hooks_accumulate_and_fail_closed() -> None:
    from agent_runtime.tools.hooks import Context, run_context_hooks, run_observers

    reg = HookRegistry()

    @reg.hook("a", point="turn_start")
    async def a(inp: object) -> Context:
        return Context(["one"])

    @reg.hook("b", point="turn_start")
    async def b(inp: object) -> Context:
        return Context(["two"])

    @reg.hook("boom", point="turn_start")
    async def boom(inp: object) -> Context:
        raise RuntimeError("x")

    @reg.hook("watch", point="turn_end")
    async def watch(inp: object) -> str:
        raise RuntimeError("observers never fail the turn")

    ok = await run_context_hooks([reg.get("a"), reg.get("b")], None)
    assert isinstance(ok, Context) and ok.texts == ["one", "two"]
    bad = await run_context_hooks([reg.get("a"), reg.get("boom")], None)
    assert isinstance(bad, Deny) and bad.reason == "hook_error:boom:RuntimeError"
    assert await run_observers([reg.get("watch")], None) == []
