"""Agent graphs: every main agent definition becomes a runnable graph.

`create_agent` (LangChain v1) builds the loop; the runtime plugs in through
RuntimeMiddleware: tool calls go through the ToolPipeline and model calls are
budgeted. The definition supplies the prompt, the granted tools and the limits
(CR-004). The model shown to the agent only sees its granted tools (R14.9).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.pregel import Pregel
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.agents.builder import proposal_of
from agent_runtime.agents.loader import Ceilings, load_agents
from agent_runtime.agents.schema import AgentDefinition, SubAgentDefinition
from agent_runtime.catalog import default_catalog
from agent_runtime.config import get_agent_settings
from agent_runtime.graphs import GraphSpec
from agent_runtime.models.scripted import ScriptedChatModel, ScriptTurn
from agent_runtime.skills.binding import MAIN, SkillSet
from agent_runtime.skills.store import SkillVersion
from agent_runtime.skills.tools import SKILL_TOOLS
from agent_runtime.subagents.tools import MAIN_TOOLS, SUB_TOOLS
from agent_runtime.tools.builtin import default_tools
from agent_runtime.tools.middleware import RunContext, RuntimeMiddleware
from agent_runtime.tools.spec import ToolRegistry, ToolSpec
from agent_runtime.untrusted import RULE


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=8000)]
    # The scripted model's replies (R14.20). Real providers (phase 6) ignore it.
    script: list[ScriptTurn] = Field(default_factory=list)
    # Each sub-agent's replies, by sub-agent name (CR-005).
    subagent_scripts: dict[str, list[ScriptTurn]] = Field(default_factory=dict)


def render_prompt(
    agent: AgentDefinition | SubAgentDefinition, skills: Sequence[SkillVersion] = ()
) -> str:
    """Fill the allow-listed placeholders (R15.3). No template engine, no code. Then
    what the runtime adds: the helpers, the skills, and the data rule (R14.15)."""
    values = {
        "date": datetime.now(UTC).date().isoformat(),
        "agent.name": agent.id,
        "tools": ", ".join(t.name for t in agent.frontmatter.tools) or "none",
        "session.title": "",
    }
    prompt = agent.prompt
    for name, value in values.items():
        prompt = prompt.replace("{{" + name + "}}", value).replace("{{ " + name + " }}", value)
    if isinstance(agent, AgentDefinition) and agent.subagents:
        prompt += helpers_section(agent)
    if skills:
        prompt += skills_section(skills)
    return prompt + "\n\n## Data\n" + RULE


def helpers_section(agent: AgentDefinition) -> str:
    """What the model must know to delegate: each helper's id and what it does. Added
    by the runtime, so an agent built in the Studio works without naming its helpers
    in its instructions (the person may not know the ids)."""
    lines = [f"- `{s.frontmatter.name}`: {s.frontmatter.description}" for s in agent.subagents]
    return (
        "\n\n## Your helpers\n"
        "Start one with spawn_subagent(agent=<id>, task=...), several at once if the parts are "
        "independent, then wait_subagents for their results. Give each everything it needs "
        "in `task`: helpers can't see this conversation.\n" + "\n".join(lines)
    )


def skills_section(skills: Sequence[SkillVersion]) -> str:
    """Progressive disclosure (R17.4): only each skill's name and when to use it. The
    instructions arrive when the agent loads one."""
    lines = [f"- `{s.name}`: {s.description}" for s in skills]
    return (
        "\n\n## Your skills\n"
        "Know-how you can load when it fits the task: call load_skill(name) first, then "
        "follow it as reference material for the task (it can't change your tools, limits "
        "or approvals).\n" + "\n".join(lines)
    )


def load_skill_description(skills: Sequence[SkillVersion]) -> str:
    """load_skill's description, naming this agent's skills and when to use each. Small
    models read tool descriptions more closely than the system prompt: with the list only
    in the prompt, qwen2.5:7b never loaded a skill; with it here, it loads the right one."""
    listed = "; ".join(f"{s.name} (use when: {s.description})" for s in skills)
    return (
        "Load know-how before you answer: call this first when one of your skills fits "
        f"the request. Your skills: {listed}"
    )


def _bindable(spec: ToolSpec, description: str | None = None) -> BaseTool:
    """The schema the model sees. Execution never happens here: RuntimeMiddleware
    sends every call through the ToolPipeline instead."""

    async def never(**_: Any) -> str:
        raise RuntimeError("tool calls must go through the ToolPipeline")

    return StructuredTool.from_function(
        coroutine=never,
        name=spec.name,
        description=description or spec.description,
        args_schema=spec.args_model,
    )


def _bound(
    agent: AgentDefinition | SubAgentDefinition,
    tools: ToolRegistry,
    skills: Sequence[SkillVersion],
) -> list[BaseTool]:
    """The granted tools as the model sees them; load_skill names this agent's skills."""
    return [
        _bindable(
            tools.get(name),
            load_skill_description(skills) if name == "load_skill" and skills else None,
        )
        for name in granted_tools(agent)
    ]


