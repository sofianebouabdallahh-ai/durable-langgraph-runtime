import uuid

import pytest
from pydantic import ValidationError

from agent_runtime.tools.builtin import (
    CalculatorArgs,
    SaveNoteArgs,
    calculator,
    default_tools,
    safe_eval,
)
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry, UnknownTool


def test_default_registry_declares_risk_and_side_effects() -> None:
    reg = default_tools()
    assert reg.catalog() == {
        "calculator": "read",
        "search": "read",
        "notify": "external_side_effect",
        "save_note": "write_internal",
        "recall_notes": "read",  # what save_note kept (H4), granted with it
        # sub-agent tools (CR-005), granted by the harness
        "spawn_subagent": "write_internal",
        "subagent_status": "read",
        "wait_subagents": "read",
        "cancel_subagent": "write_internal",
        "report_progress": "write_internal",
        "return_result": "write_internal",
        # skill tools (CR-006 R17.4), granted by the harness to agents with skills
        "load_skill": "read",
        "read_skill_file": "read",
        # the Studio's builder agents answer through these (CR-006 R17.3)
        "propose_draft": "read",
        "propose_instructions": "read",
        # the web (L6a)
        "web_search": "read",
        "read_webpage": "read",
        # code, the terminal and files, in the run's sandbox (L6b)
        "run_python": "execute",
        "run_shell": "execute",
        "workspace_files": "execute",
    }
    assert reg.get("wait_subagents").timeout_s == 125  # blocks up to 120 s
    assert reg.get("save_note").side_effect and not reg.get("calculator").side_effect
    assert reg.get("notify").max_calls == 5
    with pytest.raises(UnknownTool):
        reg.get("teleport")


def test_args_are_strict() -> None:
    CalculatorArgs.model_validate({"expression": "1+1"})
    with pytest.raises(ValidationError, match="Extra inputs"):
        CalculatorArgs.model_validate({"expression": "1+1", "evil": True})
    with pytest.raises(ValidationError):  # strict: no "3" → 3.0 coercion
        SaveNoteArgs.model_validate({"text": "x", "linger_s": "3"})


def test_execute_tools_must_be_sandboxed_and_names_unique() -> None:
    reg = ToolRegistry()

    class A(ToolArgs):
        x: int

    async def fn(args: A, ctx: ToolContext) -> int:
        return args.x

    with pytest.raises(ValueError, match="requires the sandbox"):
        reg.tool("run_code", args=A, risk_class="execute", side_effect=False)(fn)
    reg.tool("t", args=A, risk_class="read", side_effect=False)(fn)
    with pytest.raises(ValueError, match="registered twice"):
        reg.tool("t", args=A, risk_class="read", side_effect=False)(fn)


@pytest.mark.parametrize(
    ("expr", "value"), [("(2 + 3) * 4", 20.0), ("-2 ** 2", -4.0), ("7 % 4", 3.0), ("1/4", 0.25)]
)
def test_calculator_evaluates_arithmetic(expr: str, value: float) -> None:
    assert safe_eval(expr) == value


@pytest.mark.parametrize(
    "expr", ["__import__('os').system('id')", "open('/etc/passwd')", "2 ** 1000", "x + 1", "[1, 2]"]
)
def test_calculator_refuses_anything_but_arithmetic(expr: str) -> None:
    with pytest.raises((ValueError, SyntaxError)):
        safe_eval(expr)


async def test_calculator_tool() -> None:
    ctx = ToolContext(run_id=uuid.uuid4(), epoch=1, key="k" * 64, pool=None)  # type: ignore[arg-type]
    assert await calculator(CalculatorArgs(expression="6*7"), ctx) == {"value": 42.0}


def test_return_result_accepts_any_json_value() -> None:
    """Live finding: a 7B model returned `result: 48`; a dict-only schema rejected it
    until the sub-agent timed out."""
    from agent_runtime.subagents.tools import ReturnArgs

    for value in (48, 4.5, "48 slots", [1, 2], {"total": 48}, None):
        assert ReturnArgs.model_validate({"summary": "s", "result": value}).result == value


def test_a_helper_keeps_its_own_notes() -> None:
    """recall_notes (H4) reads back only the notes of whoever saved them: the agent
    itself (None) or one of its helpers, by name."""
    from types import SimpleNamespace

    from agent_runtime.tools.builtin import _author

    base: dict[str, object] = {"run_id": uuid.uuid4(), "epoch": 1, "key": "k" * 64, "pool": None}
    assert _author(ToolContext(**base)) is None  # type: ignore[arg-type]
    helper = SimpleNamespace(defn=SimpleNamespace(frontmatter=SimpleNamespace(name="scribe")))
    assert _author(ToolContext(**base, subagent=helper)) == "scribe"  # type: ignore[arg-type]


def test_the_model_never_sees_the_crash_tests_knob() -> None:
    # A model read `linger_s` as how long to keep the note, sent a day, and the note
    # wasn't saved: the knob stays out of the schema, and still works for the tests.
    schema = default_tools().get("save_note").json_schema()
    assert set(schema["properties"]) == {"text"}
    assert SaveNoteArgs.model_validate({"text": "hi", "linger_s": 2}).linger_s == 2
