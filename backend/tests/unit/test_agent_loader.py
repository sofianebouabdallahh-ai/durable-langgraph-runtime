from pathlib import Path

import pytest

from agent_runtime.agents.loader import (
    AgentValidationError,
    Catalog,
    Ceilings,
    UnknownAgent,
    canonical_content,
    content_hash,
    load_agents,
)

SHIPPED_AGENTS = Path(__file__).resolve().parents[2] / "agents"
CEILINGS = Ceilings(model_calls=100, tool_calls=100, tokens=1_000_000, cost_usd=2.0, timeout_s=1200)
CATALOG = Catalog(
    tools={"search": "read", "save_note": "write_internal", "send_email": "external_side_effect"},
    hooks={"redact": "post_tool", "load_ctx": "session_start"},
    output_schemas=frozenset({"Plan"}),
)

MAIN = """---
name: {name}
description: test agent
version: 1
model: chat
max_turns: 5
{extra}
---
{body}
"""


def write(root: Path, rel: str, name: str, extra: str = "", body: str = "You help.") -> None:
    path = root / rel / "agent.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MAIN.format(name=name, extra=extra, body=body))


def issues_for(root: Path, catalog: Catalog = CATALOG) -> list[str]:
    with pytest.raises(AgentValidationError) as exc:
        load_agents(root, catalog, CEILINGS)
    return [str(i) for i in exc.value.issues]


def test_shipped_agents_are_valid() -> None:
    registry = load_agents(SHIPPED_AGENTS, Catalog(), CEILINGS)
    example = registry.get("example")
    assert [s.id for s in example.subagents] == ["example/summarizer"]


def test_main_with_subagent_loads_with_defaults(tmp_path: Path) -> None:
    write(tmp_path, "chat", "chat", extra="tools: [search, {save_note: {max_calls: 3}}]")
    write(tmp_path, "chat/researcher", "researcher", extra="tools: [search]")
    registry = load_agents(tmp_path, CATALOG, CEILINGS)

    chat = registry.get("chat")
    assert chat.frontmatter.temperature == 0.2
    assert [(t.name, t.max_calls) for t in chat.frontmatter.tools] == [
        ("search", None),
        ("save_note", 3),
    ]
    assert chat.subagents[0].id == "chat/researcher"
    assert registry.names() == ["chat"]
    with pytest.raises(UnknownAgent):
        registry.get("nope")


def test_typo_in_a_key_is_an_error_not_ignored(tmp_path: Path) -> None:
    write(tmp_path, "a", "a", extra="max_turn: 5")
    assert any("max_turn" in i and "Extra inputs" in i for i in issues_for(tmp_path))


def test_name_must_match_folder(tmp_path: Path) -> None:
    write(tmp_path, "folder", "other")
    assert any("must match the folder name 'folder'" in i for i in issues_for(tmp_path))


def test_unknown_tool_hook_schema_and_model(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "agent.md").write_text(
        "---\nname: a\ndescription: d\nversion: 1\nmodel: gpt-unknown\nmax_turns: 5\n"
        "tools: [teleport]\noutput_schema: Nope\n"
        "hooks: {pre_tool: [ghost], session_start: [redact]}\n---\nHi\n"
    )
    found = issues_for(tmp_path)
    assert any("unknown model alias 'gpt-unknown'" in i for i in found)
    assert any("unknown tool 'teleport'" in i for i in found)
    assert any("unknown output schema 'Nope'" in i for i in found)
    assert any("unknown hook 'ghost'" in i for i in found)
    assert any("hook 'redact' is registered for 'post_tool'" in i for i in found)


def test_explicit_provider_model_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "agent.md").write_text(
        "---\nname: a\ndescription: d\nversion: 1\nmodel: openai:gpt-4.1-mini\n"
        "max_turns: 5\n---\nHi\n"
    )
    assert load_agents(tmp_path, CATALOG, CEILINGS).get("a").frontmatter.model == (
        "openai:gpt-4.1-mini"
    )


