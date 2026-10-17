"""Child runs from a workflow node (R2.8): `await ctx.spawner.spawn([...])`.

A node hands the runtime a list of children and gets their results back:

    async def research(state, runtime: Runtime[WorkflowContext]):
        fan_in = await runtime.context.spawner.spawn(
            [ChildSpec(key=f"q{i}", graph="toy", input={...}) for i, q in enumerate(qs)]
        )
        # fan_in.children: one ChildResult per child, in order; fan_in.partial

Pattern: Ports & Adapters. Nodes depend on the `Spawner` port:

- `RunSpawner` (production) raises `interrupt({"type": "spawn_children", …})`.
  The executor fans out in one fenced transaction (children are queued runs that
  land on ANY worker; the parent waits in `waiting_children` holding no lease).
  When the last child ends the parent is re-queued, and LangGraph re-runs this
  node with `interrupt()` returning the fan-in, computed from `run_results`.
- `LocalSpawner` (`--local-fanout`, tests) runs the children in-process and
  persists nothing. Same node code, no workers.

A breached limit (R14.6) or a malformed fan-out raises `FanOutRejected` in the
node, which may handle it: it is an error the workflow sees, not a crash.
"""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.runs.store import FanOutRejected

if TYPE_CHECKING:
    from agent_runtime.graphs import GraphRegistry

__all__ = [
    "SPAWN_CHILDREN",
    "ChildResult",
    "ChildSpec",
    "FanIn",
    "FanOutRejected",
    "LocalSpawner",
    "RunSpawner",
    "Spawner",
    "WorkflowContext",
    "is_spawn",
]

SPAWN_CHILDREN = "spawn_children"  # the interrupt payload type the executor acts on


class ChildSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]
    graph: str
    input: dict[str, Any]
    options: dict[str, Any] | None = None


class ChildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    run_id: uuid.UUID | None  # None for local fan-out
    status: Literal["completed", "failed", "cancelled"]
    reason: str | None = None
    output: dict[str, Any] | None = None


class FanIn(BaseModel):
    model_config = ConfigDict(frozen=True)

    children: list[ChildResult]
    partial: bool  # some child did not complete (R2.8)


class Spawner(Protocol):
    async def spawn(self, children: list[ChildSpec]) -> FanIn: ...


def is_spawn(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("type") == SPAWN_CHILDREN


class RunSpawner:
    """Children as durable runs on any worker (the interrupt protocol above)."""

    async def spawn(self, children: list[ChildSpec]) -> FanIn:
        resume = interrupt(
            {"type": SPAWN_CHILDREN, "children": [c.model_dump(mode="json") for c in children]}
        )
        if isinstance(resume, dict) and "rejected" in resume:
            raise FanOutRejected(str(resume["rejected"]))
        return FanIn.model_validate(resume)


@dataclass
class LocalSpawner:
    """Children in-process, concurrently, nothing persisted (`--local-fanout`).

    Each child runs in a fresh contextvars.Context: a graph started from inside a
    running node otherwise inherits the parent's run (measured in the phase 5
    research: the parent's callbacks saw the child's nodes)."""

    graphs: GraphRegistry
    max_children: int = 6

    async def spawn(self, children: list[ChildSpec]) -> FanIn:
        if not children:
            raise FanOutRejected("a fan-out needs at least one child")
        if len({c.key for c in children}) != len(children):
            raise FanOutRejected("child keys must be unique")
        if len(children) > self.max_children:
            raise FanOutRejected(f"max_children={self.max_children} exceeded")
        results = await asyncio.gather(*(self._run(c) for c in children))
        return FanIn(children=results, partial=any(r.status != "completed" for r in results))

    async def _run(self, child: ChildSpec) -> ChildResult:
        spec = self.graphs.get(child.graph)
        if spec.agent is not None:
            raise FanOutRejected("local fan-out runs workflow graphs only")
        graph = spec.compile(None)
        inp = spec.to_graph_input(spec.input_model.model_validate(child.input))
        ctx = WorkflowContext(spawner=self)
        task = asyncio.create_task(graph.ainvoke(inp, context=ctx), context=contextvars.Context())
        try:
            state = await task
        except Exception as exc:
            return ChildResult(key=child.key, run_id=None, status="failed", reason=repr(exc))
        return ChildResult(
            key=child.key, run_id=None, status="completed", output=spec.to_output(state)
        )


@dataclass(frozen=True)
class WorkflowContext:
    """LangGraph runtime context for workflow (non-agent) graphs."""

    spawner: Spawner
