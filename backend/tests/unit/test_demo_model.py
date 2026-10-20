"""The demo responder (phase L2): the offline model's reply to free text."""

import pytest

from agent_runtime.graphs import default_registry
from agent_runtime.models.demo import HELP, demo_script
from agent_runtime.models.scripted import ScriptTurn
from agent_runtime.streaming.bus import turn_status

GRAPHS = default_registry()
CHAT = GRAPHS.get("chat").agent


def first_tool(text: str, agent: object = CHAT) -> str | None:
    script, _ = demo_script(text, agent)  # type: ignore[arg-type]
    calls = script[0].get("tool_calls") or []
    return calls[0]["name"] if calls else None


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("What is 12 * (3 + 4)?", "run_python"),  # Nuria computes in the sandbox (L6b)
        ("what is 3 x 4", "run_python"),
        ("Remember that the demo is on Friday", "save_note"),
        ("Search for Redis Streams", "web_search"),
        ("Research Redis Streams and compute 12 * 4", "spawn_subagent"),
        ("Notify the team that the build is green", "notify"),
        ("hello", None),
    ],
)
def test_the_first_matching_rule_picks_the_tool(text: str, tool: str | None) -> None:
    assert first_tool(text) == tool


def test_every_script_is_valid_and_the_same_text_gives_the_same_script() -> None:
    for text in ("What is 6*7?", "Research Redis and compute 2+2", "notify ops", "hi"):
        script, subs = demo_script(text, CHAT)
        assert demo_script(text, CHAT) == (script, subs)  # deterministic: replay-safe
        for turn in [*script, *(t for s in subs.values() for t in s)]:
            ScriptTurn.model_validate(turn)


def test_a_rule_needs_the_agents_tools() -> None:
    assistant = GRAPHS.get("assistant").agent  # no sub-agents, no notify
    assert first_tool("Research Redis Streams", assistant) != "spawn_subagent"
    assert first_tool("What is 2 + 2?", assistant) == "calculator"  # no Run Python: the calculator
    assert demo_script("Notify the team", None) == ([{"content": HELP}], {})


def test_research_gives_both_helpers_a_script() -> None:
    script, subs = demo_script("Research queues and compute 12 * 4", CHAT)
    assert set(subs) == {"researcher", "data-analyst"}
    assert subs["data-analyst"][0]["tool_calls"][0]["args"] == {"code": "print(12 * 4)"}
    assert "**48**" in script[-1]["content"]


def test_turn_status_is_only_for_a_turns_lifecycle_events() -> None:
    import uuid
    from datetime import UTC, datetime

    from agent_runtime.runs.store import Event

    sid = uuid.uuid4()

    def event(type_: str, session_id: uuid.UUID | None = sid) -> Event:
        return Event(uuid.uuid4(), 1, datetime.now(UTC), 1, type_, {"reason": "r"}, session_id)

    channel, out = turn_status(event("run.failed")) or ("", None)
    assert channel == f"session:{sid}" and out is not None
    assert (out.type, out.persisted, out.payload["status"], out.payload["reason"]) == (
        "turn.status",
        False,
        "failed",
        "r",
    )
    assert turn_status(event("tool.called")) is None  # not a lifecycle event
    assert turn_status(event("run.completed", None)) is None  # not a chat turn


def test_any_agents_helper_gets_the_task() -> None:
    from agent_runtime.agents.document import AgentDocument, to_raw
    from agent_runtime.agents.loader import Ceilings, validate_definition
    from agent_runtime.catalog import default_catalog

    doc = AgentDocument.model_validate(
        {
            "name": "trip-planner",
            "description": "Plans trips.",
            "instructions": "Plan trips.",
            "helpers": [
                {
                    "name": "place-finder",
                    "display_name": "Place finder",
                    "description": "Finds places.",
                    "instructions": "Find places.",
                }
            ],
        }
    )
    main, helpers = to_raw(doc, 1)
    ceilings = Ceilings(model_calls=100, tool_calls=100, tokens=10**6, cost_usd=10, timeout_s=600)
    agent, issues = validate_definition(main, helpers, default_catalog(), ceilings)
    assert issues == [] and agent is not None
    script, subs = demo_script("Plan a weekend in Lisbon", agent)
    assert script[0]["tool_calls"][0]["args"]["agent"] == "place-finder"
    assert set(subs) == {"place-finder"}
    for turn in [*script, *subs["place-finder"]]:
        ScriptTurn.model_validate(turn)


def test_an_agent_with_helpers_is_told_their_ids_and_purpose() -> None:
    from agent_runtime.graphs.assistant import render_prompt

    assert CHAT is not None
    prompt = render_prompt(CHAT)
    assert "## Your helpers" in prompt
    assert "- `researcher`: Finds and cites facts" in prompt
    assert "## Your helpers" not in render_prompt(GRAPHS.get("assistant").agent)  # type: ignore[arg-type]


def test_every_agent_and_helper_is_told_that_data_is_not_instructions() -> None:
    """R14.15: the rule closes every system prompt, main agents' and helpers'."""
    from agent_runtime.graphs.assistant import render_prompt
    from agent_runtime.untrusted import RULE

    assert CHAT is not None
    assert render_prompt(CHAT).endswith(RULE)
    assert all(render_prompt(helper).endswith(RULE) for helper in CHAT.subagents)


def test_an_agent_with_skills_loads_its_first_skill_in_the_demo() -> None:
    assert CHAT is not None
    skilled = CHAT.model_copy(
        update={
            "frontmatter": CHAT.frontmatter.model_copy(
                update={"skills": ["trip-planning", "plain-writing"]}
            )
        }
    )
    script, _ = demo_script("What is 2 + 2?", skilled)
    assert script[0] == {"tool_calls": [{"name": "load_skill", "args": {"name": "trip-planning"}}]}
    assert script[1]["tool_calls"][0]["name"] == "run_python"  # then the usual rule
    plain, _ = demo_script("What is 2 + 2?", CHAT)
    assert plain[0]["tool_calls"][0]["name"] == "run_python"
