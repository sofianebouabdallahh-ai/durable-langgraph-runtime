"""`toy`: a deterministic 3-step graph (plan → research → answer).

No model, no tools: it exists to exercise the runtime itself (checkpoints,
events, limits, crash and resume) with nothing else that can fail. Inputs let
tests slow it down (`delay_s`) or make a chosen node fail (`fail_at`).
"""

from __future__ import annotations

import asyncio
import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.graphs import GraphSpec

NodeName = Literal["plan", "research", "answer"]


class ToyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=2000)]
    delay_s: Annotated[float, Field(ge=0, le=60)] = 0.0
    fail_at: NodeName | None = None


class ToyState(TypedDict, total=False):
    question: str
    delay_s: float
    fail_at: str | None
    notes: Annotated[list[str], operator.add]
    answer: str


class InducedFailure(RuntimeError):
    pass


async def _work(state: ToyState, node: NodeName) -> None:
    await asyncio.sleep(state.get("delay_s", 0.0))
    if state.get("fail_at") == node:
        raise InducedFailure(f"induced failure in {node}")


async def plan(state: ToyState) -> ToyState:
    await _work(state, "plan")
    return {"notes": [f"plan: break down {state['question']!r}"]}


async def research(state: ToyState) -> ToyState:
    await _work(state, "research")
    return {"notes": ["research: gathered 2 facts"]}


async def answer(state: ToyState) -> ToyState:
    await _work(state, "answer")
    return {"notes": ["answer: composed"], "answer": f"Toy answer to {state['question']!r}"}


def build() -> StateGraph[ToyState, None, ToyState, ToyState]:
    g = StateGraph(ToyState)
    g.add_node("plan", plan)
    g.add_node("research", research)
    g.add_node("answer", answer)
    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "answer")
    g.add_edge("answer", END)
    return g


SPEC = GraphSpec.of_state_graph(
    name="toy",
    description="Deterministic plan → research → answer graph for exercising the runtime.",
    input_model=ToyInput,
    build=build,
)
