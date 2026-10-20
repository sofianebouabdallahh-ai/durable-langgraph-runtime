"""The kill switch (phase L6): stop one agent, or every agent, now.

    GET  /kill-switch           what is switched off
    POST /kill-switch/stop      {agent?, reason?}: switch it off; its runs stop now
    POST /kill-switch/resume    {agent?}: switch it back on

Without `agent`: every agent (the runtime's admission pause, R14.18). Always served,
unlike the internal admin API: stopping agents is a safety control people need.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.runs.kill_switch import KillSwitch
from agent_runtime.runs.switches import KillSwitchState

kill_switch_router = APIRouter(prefix="/kill-switch", tags=["kill switch"])

AgentName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)]


def _service(request: Request) -> KillSwitch:
    service: KillSwitch = request.app.state.kill_switch
    return service


ServiceDep = Annotated[KillSwitch, Depends(_service)]


class SwitchView(BaseModel):
    agent: str
    reason: str | None
    since: datetime


class KillSwitchView(BaseModel):
    all_off: bool = Field(description="Every agent is stopped")
    reason: str | None
    since: datetime | None
    agents: list[SwitchView] = Field(description="Agents switched off one by one")

    @classmethod
    def of(cls, state: KillSwitchState) -> KillSwitchView:
        return cls(
            all_off=state.all_off,
            reason=state.reason,
            since=state.since,
            agents=[
                SwitchView(agent=s.agent, reason=s.reason, since=s.since) for s in state.agents
            ],
        )


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentName | None = Field(default=None, description="None: every agent")
    reason: Annotated[str, Field(max_length=500)] | None = None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentName | None = Field(default=None, description="None: every agent")


class StopResult(KillSwitchView):
    cancelled: int = Field(description="Runs stopped (their helpers and children with them)")


@kill_switch_router.get("", response_model=KillSwitchView, summary="What is switched off")
async def state(service: ServiceDep) -> KillSwitchView:
    return KillSwitchView.of(await service.state())


@kill_switch_router.post("/stop", response_model=StopResult, summary="Stop an agent, or all, now")
async def stop(body: StopRequest, service: ServiceDep) -> StopResult:
    cancelled = await service.stop(body.agent, body.reason)
    view = KillSwitchView.of(await service.state())
    return StopResult(**view.model_dump(), cancelled=cancelled)


@kill_switch_router.post("/resume", response_model=KillSwitchView, summary="Switch back on")
async def resume(body: ResumeRequest, service: ServiceDep) -> KillSwitchView:
    await service.resume(body.agent)
    return KillSwitchView.of(await service.state())
