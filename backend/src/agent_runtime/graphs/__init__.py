"""Graph registry: the graphs runs can execute, by name.

Pattern: Registry. The API validates `POST /runs {graph}` against it and
describes graphs for the UI (`GET /graphs`); the executor builds from it.
`compile(checkpointer)` is called per execution, so each run gets its own
fenced checkpointer. Plain graphs use `GraphSpec.of_state_graph`; agent graphs
(create_agent) compile themselves and carry their agent definition.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph
from langgraph.pregel import Pregel
from pydantic import BaseModel

if TYPE_CHECKING:
    from agent_runtime.agents.schema import AgentDefinition

Compile = Callable[[BaseCheckpointSaver[Any] | None], Pregel[Any, Any]]


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _json_state(state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(json.dumps(state, default=str))
    return result


@dataclass(frozen=True)
class GraphSpec:
    name: str
    description: str
    input_model: type[BaseModel]  # validates `POST /runs {input}` (422 on error)
    compile: Compile
    to_graph_input: Callable[[BaseModel], dict[str, Any]] = _dump
    to_output: Callable[[dict[str, Any]], dict[str, Any]] = _json_state
    agent: AgentDefinition | None = field(default=None)  # agent graphs: grants, hooks, limits
    # The skill versions the agent and its helpers use, by owner ("" = the main agent).
    skills: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)

    @classmethod
    def of_state_graph(
        cls,
        name: str,
        description: str,
        input_model: type[BaseModel],
        build: Callable[[], StateGraph[Any, Any, Any, Any]],
    ) -> GraphSpec:
        return cls(name, description, input_model, lambda cp: build().compile(checkpointer=cp))


class UnknownGraph(LookupError):
    pass


class GraphRegistry:
    def __init__(self, specs: list[GraphSpec]) -> None:
        self._specs = {s.name: s for s in specs}

    def get(self, name: str) -> GraphSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise UnknownGraph(f"unknown graph {name!r}") from None

    def __iter__(self) -> Iterator[GraphSpec]:
        return iter(self._specs[n] for n in sorted(self._specs))


def default_registry() -> GraphRegistry:
    from agent_runtime.graphs.assistant import specs as agent_specs
    from agent_runtime.graphs.fanout import SPEC as FANOUT
    from agent_runtime.graphs.toy import SPEC as TOY

    return GraphRegistry([TOY, FANOUT, *agent_specs()])
