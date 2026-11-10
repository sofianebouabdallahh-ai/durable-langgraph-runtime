"""SearXNG's answers, read honestly: no results because its engines refused it is search
not working, not "nothing on the web"."""

from typing import Any

import pytest

from agent_runtime.web import search
from agent_runtime.web.search import SearchUnavailable, SearxngProvider

BLOCKED = [["brave", "Suspended: too many requests"], ["duckduckgo", "CAPTCHA"]]
ROW = {"title": "Redis Streams", "url": "https://redis.io/docs/streams/", "content": "Logs."}


def answering(body: dict[str, Any]) -> Any:
    async def fake(method: str, url: str, **kw: Any) -> dict[str, Any]:
        return body

    return fake


async def test_no_results_because_every_engine_refused_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search, "_request", answering({"results": [], "unresponsive_engines": BLOCKED})
    )
    with pytest.raises(SearchUnavailable, match="didn't answer"):
        await SearxngProvider("http://searxng:8080").search("Redis Streams", 5)


async def test_results_from_the_engines_that_answered_are_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search, "_request", answering({"results": [ROW], "unresponsive_engines": BLOCKED})
    )
    hits = await SearxngProvider("http://searxng:8080").search("Redis Streams", 5)
    assert [h.url for h in hits] == [ROW["url"]]


async def test_nothing_found_by_engines_that_answered_is_just_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search, "_request", answering({"results": [], "unresponsive_engines": []}))
    assert await SearxngProvider("http://searxng:8080").search("qzxv", 5) == []
