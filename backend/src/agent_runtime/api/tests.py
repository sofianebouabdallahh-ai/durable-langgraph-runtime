"""A Studio agent's tests (phase H6): the Tests tab.

    GET    /studio/agents/{id}/tests              its cases, each with its latest result
    POST   /studio/agents/{id}/tests              add a case
    PUT    /studio/agents/{id}/tests/{case_id}    change it (earlier results go stale)
    DELETE /studio/agents/{id}/tests/{case_id}
    POST   /studio/agents/{id}/tests/run          run them all on the draft
    POST   /runs/{run_id}/make-test               a 👎 reply becomes a test

Each case runs as a turn in its own test chat; a worker grades it when it ends. A draft
with tests publishes only once every case passed on exactly that draft.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from agent_runtime.agents.studio import StudioService
from agent_runtime.evals.cases import Case
from agent_runtime.evals.service import EvalService
from agent_runtime.evals.store import Result, StoredCase

tests_router = APIRouter(tags=["tests"])


def _evals(request: Request) -> EvalService:
    service: EvalService = request.app.state.evals
    return service


def _studio(request: Request) -> StudioService:
    service: StudioService = request.app.state.studio
    return service


EvalsDep = Annotated[EvalService, Depends(_evals)]
StudioDep = Annotated[StudioService, Depends(_studio)]


class CheckView(BaseModel):
    check: str
    ok: bool
    detail: str = ""
    error: bool = False


class ResultView(BaseModel):
    status: Literal["running", "passed", "failed", "error"]
    current: bool = Field(description="On this draft, and the case as it is now")
    checks: list[CheckView]
    run_id: uuid.UUID
    session_id: uuid.UUID | None = Field(description="Its test chat, to see what happened")
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, r: Result, case: StoredCase, digest: str | None) -> ResultView:
        current = r.bundle_hash == digest and r.case_hash == case.case.digest()
        return cls(status=r.status, current=current, checks=[CheckView(**c) for c in r.checks],  # type: ignore[arg-type]
                   run_id=r.run_id, session_id=r.session_id, created_at=r.created_at,
                   finished_at=r.finished_at)  # fmt: skip


class CaseView(BaseModel):
    id: uuid.UUID
    case: Case
    from_run: uuid.UUID | None
    result: ResultView | None = Field(description="Its latest result, current or not")
    updated_at: datetime


class TestsView(BaseModel):
    cases: list[CaseView]
    passing: int = Field(description="Cases passed on this draft, as they are now")
    blocking: bool = Field(description="Publishing waits for these tests")


class RunStarted(BaseModel):
    batch: uuid.UUID
    cases: int


def _view(c: StoredCase, results: dict[str, Result], digest: str | None) -> CaseView:
    r = results.get(str(c.id))
    return CaseView(id=c.id, case=c.case, from_run=c.from_run, updated_at=c.updated_at,
                    result=ResultView.of(r, c, digest) if r else None)  # fmt: skip


async def _digest(studio: StudioService, agent_id: uuid.UUID) -> str | None:
    state = await studio.get(agent_id)
    return state.draft.digest if state.draft else None


@tests_router.get("/studio/agents/{agent_id}/tests", response_model=TestsView,
                  summary="Its tests, each with its latest result")  # fmt: skip
async def list_tests(agent_id: uuid.UUID, evals: EvalsDep, studio: StudioDep) -> TestsView:
    cases = await evals.cases(agent_id)
    digest = await _digest(studio, agent_id)
    results = await evals.newest(agent_id)
    views = [_view(c, results, digest) for c in cases]
    passing = sum(1 for v in views if v.result and v.result.current
                  and v.result.status == "passed")  # fmt: skip
    return TestsView(cases=views, passing=passing, blocking=bool(cases))


@tests_router.post("/studio/agents/{agent_id}/tests", response_model=CaseView,
                   status_code=status.HTTP_201_CREATED, summary="Add a test")  # fmt: skip
async def add_test(agent_id: uuid.UUID, case: Case, evals: EvalsDep) -> CaseView:
    return _view(await evals.add(agent_id, case), {}, None)


@tests_router.put("/studio/agents/{agent_id}/tests/{case_id}", response_model=CaseView,
                  summary="Change a test (its earlier results no longer count)")  # fmt: skip
async def change_test(
    agent_id: uuid.UUID, case_id: uuid.UUID, case: Case, evals: EvalsDep
) -> CaseView:
    return _view(await evals.replace(agent_id, case_id, case), {}, None)


@tests_router.delete("/studio/agents/{agent_id}/tests/{case_id}",
                     status_code=status.HTTP_204_NO_CONTENT, summary="Remove a test")  # fmt: skip
async def remove_test(agent_id: uuid.UUID, case_id: uuid.UUID, evals: EvalsDep) -> Response:
    await evals.remove(agent_id, case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@tests_router.post("/studio/agents/{agent_id}/tests/run", response_model=RunStarted,
                   status_code=status.HTTP_202_ACCEPTED,
                   summary="Run every test on the draft, each in its own test chat")  # fmt: skip
async def run_tests(agent_id: uuid.UUID, evals: EvalsDep) -> RunStarted:
    batch = await evals.run(agent_id)
    return RunStarted(batch=batch, cases=len(await evals.batch(batch)))


@tests_router.post("/runs/{run_id}/make-test", response_model=CaseView,
                   status_code=status.HTTP_201_CREATED,
                   summary="Make a test from a reply: its message, the 👎 reason")  # fmt: skip
async def make_test(run_id: uuid.UUID, evals: EvalsDep) -> dict[str, Any]:
    return _view(await evals.from_run(run_id), {}, None).model_dump()
