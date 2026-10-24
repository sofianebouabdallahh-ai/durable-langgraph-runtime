"""MCP servers and their tools (phase L8): Settings → Tools → MCP servers.

    GET    /mcp/servers                              servers, with their tools
    POST   /mcp/servers                              add (then it's tested at once)
    PATCH  /mcp/servers/{id}                         change (a new token replaces the old)
    DELETE /mcp/servers/{id}                         remove (its tools stop working)
    POST   /mcp/servers/{id}/test                    ask the server for its tools again
    PUT    /mcp/servers/{id}/tools/{tool}            switch a tool on or off; ask first or not
    POST   /mcp/servers/{id}/tools/{tool}/approve    a changed tool, looked at again

A token is never returned: only whether one is set, and its fingerprint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.mcp.service import McpServer, McpService, McpTool, tool_name

mcp_router = APIRouter(prefix="/mcp", tags=["mcp"])


def _service(request: Request) -> McpService:
    service: McpService = request.app.state.mcp
    return service


ServiceDep = Annotated[McpService, Depends(_service)]


class McpToolView(BaseModel):
    name: str = Field(description="As the server names it")
    agent_name: str = Field(description="As agents know it: mcp__<server>__<tool>")
    description: str = Field(description="What the server says now")
    input_schema: dict[str, Any]
    read_only: bool = Field(description="The server says so (a hint, never trusted alone)")
    hints: dict[str, bool]
    enabled: bool
    without_asking: bool
    changed: bool = Field(description="The server changed it since it was switched on")
    approved_description: str | None = Field(description="What was switched on, if different")
    scan: dict[str, Any] = Field(description="The check of its description and arguments")

    @classmethod
    def of(cls, server: McpServer, t: McpTool) -> McpToolView:
        approved = t.definition.description if t.definition and t.changed else None
        return cls(
            name=t.name, agent_name=tool_name(server.name, t.name),
            description=t.latest.description, input_schema=dict(t.latest.input_schema),
            read_only=t.latest.read_only, hints=dict(t.latest.hints), enabled=t.enabled,
            without_asking=t.without_asking, changed=t.changed,
            approved_description=approved, scan=t.scan,
        )  # fmt: skip


class McpServerView(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    url: str
    header_name: str
    has_token: bool
    token_fingerprint: str | None
    status: str = Field(description="untested, ready or failed")
    status_detail: str | None
    protocol_version: str | None
    tested_at: datetime | None
    tools: list[McpToolView]

    @classmethod
    def of(cls, s: McpServer, tools: list[McpTool]) -> McpServerView:
        return cls(
            id=s.id, name=s.name, display_name=s.display_name, url=s.url,
            header_name=s.header_name, has_token=s.has_token,
            token_fingerprint=s.key_fingerprint, status=s.status,
            status_detail=s.status_detail, protocol_version=s.protocol_version,
            tested_at=s.tested_at, tools=[McpToolView.of(s, t) for t in tools],
        )  # fmt: skip


class AddServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=60)]
    url: Annotated[str, Field(min_length=8, max_length=500)]
    token: Annotated[str, Field(max_length=4000)] | None = None
    header_name: Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{1,64}$")] = "Authorization"


class ChangeServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    url: Annotated[str, Field(min_length=8, max_length=500)] | None = None
    token: Annotated[str, Field(max_length=4000)] | None = None
    header_name: Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{1,64}$")] | None = None


class SetTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    without_asking: bool = Field(default=False, description="Only for a read-only tool")


@mcp_router.get("/servers", response_model=list[McpServerView], summary="MCP servers")
async def servers(service: ServiceDep) -> list[McpServerView]:
    return [McpServerView.of(s, tools) for s, tools in await service.servers()]


@mcp_router.post("/servers", status_code=status.HTTP_201_CREATED, response_model=McpServerView,
                 summary="Add an MCP server (it's tested at once)")  # fmt: skip
async def add(body: AddServer, service: ServiceDep) -> McpServerView:
    added = await service.add(display_name=body.display_name, url=body.url, token=body.token,
                              header_name=body.header_name)  # fmt: skip
    return McpServerView.of(*await service.test(added.id))


@mcp_router.patch("/servers/{server_id}", response_model=McpServerView, summary="Change")
async def change(server_id: uuid.UUID, body: ChangeServer, service: ServiceDep) -> McpServerView:
    await service.change(server_id, display_name=body.display_name, url=body.url,
                         token=body.token, header_name=body.header_name)  # fmt: skip
    return McpServerView.of(*await service.server(server_id))


@mcp_router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT,
                   summary="Remove (its tools stop working for every agent)")  # fmt: skip
async def remove(server_id: uuid.UUID, service: ServiceDep) -> Response:
    await service.remove(server_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@mcp_router.post("/servers/{server_id}/test", response_model=McpServerView,
                 summary="Ask the server for its tools")  # fmt: skip
async def test(server_id: uuid.UUID, service: ServiceDep) -> McpServerView:
    return McpServerView.of(*await service.test(server_id))


@mcp_router.put("/servers/{server_id}/tools/{tool}", response_model=McpServerView,
                summary="Switch a tool on or off")  # fmt: skip
async def set_tool(
    server_id: uuid.UUID, tool: str, body: SetTool, service: ServiceDep
) -> McpServerView:
    await service.set_tool(server_id, tool, enabled=body.enabled,
                           without_asking=body.without_asking)  # fmt: skip
    return McpServerView.of(*await service.server(server_id))


@mcp_router.post("/servers/{server_id}/tools/{tool}/approve", response_model=McpServerView,
                 summary="Approve a tool the server changed")  # fmt: skip
async def approve(server_id: uuid.UUID, tool: str, service: ServiceDep) -> McpServerView:
    await service.approve_change(server_id, tool)
    return McpServerView.of(*await service.server(server_id))
