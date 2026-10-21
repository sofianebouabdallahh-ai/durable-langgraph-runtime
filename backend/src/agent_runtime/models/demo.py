"""The demo responder: what the offline `scripted` model says to free text (phase L2).

The scripted model (R14.20) replays a script, and a person typing in the UI sends
none. Without this, every reply would be "(script finished)". `demo_script` picks a
script from the user's words, so someone without a model can still see the system
work: a tool call, a saved note, a search, two helpers in parallel, an approval.

Pattern: Strategy, as an ordered rule table; the first rule that matches and that
the agent's tools allow wins. It's a pure function of (text, agent), and the script
it returns is stored in the run's input, so a replay after a crash, or a resume
after an approval, reads the same script back instead of choosing again.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.graphs.assistant import granted_tools
from agent_runtime.tools.builtin import safe_eval

Script = list[dict[str, Any]]
SubScripts = dict[str, Script]

DEMO_NOTE = "_(Demo model: connect a real one with `./setup.sh --model …` for real answers.)_"
HELP = f"""Hi! I'm running on the **demo model**, which works offline and follows a few \
simple rules, so you can see how the system works before connecting a real model.

Try one of these:
- **What is 12 * (3 + 4)?** uses the calculator
- **Remember that the demo is on Friday** saves a note
- **Search the web for Redis Streams** runs a web search
- **Research Redis Streams and compute 12 * 4** starts two helpers in parallel
- **Notify the team that the build is green** asks for your approval first

{DEMO_NOTE}"""

_CANDIDATE = re.compile(r"[\d(][\d\s.+\-*/x\u00d7^()]*[\d)]")
_OPERATOR = re.compile(r"[\d)]\s*[-+*/x\u00d7^]\s*[\d(]")
_HANDLE = "${spawn_subagent[%d].handle}"


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    needs: tuple[str, ...]  # tools (and sub-agents) the agent must have
    match: Callable[[str], bool]
    script: Callable[[str], tuple[Script, SubScripts]]


def _words(*words: str) -> Callable[[str], bool]:
    pattern = re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)
    return lambda text: bool(pattern.search(text))


def _expression(text: str) -> str | None:
    """The first arithmetic expression in the text that the calculator accepts."""
    for found in _CANDIDATE.finditer(text):
        candidate = found.group(0).strip()
        if not _OPERATOR.search(candidate):
            continue
        expression = candidate.replace("\u00d7", "*").replace("x", "*").replace("^", "**")
        try:
            safe_eval(expression)
        except Exception:
            continue
        return expression
    return None


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _research(text: str) -> tuple[Script, SubScripts]:
    expression = _expression(text) or "12 * 4"
    script: Script = [
        {"tool_calls": [
            {"name": "spawn_subagent", "args": {"agent": "researcher", "task": text[:500]}},
            {"name": "spawn_subagent", "args": {"agent": "data-analyst", "task": expression}},
        ]},
        {"tool_calls": [{"name": "wait_subagents",
                         "args": {"handles": [_HANDLE % 0, _HANDLE % 1], "timeout_s": 120}}]},
        {"content": "Both helpers are done: the **researcher** searched the web "
                    f"and the **data analyst** computed {expression} = "
                    f"**{_number(safe_eval(expression))}**. Their reports are in the cards "
                    f"above."},
    ]  # fmt: skip
    subs: SubScripts = {
        "researcher": [
            {"tool_calls": [{"name": "report_progress",
                             "args": {"message": "Searching the sources", "percent": 20}}]},
            {"tool_calls": [{"name": "web_search", "args": {"query": text[:400], "k": 3}}]},
            {"tool_calls": [{"name": "report_progress",
                             "args": {"message": "Reading what I found", "percent": 70}}]},
            {"tool_calls": [{"name": "return_result",
                             "args": {"summary": "I searched the web for the question; the "
                                                 "results are in my card."}}]},
        ],
        "data-analyst": [
            {"tool_calls": [{"name": "run_python",
                             "args": {"code": f"print({_python(expression)})"}}]},
            {"tool_calls": [{"name": "return_result",
                             "args": {"summary": f"{expression} = "
                                                 f"{_number(safe_eval(expression))}"}}]},
        ],
    }  # fmt: skip
    return script, subs


def _delegate(text: str, helper: str, label: str) -> tuple[Script, SubScripts]:
    """Any agent's helpers (Studio agents): hand the task to the first one."""
    script: Script = [
        {"tool_calls": [{"name": "spawn_subagent", "args": {"agent": helper, "task": text[:500]}}]},
        {"tool_calls": [{"name": "wait_subagents",
                         "args": {"handles": [_HANDLE % 0], "timeout_s": 120}}]},
        {"content": f"My helper **{label}** worked on it; its report is in the card above."},
    ]  # fmt: skip
    subs: SubScripts = {
        helper: [
            {"tool_calls": [{"name": "report_progress",
                             "args": {"message": "Working on it", "percent": 50}}]},
            {"tool_calls": [{"name": "return_result",
                             "args": {"summary": f"{label} looked into: {text[:200]}"}}]},
        ]
    }  # fmt: skip
    return script, subs


