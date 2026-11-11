"""SearXNG's answers, read honestly: no results while its engines refused it isn't
"nothing on the web", and the model is told so."""

from typing import Any

import pytest

from agent_runtime.web import search
from agent_runtime.web.search import SearxngProvider
from agent_runtime.web.tools import unanswered_note

BLOCKED = [["brave", "Suspended: too many requests"], ["duckduckgo", "CAPTCHA"]]
ROW = {"title": "Redis Streams", "url": "https://redis.io/docs/streams/", "content": "Logs."}


def answering(body: dict[str, Any]) -> Any:
    async def fake(method: str, url: str, **kw: Any) -> dict[str, Any]:
        return body

    return fake


async def test_no_results_while_engines_refused_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        search, "_request", answering({"results": [], "unresponsive_engines": BLOCKED})
    )
    hits = await SearxngProvider("http://searxng:8080").search("Redis Streams", 5)
    assert hits == [] and hits.unanswered == ("brave", "duckduckgo")
    note = unanswered_note(hits)
    assert note is not None and "2 search engine(s) didn't answer (brave, duckduckgo)" in note
    assert "doesn't mean nothing is out there" in note


async def test_results_from_the_engines_that_answered_are_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search, "_request", answering({"results": [ROW], "unresponsive_engines": BLOCKED})
    )
    hits = await SearxngProvider("http://searxng:8080").search("Redis Streams", 5)
    assert [h.url for h in hits] == [ROW["url"]]
    assert unanswered_note(hits) is None  # results: nothing to explain


async def test_nothing_found_by_engines_that_answered_is_just_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search, "_request", answering({"results": [], "unresponsive_engines": []}))
    hits = await SearxngProvider("http://searxng:8080").search("qzxv", 5)
    assert hits == [] and unanswered_note(hits) is None


async def test_the_settings_test_names_the_engines_that_didnt_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Settings → Tools said "answered, but with no results" while every engine refused it.
    from agent_runtime.web.settings import ToolSettings

    monkeypatch.setattr(
        search, "_request", answering({"results": [], "unresponsive_engines": BLOCKED})
    )
    settings = object.__new__(ToolSettings)

    async def provider() -> SearxngProvider:
        return SearxngProvider("http://searxng:8080")

    monkeypatch.setattr(settings, "provider", provider)
    ok, message, hits = await settings.test()
    assert (ok, hits) == (False, [])
    assert message.startswith("No results: brave, duckduckgo didn't answer")
