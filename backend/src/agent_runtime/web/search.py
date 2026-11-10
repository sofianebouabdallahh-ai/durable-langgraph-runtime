"""Web search (phase L6a): one port, three adapters (Ports & Adapters, Strategy).

- **SearXNG** (the default): a metasearch engine running in the stack, private, no key.
- **Tavily**, **Brave**: hosted search APIs, with a key saved in Settings → Tools.

Each returns the same `Hit`s (title, url, snippet), so agents and the UI don't care
which one answered. Failures become `SearchUnavailable` with a plain reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

import httpx

Provider = Literal["searxng", "tavily", "brave"]
TIMEOUT_S = 15.0


class SearchUnavailable(Exception):
    """Search didn't work; the message says why in plain words."""


@dataclass(frozen=True, slots=True)
class Hit:
    title: str
    url: str
    snippet: str

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


class Hits(list[Hit]):
    """A search's hits, and the engines that didn't answer it (SearXNG's)."""

    unanswered: tuple[str, ...] = ()


class SearchProvider(Protocol):
    @property
    def name(self) -> Provider: ...

    async def search(self, query: str, k: int) -> list[Hit]: ...


def _hits(rows: list[dict[str, Any]], snippet: str, k: int) -> list[Hit]:
    out: list[Hit] = []
    for row in rows:
        url = str(row.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        text = " ".join(str(row.get(snippet) or "").split())
        out.append(Hit(" ".join(str(row.get("title") or url).split())[:200], url, text[:500]))
        if len(out) == k:
            break
    return out


async def _request(method: str, url: str, **kw: Any) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, trust_env=False) as client:
            response = await client.request(method, url, **kw)
    except httpx.TimeoutException as exc:
        raise SearchUnavailable("the search service didn't answer in time") from exc
    except httpx.HTTPError as exc:
        raise SearchUnavailable("couldn't reach the search service") from exc
    if response.status_code in (401, 403):
        raise SearchUnavailable("the search service refused the key (Settings → Tools)")
    if response.status_code == 429:
        raise SearchUnavailable("the search service says too many searches: try again shortly")
    if response.status_code >= 400:
        raise SearchUnavailable(f"the search service answered {response.status_code}")
    try:
        body: dict[str, Any] = response.json()
    except ValueError as exc:
        raise SearchUnavailable("the search service didn't answer with results") from exc
    return body


@dataclass(frozen=True)
class SearxngProvider:
    base_url: str
    name: Provider = "searxng"

    async def search(self, query: str, k: int) -> Hits:
        body = await _request(
            "GET",
            self.base_url.rstrip("/") + "/search",
            params={"q": query, "format": "json", "safesearch": 1},
        )
        # SearXNG answers 200 with no results when the engines it asks refuse it (rate
        # limits, CAPTCHAs): kept, so "nothing found" isn't read as "nothing on the web".
        hits = Hits(_hits(list(body.get("results") or []), "content", k))
        hits.unanswered = tuple(
            str(e[0]) for e in body.get("unresponsive_engines") or [] if isinstance(e, list) and e
        )
        return hits


@dataclass(frozen=True)
class TavilyProvider:
    key: str
    base_url: str = "https://api.tavily.com"
    name: Provider = "tavily"

    async def search(self, query: str, k: int) -> list[Hit]:
        body = await _request(
            "POST",
            self.base_url.rstrip("/") + "/search",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"query": query, "max_results": k, "search_depth": "basic"},
        )
        return _hits(list(body.get("results") or []), "content", k)


@dataclass(frozen=True)
class BraveProvider:
    key: str
    base_url: str = "https://api.search.brave.com"
    name: Provider = "brave"

    async def search(self, query: str, k: int) -> list[Hit]:
        body = await _request(
            "GET",
            self.base_url.rstrip("/") + "/res/v1/web/search",
            headers={"X-Subscription-Token": self.key, "Accept": "application/json"},
            params={"q": query, "count": k},
        )
        return _hits(list((body.get("web") or {}).get("results") or []), "description", k)
