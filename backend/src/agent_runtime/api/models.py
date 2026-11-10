"""Your own models (phase L3b, CR-006 R18.2 to R18.4): what Settings → Models calls.

A key goes in once (POST/PATCH) and never comes out: responses say `has_key` and
show a fingerprint that tells keys apart, nothing more (AC45).

    GET  /models/connections · POST           add (kind, URL, key, models)
    PATCH /models/connections/{id} · DELETE   edit (a new key replaces the old) / remove
    POST /models/connections/{id}/test        the capability check (a tool call)
    GET  /models/connections/{id}/models      what the service says it has
    GET  /models/ollama                       Ollama servers reachable from here
    GET  /models/default · PUT                the default model (what roles use)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.models.connections import Connection, ConnectionService

models_router = APIRouter(prefix="/models", tags=["models"])
Kind = Literal["ollama", "openai", "azure_foundry", "compatible"]


def _service(request: Request) -> ConnectionService:
    service: ConnectionService = request.app.state.connections
    return service


ServiceDep = Annotated[ConnectionService, Depends(_service)]


class PriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_per_mtok: Annotated[float, Field(ge=0, lt=10_000)]
    output_per_mtok: Annotated[float, Field(ge=0, lt=10_000)]


class PriceView(BaseModel):
    input_per_mtok: float = Field(description="USD per 1 million input tokens")
    output_per_mtok: float = Field(description="USD per 1 million output tokens")
    source: Literal["connection", "settings", "built-in", "local", "estimate"] = Field(
        description="Where the price comes from: set here, MODEL_PRICES, Nuria's price list "
        "(dated), free (a model on this machine or network), or an estimate (a deliberately "
        "high default for a model with no known price: set its price)"
    )


class ConnectionView(BaseModel):
    id: uuid.UUID
    name: str = Field(description="What agents say: `<name>:<model>`")
    display_name: str
    kind: Kind
    base_url: str
    has_key: bool = Field(description="A key is saved. The key itself is never returned")
    key_fingerprint: str | None = Field(description="Tells keys apart without revealing them")
    models: list[str]
    prices: dict[str, PriceView] = Field(
        description="What a call to each model costs, and where that price comes from "
        "(phase H2): budgets in USD use it"
    )
    test_status: Literal["untested", "ready", "failed"]
    test_detail: str | None
    tested_model: str | None
    tested_at: datetime | None
    context_tokens: int = Field(
        description="How many tokens its models take in one request (phase H5): what a "
        "chat is fitted and compacted to"
    )
    context_tokens_set: bool = Field(description="Set on this connection, not the default")

    @classmethod
    def of(cls, c: Connection, service: ConnectionService) -> ConnectionView:
        prices = {m: PriceView(**p.as_dict()) for m, p in service.prices_of(c).items()}
        return cls(
            id=c.id, name=c.name, display_name=c.display_name, kind=c.kind, base_url=c.base_url,
            has_key=c.has_key, key_fingerprint=c.key_fingerprint, models=c.models,
            prices=prices, test_status=c.test_status, test_detail=c.test_detail,
            tested_model=c.tested_model, tested_at=c.tested_at,
            context_tokens=service.window_of(c), context_tokens_set=c.context_tokens is not None,
        )  # fmt: skip


class AddConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=60)]
    kind: Kind
    base_url: Annotated[str, Field(min_length=8, max_length=500)]
    api_key: Annotated[str, Field(max_length=500)] | None = None
    models: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=50)] = []


class EditConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    base_url: Annotated[str, Field(min_length=8, max_length=500)] | None = None
    api_key: Annotated[str, Field(max_length=500)] | None = Field(
        default=None, description="A new key replaces the saved one; omit to keep it"
    )
    models: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=50)] | None = (
        None
    )
    prices: Annotated[dict[str, PriceIn | None], Field(max_length=50)] | None = Field(
        default=None,
        description="A price per model, USD per 1 million tokens; null removes one. It wins "
        "over MODEL_PRICES and Nuria's price list",
    )
    context_tokens: Annotated[int, Field(ge=0, le=10_000_000)] | None = Field(
        default=None,
        description="Its models' context window in tokens; 0 goes back to the default",
    )


class TestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Annotated[str, Field(min_length=1, max_length=200)]


class TestView(BaseModel):
    ok: bool
    detail: str
    model: str
    seconds: float
    connection: ConnectionView


class OllamaView(BaseModel):
    base_url: str
    models: list[str]


class DefaultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: uuid.UUID | None = Field(description="None: back to the setup's model")
    model: str | None = None


class DefaultView(BaseModel):
    connection: ConnectionView | None
    model: str | None
    setup_provider: str = Field(description="What roles use when no default is set")


@models_router.get("/connections", response_model=list[ConnectionView], summary="Your models")
async def list_connections(service: ServiceDep) -> list[ConnectionView]:
    return [ConnectionView.of(c, service) for c in await service.all()]


@models_router.post("/connections", status_code=status.HTTP_201_CREATED,
                    response_model=ConnectionView, summary="Add a model connection")  # fmt: skip
async def add(body: AddConnection, service: ServiceDep) -> ConnectionView:
    return ConnectionView.of(await service.add(
        display_name=body.display_name, kind=body.kind, base_url=body.base_url,
        api_key=body.api_key, models=body.models,
    ), service)  # fmt: skip


@models_router.patch("/connections/{connection_id}", response_model=ConnectionView,
                     summary="Edit (a new key replaces the old one)")  # fmt: skip
async def edit(
    connection_id: uuid.UUID, body: EditConnection, service: ServiceDep
) -> ConnectionView:
    return ConnectionView.of(await service.update(
        connection_id, display_name=body.display_name, base_url=body.base_url,
        api_key=body.api_key, models=body.models, context_tokens=body.context_tokens,
        prices=None if body.prices is None else {
            m: None if p is None else p.model_dump() for m, p in body.prices.items()},
    ), service)  # fmt: skip


@models_router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT,
                      summary="Remove (agents using it need another model)")  # fmt: skip
async def remove(connection_id: uuid.UUID, service: ServiceDep) -> Response:
    await service.archive(connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@models_router.post("/connections/{connection_id}/test", response_model=TestView,
                    summary="Check it answers and uses tools")  # fmt: skip
async def test(connection_id: uuid.UUID, body: TestRequest, service: ServiceDep) -> TestView:
    result = await service.test(connection_id, body.model)
    connection = ConnectionView.of(await service.get(connection_id), service)
    return TestView(ok=result.ok, detail=result.detail, model=result.model,
                    seconds=round(result.seconds, 2), connection=connection)  # fmt: skip


@models_router.get("/connections/{connection_id}/models", response_model=list[str],
                   summary="The models the service says it has")  # fmt: skip
async def remote_models(connection_id: uuid.UUID, service: ServiceDep) -> list[str]:
    return await service.remote_models(connection_id)


@models_router.get("/ollama", response_model=list[OllamaView], summary="Find Ollama")
async def ollama(service: ServiceDep) -> list[OllamaView]:
    return [
        OllamaView(base_url=o.base_url, models=o.models) for o in await service.discover_ollama()
    ]


@models_router.get("/default", response_model=DefaultView, summary="The default model")
async def get_default(request: Request, service: ServiceDep) -> DefaultView:
    found = await service.default()
    setup = request.app.state.settings.model_provider
    if found is None:
        return DefaultView(connection=None, model=None, setup_provider=setup)
    return DefaultView(
        connection=ConnectionView.of(found[0], service), model=found[1], setup_provider=setup
    )


@models_router.put("/default", response_model=DefaultView, summary="Set the default model")
async def set_default(body: DefaultModel, request: Request, service: ServiceDep) -> DefaultView:
    await service.set_default(body.connection_id, body.model)
    return await get_default(request, service)