def test_limits_cannot_exceed_server_ceilings(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "agent.md").write_text(
        "---\nname: a\ndescription: d\nversion: 1\nmodel: chat\nmax_turns: 500\n"
        "limits: {max_cost_usd: 9.5, timeout_s: 5000}\n---\nHi\n"
    )
    found = issues_for(tmp_path)
    assert any("max_turns: 500 exceeds the server ceiling 100" in i for i in found)
    assert any("max_cost_usd: 9.5 exceeds the server ceiling 2.0" in i for i in found)
    assert any("timeout_s: 5000 exceeds the server ceiling 1200" in i for i in found)


def test_subagent_cannot_declare_subagents_or_session_hooks(tmp_path: Path) -> None:
    write(tmp_path, "m", "m")
    write(tmp_path, "m/s", "s", extra="subagents: [x]\nhooks: {session_start: [load_ctx]}")
    found = issues_for(tmp_path)
    assert any("m/s/agent.md: subagents: Extra inputs" in i for i in found)
    assert any("hooks.session_start: Extra inputs" in i for i in found)


def test_subagents_are_leaves(tmp_path: Path) -> None:
    write(tmp_path, "m", "m")
    write(tmp_path, "m/s", "s")
    write(tmp_path, "m/s/deeper", "deeper")
    assert any("sub-agents are leaf agents" in i for i in issues_for(tmp_path))


def test_subagent_cannot_use_approval_gated_tools(tmp_path: Path) -> None:
    write(tmp_path, "m", "m", extra="tools: [send_email]")  # fine for a main agent
    write(tmp_path, "m/s", "s", extra="tools: [send_email]")
    found = issues_for(tmp_path)
    assert len(found) == 1  # only the sub-agent is flagged
    assert found[0].endswith(
        "m/s/agent.md: tools: 'send_email' needs human approval; sub-agents can't use it"
    )


def test_folder_without_definition(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    write(tmp_path, "m", "m")
    (tmp_path / "m" / "orphan").mkdir()
    found = issues_for(tmp_path)
    assert any("empty: agent folder has no agent.md" in i for i in found)
    assert any("m/orphan: agent folder has no agent.md" in i for i in found)


def test_prompt_placeholders_are_allow_listed(tmp_path: Path) -> None:
    write(tmp_path, "m", "m", body="Today is {{date}}. Run {{ os.system }}.")
    write(tmp_path, "m/s", "s", body="Session {{session.title}}")  # main-only placeholder
    found = issues_for(tmp_path)
    assert any("unknown placeholder {{os.system}}" in i for i in found)
    assert any("m/s/agent.md: prompt: unknown placeholder {{session.title}}" in i for i in found)


def test_empty_prompt(tmp_path: Path) -> None:
    write(tmp_path, "m", "m", body="")
    assert any("the body (system prompt) is empty" in i for i in issues_for(tmp_path))


def test_yaml_is_loaded_safely(tmp_path: Path) -> None:
    """An unsafe YAML loader would execute this. The safe loader refuses the tag."""
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "agent.md").write_text(
        "---\nname: !!python/object/apply:os.system ['echo pwned']\n---\nHi\n"
    )
    assert any("invalid YAML frontmatter" in i for i in issues_for(tmp_path))


def test_all_problems_are_reported_at_once(tmp_path: Path) -> None:
    write(tmp_path, "a", "wrong-name")
    write(tmp_path, "b", "b", extra="tools: [teleport]")
    assert len(issues_for(tmp_path)) >= 2


def test_hash_is_stable_and_scoped(tmp_path: Path) -> None:
    write(tmp_path, "m", "m")
    write(tmp_path, "m/s", "s")
    first = load_agents(tmp_path, CATALOG, CEILINGS).get("m")
    again = load_agents(tmp_path, CATALOG, CEILINGS).get("m")
    assert content_hash(canonical_content(first)) == content_hash(canonical_content(again))

    write(tmp_path, "m/s", "s", body="Changed sub-agent prompt.")
    after_sub_edit = load_agents(tmp_path, CATALOG, CEILINGS).get("m")
    # editing a sub-agent doesn't change the main agent's snapshot …
    assert content_hash(canonical_content(after_sub_edit)) == content_hash(canonical_content(first))
    # … but does change the sub-agent's own
    assert content_hash(canonical_content(after_sub_edit.subagents[0])) != content_hash(
        canonical_content(first.subagents[0])
    )
