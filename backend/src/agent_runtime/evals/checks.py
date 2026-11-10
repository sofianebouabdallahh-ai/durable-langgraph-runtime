"""Grade a turn against a case (phase H6): one result per expectation, each with why.

Deterministic checks only; the judge (a model) is graded separately (`judge.py`), so
these are pure and unit-tested on hand-made trajectories.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

import jsonschema

from agent_runtime.evals.cases import Expect, Trajectory

Outcome = Literal["passed", "failed", "error"]


@dataclass(frozen=True, slots=True)
class Check:
    check: str
    ok: bool
    detail: str = ""
    error: bool = False  # couldn't be graded (e.g. the judge needs a real model)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def grade(expect: Expect, t: Trajectory) -> list[Check]:
    """Every deterministic check `expect` asks for, in a stable order."""
    out = [Check("status", t.status == expect.status,
                 f"it ended {t.status}" + (f" ({t.reason})" if t.reason else ""))]  # fmt: skip
    for tool in expect.tools:
        out.append(Check(f"called {tool}", tool in t.tools,
                         "" if tool in t.tools else f"it called {_names(t)}"))  # fmt: skip
    for tool in expect.not_tools:
        out.append(Check(f"never called {tool}", tool not in t.tools,
                         f"it called {tool}" if tool in t.tools else ""))  # fmt: skip
    for tool in expect.approvals:
        out.append(Check(f"asked before {tool}", tool in t.asked,
                         "" if tool in t.asked else (
                             f"{tool} ran without asking" if tool in t.tools
                             else f"it never got to {tool}")))  # fmt: skip
    if expect.max_tool_calls is not None:
        n = len(t.calls)
        out.append(Check(f"at most {expect.max_tool_calls} tool calls",
                         n <= expect.max_tool_calls, f"{n} tool calls"))  # fmt: skip
    answer = t.answer.casefold()
    for words in expect.answer_contains:
        out.append(Check(f"answer says {words!r}", words.casefold() in answer,
                         "" if words.casefold() in answer else _quote(t.answer)))  # fmt: skip
    for words in expect.answer_not_contains:
        out.append(Check(f"answer doesn't say {words!r}", words.casefold() not in answer,
                         _quote(t.answer) if words.casefold() in answer else ""))  # fmt: skip
    if expect.answer_matches is not None:
        try:
            ok = re.search(expect.answer_matches, t.answer) is not None
            out.append(Check(f"answer matches /{expect.answer_matches}/", ok,
                             "" if ok else _quote(t.answer)))  # fmt: skip
        except re.error as exc:
            out.append(Check(f"answer matches /{expect.answer_matches}/", False,
                             f"not a valid pattern: {exc}", error=True))  # fmt: skip
    if expect.answer_schema is not None:
        out.append(_schema(expect.answer_schema, t.answer))
    return out


def outcome(checks: list[Check]) -> Outcome:
    if any(c.error for c in checks):
        return "error"
    return "passed" if all(c.ok for c in checks) else "failed"


def _schema(schema: dict[str, Any], answer: str) -> Check:
    name = "answer follows the schema"
    text = answer.strip()
    if text.startswith("```"):  # a fenced block: its content
        text = text.strip("`").removeprefix("json").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return Check(name, False, f"not JSON: {_quote(answer)}")
    try:
        jsonschema.validate(value, schema)
    except jsonschema.SchemaError as exc:
        return Check(name, False, f"the schema is invalid: {exc.message}", error=True)
    except jsonschema.ValidationError as exc:
        return Check(name, False, exc.message)
    return Check(name, True)


def _names(t: Trajectory) -> str:
    return ", ".join(name for name, _ in t.calls) or "no tool"


def _quote(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return (
        f"the answer: “{text[:limit]}{'…' if len(text) > limit else ''}”" if text else "no answer"
    )
