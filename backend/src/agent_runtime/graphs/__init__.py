"""Graph registry: the graphs runs can execute, by name.

Pattern: Registry. The API validates `POST /runs {graph}` against it and
describes graphs for the UI (`GET /graphs`); the executor builds from it.
Builders return an *uncompiled* StateGraph: the executor compiles each run
with its own fenced checkpointer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from langgraph.graph import StateGraph
from pydantic import BaseModel


@dataclass(frozen=True)
class GraphSpec:
    name: str
    description: str
    input_model: type[BaseModel]  # validates `POST /runs {input}` (422 on error)
    build: Callable[[], StateGraph[Any, Any, Any, Any]]


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
    from agent_runtime.graphs import toy

    return GraphRegistry([toy.SPEC])
