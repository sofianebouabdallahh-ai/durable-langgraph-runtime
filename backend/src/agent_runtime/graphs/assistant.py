"""Agent graphs: every main agent definition becomes a runnable graph.

`create_agent` (LangChain v1) builds the loop; the runtime plugs in through
RuntimeMiddleware: tool calls go through the ToolPipeline and model calls are
budgeted. The definition supplies the prompt, the granted tools and the limits
(CR-004). The model shown to the agent only sees its granted tools (R14.9).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.pregel import Pregel
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.agents.loader import Ceilings, load_agents
from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.catalog import default_catalog
from agent_runtime.config import get_agent_settings
from agent_runtime.graphs import GraphSpec
from agent_runtime.models.scripted import ScriptedChatModel, ScriptTurn
from agent_runtime.tools.builtin import default_tools
from agent_runtime.tools.middleware import RunContext, RuntimeMiddleware
from agent_runtime.tools.spec import ToolRegistry, ToolSpec


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=8000)]
    # The scripted model's replies (R14.20). Real providers (phase 6) ignore it.
    script: list[ScriptTurn] = Field(default_factory=list)


def render_prompt(agent: AgentDefinition) -> str:
    """Fill the allow-listed placeholders (R15.3). No template engine, no code."""
    values = {
        "date": datetime.now(UTC).date().isoformat(),
        "agent.name": agent.id,
        "tools": ", ".join(t.name for t in agent.frontmatter.tools) or "none",
        "session.title": "",
    }
    prompt = agent.prompt
    for name, value in values.items():
        prompt = prompt.replace("{{" + name + "}}", value).replace("{{ " + name + " }}", value)
    return prompt


def _bindable(spec: ToolSpec) -> BaseTool:
    """The schema the model sees. Execution never happens here: RuntimeMiddleware
    sends every call through the ToolPipeline instead."""

    async def never(**_: Any) -> str:
        raise RuntimeError("tool calls must go through the ToolPipeline")

    return StructuredTool.from_function(
        coroutine=never, name=spec.name, description=spec.description, args_schema=spec.args_model
    )


def agent_spec(agent: AgentDefinition, tools: ToolRegistry) -> GraphSpec:
    granted = [_bindable(tools.get(t.name)) for t in agent.frontmatter.tools]

    def compile_graph(checkpointer: BaseCheckpointSaver[Any] | None) -> Pregel[Any, Any]:
        graph: Pregel[Any, Any] = create_agent(
            ScriptedChatModel(),  # replaced per run by RuntimeMiddleware
            tools=granted,
            system_prompt=render_prompt(agent),
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
        return {"answer": answer, "messages": len(messages)}

    return GraphSpec(
        name=agent.id,
        description=agent.frontmatter.description,
        input_model=AgentInput,
        compile=compile_graph,
        to_graph_input=to_input,
        to_output=to_output,
        agent=agent,
    )


def specs() -> list[GraphSpec]:
    settings = get_agent_settings()
    agents = load_agents(settings.agents_dir, default_catalog(), Ceilings.from_settings(settings))
    tools = default_tools()
    return [agent_spec(agent, tools) for agent in agents]
