"""`fanout`: plan → research (N child runs) → synthesize. The R2.8 demo.

The research node fans out one `toy` child run per sub-question. With the
production spawner each child is a queued run that any worker can claim (AC6);
with `--local-fanout` they run in-process. Inputs let tests slow the children
down (`child_delay_s`) or make chosen ones fail (`fail`), to exercise partial
results and crashes.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.graphs import GraphSpec
from agent_runtime.runs.fanout import ChildSpec, FanOutRejected, WorkflowContext


class FanoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: Annotated[str, Field(min_length=1, max_length=2000)]
    n: Annotated[int, Field(ge=1, le=20)] = 3  # above max_children (6) → rejected (R14.6)
    child_delay_s: Annotated[float, Field(ge=0, le=60)] = 0.0
    fail: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)  # child indexes


class FanoutState(TypedDict, total=False):
    topic: str
    n: int
    child_delay_s: float
    fail: list[int]
    questions: list[str]
    answers: list[dict[str, Any]]
    partial: bool
    rejected: str | None
    summary: str


async def plan(state: FanoutState) -> FanoutState:
    return {"questions": [f"{state['topic']}: aspect {i + 1}" for i in range(state["n"])]}


async def research(state: FanoutState, runtime: Runtime[WorkflowContext]) -> FanoutState:
    children = [
        ChildSpec(
            key=f"q{i}",
            graph="toy",
            input={
                "question": q,
                "delay_s": state.get("child_delay_s", 0.0),
                "fail_at": "research" if i in state.get("fail", []) else None,
            },
        )
        for i, q in enumerate(state["questions"])
    ]
    try:
        fan_in = await runtime.context.spawner.spawn(children)
    except FanOutRejected as exc:  # a limit (R14.6): the workflow decides what to do
        return {"rejected": exc.reason, "answers": [], "partial": False}
    answers = [
        {
            "key": c.key,
            "run_id": str(c.run_id) if c.run_id else None,
            "status": c.status,
            "answer": (c.output or {}).get("answer"),
        }
        for c in fan_in.children
    ]
    return {"answers": answers, "partial": fan_in.partial, "rejected": None}


async def synthesize(state: FanoutState) -> FanoutState:
    if state.get("rejected"):
        return {"summary": f"No research: {state['rejected']}"}
    done = [a for a in state["answers"] if a["status"] == "completed"]
    note = " (partial)" if state.get("partial") else ""
    return {"summary": f"{len(done)}/{len(state['answers'])} sub-questions answered{note}"}


def build() -> StateGraph[FanoutState, WorkflowContext, FanoutState, FanoutState]:
    g = StateGraph(FanoutState, context_schema=WorkflowContext)
    g.add_node("plan", plan)
    g.add_node("research", research)
    g.add_node("synthesize", synthesize)
    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "synthesize")
    g.add_edge("synthesize", END)
    return g


SPEC = GraphSpec.of_state_graph(
    name="fanout",
    description="plan → research (one child run per sub-question, on any worker) → synthesize.",
    input_model=FanoutInput,
    build=build,
)
