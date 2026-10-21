"""Getting started (phase L3d): the guide's progress, derived from the account.

GET /onboarding    the five steps (done / skipped), the next one, the guide's agent
PUT /onboarding    the guide's choices: its agent, skip the model step, dismiss, restart
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime import onboarding
from agent_runtime.db import Pool

onboarding_router = APIRouter(prefix="/onboarding", tags=["onboarding"])
StepKey = Literal["model", "agent", "tool", "helper", "try"]


def _pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


PoolDep = Annotated[Pool, Depends(_pool)]


class Step(BaseModel):
    key: StepKey
    done: bool
    skipped: bool


class GuideAgentView(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str


class Tried(BaseModel):
    tested: bool = False
    published: bool = False
    chatted: bool = False


class OnboardingView(BaseModel):
    steps: list[Step]
    next: StepKey | None = Field(description="The first step neither done nor skipped")
    finished: bool
    dismissed: bool
    agent: GuideAgentView | None = Field(description="The agent built in the guide")
    tried: Tried = Field(description="Step 5's parts")


class OnboardingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID | None = Field(default=None, description="Make this the guide's agent")
    skip_model: bool | None = Field(default=None, description="Use the demo model for now")
    dismissed: bool | None = None
    restart: bool = False


async def view(request: Request, pool: Pool) -> OnboardingView:
    real = request.app.state.settings.model_provider != "scripted"
    async with pool.connection() as conn:
        p = await onboarding.progress(conn, real_setup_model=real)
    return OnboardingView(
        steps=[Step(key=s, done=p.done[s], skipped=p.skipped[s]) for s in onboarding.STEPS],
        next=p.next, finished=p.finished, dismissed=p.dismissed,
        agent=GuideAgentView(id=p.agent.id, name=p.agent.name, display_name=p.agent.display_name)
        if p.agent else None,
        tried=Tried(**p.tried),
    )  # fmt: skip


@onboarding_router.get("", response_model=OnboardingView, summary="Where the guide stands")
async def get_onboarding(request: Request, pool: PoolDep) -> OnboardingView:
    return await view(request, pool)


@onboarding_router.put("", response_model=OnboardingView, summary="The guide's choices")
async def put_onboarding(body: OnboardingUpdate, request: Request, pool: PoolDep) -> OnboardingView:
    async with pool.connection() as conn, conn.transaction():
        await onboarding.update(
            conn, agent_id=body.agent_id, skip_model=body.skip_model,
            dismissed=body.dismissed, restart=body.restart,
        )  # fmt: skip
    return await view(request, pool)
