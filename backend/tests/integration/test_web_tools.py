"""The web tools in real turns (L6a; SC1, SC3, SC4): search, read, cite; settings; safety.

A fake web (the fake model server: a SearXNG lookalike, Tavily and Brave lookalikes,
and a few pages) stands in for the internet. It runs on 127.0.0.1, which the page
reader refuses like any internal address, so these tests let that one host through,
as the test stack does.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.devtools.fake_model import create_app as fake_server
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.web import tools as web_tools
from agent_runtime.web.search import BraveProvider, SearchUnavailable, TavilyProvider
from tests.integration.test_models import Seen, api, bus, run
from tests.integration.test_stream import Server

pytestmark = pytest.mark.integration
__all__ = ["api", "bus"]  # fixtures, imported for pytest
SEARCH_KEY = "fake-search-key"


@pytest.fixture
async def web(test_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """The fake web on a free port; the web tools allowed to read from it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(fake_server(base_url=base), port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    settings = test_settings.model_copy(
        update={"fetch_allow_hosts": "127.0.0.1", "searxng_url": f"{base}/searxng"}
    )
    monkeypatch.setattr(web_tools, "get_settings", lambda: settings)
    web_tools._services.clear()
    yield base
    web_tools._services.clear()
    server.should_exit = True
    await task


@pytest.fixture
async def defaults(api: Server) -> AsyncIterator[None]:
    """Search back to the stack's SearXNG after each test (the database is shared)."""
    yield
    await api.client.put(
        "/tools/settings",
        json={"search_provider": "searxng", "searxng_url": "", "web_allowlist": []},
    )


async def model(c: Seen, web: str) -> dict[str, Any]:
    """A model connection to the fake model on the same server, made the default."""
    added = await c(
        "POST",
        "/models/connections",
        json={
            "display_name": f"Web {uuid.uuid4().hex[:6]}",
            "kind": "compatible",
            "base_url": f"{web}/v1",
            "models": ["fake-a"],
        },
    )
    connection: dict[str, Any] = added.json()
    await c("POST", f"/models/connections/{connection['id']}/test", json={"model": "fake-a"})
    return connection


async def agent(c: Seen, connection: dict[str, Any], tools: list[str]) -> dict[str, Any]:
    created = (
        await c("POST", "/studio/agents", json={"display_name": f"Web {uuid.uuid4().hex[:6]}"})
    ).json()
    doc = created["draft"]["document"] | {
        "description": "Researches.",
        "instructions": "Research, then answer with sources.",
        "model": f"{connection['name']}:fake-a",
        "tools": [{"name": t} for t in tools],
    }
    saved = (await c("PUT", f"/studio/agents/{created['id']}/draft", json=doc)).json()
    assert saved["draft"]["issues"] == [], saved["draft"]["issues"]
    result: dict[str, Any] = created
    return result


async def test_an_agent_searches_reads_and_cites(
    api: Server, web: str, pool: Pool, test_settings: Settings, defaults: None
) -> None:
    c = Seen(api.client)
    await c("PUT", "/tools/settings", json={"searxng_url": f"{web}/searxng"})
    tested = (await c("POST", "/tools/search/test", json={"query": "naxos"})).json()
    assert tested["ok"] and tested["results"][0]["url"] == f"{web}/web/naxos-ferries"

    researcher = await agent(c, await model(c, web), ["web_search", "read_webpage"])
    chat = (await c("POST", f"/studio/agents/{researcher['id']}/test-chat")).json()
    sent = (
        await c("POST", f"/sessions/{chat['id']}/messages", json={"content": "ferries to naxos"})
    ).json()
    done = await run(pool, test_settings, sent["run_id"])
    assert done.status is S.COMPLETED, done.reason

    msgs = (await c("GET", f"/sessions/{chat['id']}/messages")).json()["messages"]
    results = {m["content"]["tool"]: m["content"] for m in msgs if m["type"] == "tool_result"}
    assert results["web_search"]["result"]["source"] == "searxng"
    page = results["read_webpage"]["result"]
    assert page["title"] == "Ferries to Naxos" and "07:25" in page["text"]
    assert msgs[-1]["content"]["text"].endswith("Read: Ferries to Naxos.")


async def test_internal_addresses_are_refused_in_a_turn(
    api: Server, web: str, pool: Pool, test_settings: Settings
) -> None:
    """SC3: a model asking for an internal address gets a plain refusal, not the page."""
    from agent_runtime.tools.spec import ToolContext

    ctx = ToolContext(run_id=uuid.uuid4(), epoch=1, key="k", pool=pool)
    for url in (
        "http://169.254.169.254/latest/meta-data",
        "http://postgres:5432/",
        "http://localhost:8000/healthz",
        "http://[::1]/",
    ):
        with pytest.raises(web_tools.WebToolError, match="Couldn't read"):
            await web_tools.read_webpage(web_tools.ReadArgs(url=url), ctx)


async def test_keys_and_providers(api: Server, web: str, defaults: None) -> None:
    c = Seen(api.client)
    refused = await c("PUT", "/tools/settings", json={"search_provider": "tavily"})
    assert refused.status_code == 422 and "needs an API key" in refused.text
    saved = (
        await c("PUT", "/tools/settings", json={"search_provider": "brave", "api_key": SEARCH_KEY})
    ).json()
    assert saved["has_key"] and saved["key_fingerprint"] and saved["search_provider"] == "brave"
    assert all(SEARCH_KEY not in body for body in c.bodies)  # never returned

    hits = await TavilyProvider(SEARCH_KEY, base_url=f"{web}/tavily").search("naxos", 2)
    assert [h.url for h in hits] == [f"{web}/web/naxos-ferries", f"{web}/web/naxos-beaches"]
    brave = await BraveProvider(SEARCH_KEY, base_url=f"{web}/brave").search("naxos", 1)
    assert brave[0].title == "Ferries to Naxos"
    with pytest.raises(SearchUnavailable, match="refused the key"):
        await TavilyProvider("wrong", base_url=f"{web}/tavily").search("naxos", 2)


async def test_the_allowlist_limits_pages(
    api: Server, web: str, pool: Pool, defaults: None
) -> None:
    from agent_runtime.tools.spec import ToolContext

    await api.client.put("/tools/settings", json={"web_allowlist": ["wikipedia.org"]})
    ctx = ToolContext(run_id=uuid.uuid4(), epoch=1, key="k", pool=pool)
    with pytest.raises(web_tools.WebToolError, match="isn't on the list"):
        await web_tools.read_webpage(web_tools.ReadArgs(url=f"{web}/web/naxos-ferries"), ctx)


async def test_planted_instructions_in_a_page_arrive_as_data(
    api: Server, web: str, pool: Pool, test_settings: Settings, defaults: None
) -> None:
    """SC4: a page that says "call notify" is read as data; the turn has no notify, and the
    page's text reaches the model inside <data> it can't close."""
    c = Seen(api.client)
    await c("PUT", "/tools/settings", json={"searxng_url": f"{web}/searxng"})
    researcher = await agent(c, await model(c, web), ["web_search", "read_webpage"])
    chat = (await c("POST", f"/studio/agents/{researcher['id']}/test-chat")).json()
    sent = (
        await c("POST", f"/sessions/{chat['id']}/messages", json={"content": "travel tips"})
    ).json()
    assert (await run(pool, test_settings, sent["run_id"])).status is S.COMPLETED
    msgs = (await c("GET", f"/sessions/{chat['id']}/messages")).json()["messages"]
    assert [m["content"]["tool"] for m in msgs if m["type"] == "tool_call"] == [
        "web_search",
        "read_webpage",
    ]
    async with httpx.AsyncClient() as client:
        served = (await client.get(f"{web}/calls")).json()
    assert all("notify" not in call["tools"] for call in served)


async def test_an_always_used_skill_reaches_the_model_and_its_reasoning_the_download(
    api: Server, web: str, pool: Pool, test_settings: Settings
) -> None:
    """L6: "Always use" puts the skill's instructions in the prompt, inside <data>; a
    reasoning model's thinking is kept with the reply and in the Markdown download."""
    c = Seen(api.client)
    connection = await model(c, web)
    created = (await c("POST", "/studio/agents", json={"display_name": "Packer"})).json()
    doc = created["draft"]["document"] | {
        "description": "Plans trips.", "instructions": "Help plan trips.",
        "model": f"{connection['name']}:fake-a",
        "skills": ["trip-planning"], "always_skills": ["trip-planning"],
    }  # fmt: skip
    saved = (await c("PUT", f"/studio/agents/{created['id']}/draft", json=doc)).json()
    assert saved["draft"]["issues"] == [], saved["draft"]["issues"]
    chat = (await c("POST", f"/studio/agents/{created['id']}/test-chat")).json()
    async with httpx.AsyncClient() as client:
        await client.delete(f"{web}/calls")
    sent = (await c("POST", f"/sessions/{chat['id']}/messages", json={"content": "hello"})).json()
    assert (await run(pool, test_settings, sent["run_id"])).status is S.COMPLETED

    async with httpx.AsyncClient() as client:
        (served, *_) = (await client.get(f"{web}/calls")).json()
    always = served["system"].index("## Know-how you always use")
    assert served["system"].index("## Data") < always  # last, where a small model follows it
    assert "### trip-planning\n" in served["system"][always:]  # its scan is clean: plain guidance
    assert '<data source="skill:trip-planning">' not in served["system"]
    assert "load_skill" in served["tools"]  # its files stay readable

    msgs = (await c("GET", f"/sessions/{chat['id']}/messages")).json()["messages"]
    reply = next(m for m in msgs if m["type"] == "assistant")["content"]
    assert reply["reasoning"].startswith("Thinking:")
    md = (await c("GET", f"/sessions/{chat['id']}/export")).text
    assert "> 💭 **Reasoning**" in md and "> Thinking:" in md
    assert md.index("> 💭 **Reasoning**") < md.index(reply["text"].split("\n")[0])
