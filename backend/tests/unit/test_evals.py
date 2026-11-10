"""Phase H6: test cases, the checks, the judge, on hand-made trajectories."""

from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import ValidationError

from agent_runtime.evals.cases import Case, Expect, Trajectory, load_dir
from agent_runtime.evals.checks import grade, outcome
from agent_runtime.evals.judge import judge
from agent_runtime.models.scripted import ScriptedChatModel

TURN = Trajectory(status="completed", reason=None,
                  calls=[("calculator", {"expression": "6*7"}), ("notify", {"to": "ops"})],
                  asked=["notify"], answer="Done: it is 42, and I told ops.")  # fmt: skip


def failed(expect: Expect, t: Trajectory = TURN) -> dict[str, str]:
    return {c.check: c.detail for c in grade(expect, t) if not c.ok}


def test_a_turn_that_does_what_was_expected_passes() -> None:
    expect = Expect(tools=["calculator", "notify"], not_tools=["run_shell"], approvals=["notify"],
                    max_tool_calls=2, answer_contains=["42", "OPS"], answer_not_contains=["sorry"],
                    answer_matches=r"^Done")  # fmt: skip
    checks = grade(expect, TURN)
    assert all(c.ok for c in checks) and outcome(checks) == "passed"
    assert len(checks) == 10  # status, and one per expectation


def test_each_failure_says_what_happened() -> None:
    assert failed(Expect(tools=["web_search"])) == {
        "called web_search": "it called calculator, notify"}  # fmt: skip
    assert failed(Expect(not_tools=["notify"])) == {"never called notify": "it called notify"}
    no_ask = Trajectory("completed", None, [("notify", {})], [], "ok")
    assert failed(Expect(approvals=["notify"]), no_ask) == {
        "asked before notify": "notify ran without asking"}  # fmt: skip
    assert failed(Expect(max_tool_calls=1)) == {"at most 1 tool calls": "2 tool calls"}
    assert failed(Expect(answer_contains=["43"]))["answer says '43'"].startswith(
        "the answer: “Done"
    )
    assert failed(Expect(status="failed")) == {"status": "it ended completed"}


def test_the_answer_can_follow_a_json_schema() -> None:
    schema = {"type": "object", "required": ["total"], "properties": {"total": {"type": "number"}}}
    good = Trajectory("completed", None, answer='```json\n{"total": 42}\n```')
    assert outcome(grade(Expect(answer_schema=schema), good)) == "passed"
    wrong = Trajectory("completed", None, answer='{"total": "42"}')
    assert failed(Expect(answer_schema=schema), wrong) == {
        "answer follows the schema": "'42' is not of type 'number'"}  # fmt: skip
    prose = Trajectory("completed", None, answer="The total is 42.")
    assert failed(Expect(answer_schema=schema), prose)["answer follows the schema"].startswith(
        "not JSON")  # fmt: skip


def test_a_bad_pattern_or_schema_is_an_error_not_a_failure() -> None:
    assert outcome(grade(Expect(answer_matches="(unclosed"), TURN)) == "error"
    assert outcome(grade(Expect(answer_schema={"type": "nope"}),
                         Trajectory("completed", None, answer="{}"))) == "error"  # fmt: skip


def test_a_case_is_strict_and_its_hash_ignores_key_order() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate({"name": "x", "message": "hi", "expect": {"toolz": ["x"]}})
    a = Case.model_validate({"name": "x", "message": "hi", "expect": {"tools": ["a"], "status":
                             "completed"}})  # fmt: skip
    b = Case.model_validate({"expect": {"status": "completed", "tools": ["a"]}, "message": "hi",
                             "name": "x"})  # fmt: skip
    assert a.digest() == b.digest()
    assert a.digest() != a.model_copy(update={"message": "hello"}).digest()


def test_suites_load_from_yaml_and_a_bad_file_is_named(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("name: a\nmessage: hi\nexpect: {tools: [calculator]}\n")
    assert [k for k, _ in load_dir(tmp_path)] == ["a"]
    (tmp_path / "b.yaml").write_text("name: b\nmessage: hi\nexpectations: {}\n")
    with pytest.raises(ValueError, match=r"b\.yaml"):
        load_dir(tmp_path)


async def test_the_judge_grades_with_a_real_model_and_never_passes_without_one() -> None:
    model = FakeListChatModel(responses=['{"pass": false, "why": "It never shows the working."}'])
    check, usage = await judge(model, "6*7?", "42", "Shows the working")
    assert (check.ok, check.detail, check.error) == (False, "It never shows the working.", False)
    assert usage is not None
    yes = FakeListChatModel(responses=['Sure: {"pass": true, "why": "ok"}'])
    assert (await judge(yes, "q", "a", "r"))[0].ok is True
    garbled = FakeListChatModel(responses=["I think it passes"])
    assert (await judge(garbled, "q", "a", "r"))[0].error is True
    scripted: Any = ScriptedChatModel()
    check, usage = await judge(scripted, "q", "a", "r")
    assert check.error and "needs a real model" in check.detail and usage is None


async def test_only_a_real_true_passes_the_judge() -> None:
    for verdict in ('{"pass": "false"}', '{"pass": 1}', '{"pass": "yes"}'):
        model = FakeListChatModel(responses=[verdict])
        assert (await judge(model, "q", "a", "r"))[0].ok is False