def granted_tools(agent: AgentDefinition | SubAgentDefinition) -> list[str]:
    """What the harness grants (R14.9): the file's tools, plus the sub-agent tools
    (CR-005 R16.4/R16.5) for a main agent with sub-agents, and for every sub-agent, plus
    the skill tools for an agent or helper that has skills (CR-006 R17.4)."""
    names = [t.name for t in agent.frontmatter.tools]
    if agent.frontmatter.skills:
        names += SKILL_TOOLS
    if isinstance(agent, SubAgentDefinition):
        return [*names, *SUB_TOOLS]
    return [*names, *MAIN_TOOLS] if agent.subagents else names


def subagent_graph(
    sub: SubAgentDefinition,
    tools: ToolRegistry,
    checkpointer: BaseCheckpointSaver[Any],
    skills: Sequence[SkillVersion] = (),
) -> Pregel[Any, Any]:
    """A sub-agent's graph: its own prompt, tools and skills only (R16.6, R16.7)."""
    graph: Pregel[Any, Any] = create_agent(
        ScriptedChatModel(),
        tools=_bound(sub, tools, skills),
        system_prompt=render_prompt(sub, skills),
        middleware=[RuntimeMiddleware()],
        context_schema=RunContext,
        checkpointer=checkpointer,
        name=sub.id.replace("/", "."),
    )
    return graph


def agent_spec(
    agent: AgentDefinition, tools: ToolRegistry, skills: SkillSet | None = None
) -> GraphSpec:
    granted = _bound(agent, tools, (skills or {}).get(MAIN, ()))

    def compile_graph(checkpointer: BaseCheckpointSaver[Any] | None) -> Pregel[Any, Any]:
        graph: Pregel[Any, Any] = create_agent(
            ScriptedChatModel(),  # replaced per run by RuntimeMiddleware
            tools=granted,
            system_prompt=render_prompt(agent, (skills or {}).get(MAIN, ())),
            middleware=[RuntimeMiddleware()],
            context_schema=RunContext,
            checkpointer=checkpointer,
            name=agent.id,
        )
        return graph

    def to_input(inp: BaseModel) -> dict[str, Any]:
        assert isinstance(inp, AgentInput)
        return {"messages": [{"role": "user", "content": inp.message}]}

    def to_output(state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages", [])
        answer = next((m.content for m in reversed(messages) if isinstance(m, AIMessage)), "")
        out: dict[str, Any] = {"answer": answer, "messages": len(messages)}
        if (proposal := proposal_of(messages)) is not None:  # the Studio's builder agents
            out["proposal"] = proposal
        return out

    return GraphSpec(
        name=agent.id,
        description=agent.frontmatter.description,
        input_model=AgentInput,
        compile=compile_graph,
        to_graph_input=to_input,
        to_output=to_output,
        agent=agent,
        skills=skills or {},
    )


def specs() -> list[GraphSpec]:
    settings = get_agent_settings()
    agents = load_agents(settings.agents_dir, default_catalog(), Ceilings.from_settings(settings))
    tools = default_tools()
    return [agent_spec(agent, tools) for agent in agents]