DELEGATE = re.compile(r"\b(research|investigate|find|plan|ask|look into|delegate)\b", re.IGNORECASE)


def _notify(text: str) -> tuple[Script, SubScripts]:
    return [
        {"content": "This sends a message to people, so it waits for your approval.",
         "tool_calls": [{"name": "notify", "args": {"to": "the team", "message": text[:2000]}}]},
        {"content": "Done. If you approved, the notification is queued; if you rejected it, "
                    "nothing was sent."},
    ], {}  # fmt: skip


def _calculate(text: str) -> tuple[Script, SubScripts]:
    expression = _expression(text) or "0"
    return [
        {"tool_calls": [{"name": "calculator", "args": {"expression": expression}}]},
        {"content": f"{expression} = **{_number(safe_eval(expression))}**"},
    ], {}  # fmt: skip


def _python(expression: str) -> str:
    """The expression as Python (the demo's arithmetic: x and \u00d7 multiply, ^ is a power)."""
    return expression.replace("\u00d7", "*").replace("x", "*").replace("^", "**")


def _code(text: str) -> tuple[Script, SubScripts]:
    expression = _expression(text) or "0"
    return [
        {"tool_calls": [{"name": "run_python", "args": {"code": f"print({_python(expression)})"}}]},
        {"content": f"{expression} = **{_number(safe_eval(expression))}** (run in the sandbox)"},
    ], {}  # fmt: skip


def _note(text: str) -> tuple[Script, SubScripts]:
    return [
        {"tool_calls": [{"name": "save_note", "args": {"text": text[:2000]}}]},
        {"content": "Saved it as a note."},
    ], {}  # fmt: skip


def _search(text: str) -> tuple[Script, SubScripts]:
    return [
        {"tool_calls": [{"name": "web_search", "args": {"query": text[:400], "k": 3}}]},
        {"content": "Here's what a web search found; the results are in the card above. (The "
                    "demo model can't read them: connect a real model to get answers.)"},
    ], {}  # fmt: skip


RULES: tuple[Rule, ...] = (
    Rule("research", ("spawn_subagent", "wait_subagents", "researcher", "data-analyst"),
         _words("research", "investigate"), _research),
    Rule("notify", ("notify",), _words("notify", "tell", "message", "email"), _notify),
    Rule("code", ("run_python",), lambda t: _expression(t) is not None, _code),
    Rule("calculate", ("calculator",), lambda t: _expression(t) is not None, _calculate),
    Rule("note", ("save_note",), _words("remember", "note", "save", "keep"), _note),
    Rule("search", ("web_search",),
         _words("search", "find", "look up", "what", "who", "how", "why"), _search),
)  # fmt: skip


def demo_script(text: str, agent: AgentDefinition | None) -> tuple[Script, SubScripts]:
    """The script for one turn: the first rule that matches and that `agent` can run,
    else a short help text. An agent with skills first loads its first one, so the demo
    shows skills at work too."""
    script, subs = _rule_script(text, agent)
    if agent is not None and agent.frontmatter.skills:
        load = {
            "tool_calls": [{"name": "load_skill", "args": {"name": agent.frontmatter.skills[0]}}]
        }
        script = [load, *script]
    return script, subs


def _rule_script(text: str, agent: AgentDefinition | None) -> tuple[Script, SubScripts]:
    available: set[str] = set()
    if agent is not None:
        available = {*granted_tools(agent), *(s.frontmatter.name for s in agent.subagents)}
    for rule in RULES:
        if all(n in available for n in rule.needs) and rule.match(text):
            return rule.script(text)
        if (
            rule.name == "research"
            and agent is not None
            and agent.subagents
            and DELEGATE.search(text)
        ):
            first = agent.subagents[0].frontmatter  # an agent with its own helpers
            return _delegate(text, first.name, first.display_name or first.name)
    return [{"content": HELP}], {}
