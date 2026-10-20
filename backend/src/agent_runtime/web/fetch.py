"""Read a web page, safely (phase L6a; CR-002 R13.8).

A URL chosen by a model is a server-side request forgery risk: it could point at
Postgres, Redis, the sandbox service, the host, or cloud metadata (169.254.169.254).
The guard sits where it can't be bypassed: in the connection itself.

- `GuardedBackend` (httpcore's network backend, Decorator) resolves every host it is
  asked to connect to, refuses any address that isn't public, and connects to the
  address it checked. So redirects, DNS rebinding and odd spellings of an IP all meet
  the same check, and TLS still verifies the real host name.
- Bounded: http(s) only, no credentials in URLs, at most 5 redirects, 2 MB, 15 s.
- Readable: HTML → the main text (trafilatura), PDF → its text, plain text as is.

The text is untrusted: the ToolPipeline marks it as data before any model sees it
(R14.15).
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import re
import socket
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import anyio
import httpcore

MAX_BYTES = 2_000_000
MAX_CHARS = 20_000
TIMEOUT_S = 15.0
MAX_REDIRECTS = 5
MAX_PDF_PAGES = 30
USER_AGENT = "Nuria/0.1 (+https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime)"
READABLE = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
    "application/pdf",
    "application/json",
)


class FetchRefused(ValueError):
    """Why a page wasn't read, in plain words (the model and the person see it)."""


@dataclass(frozen=True, slots=True)
class Page:
    url: str
    final_url: str
    status: int
    content_type: str
    title: str | None
    text: str
    truncated: bool

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def public(address: str) -> bool:
    """A globally routable unicast address (not private, loopback, link-local, CGNAT,
    multicast or reserved), also through an IPv4-mapped IPv6 address."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Connects only to public addresses, after resolving the host itself.

    `allow_hosts`: host names let through even if private (tests: the fake web)."""

    def __init__(self, allow_hosts: Iterable[str] = ()) -> None:
        self._inner = httpcore.AnyIOBackend()
        self._allow = {h.lower() for h in allow_hosts if h}

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's interface)
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [str(info[4][0]) for info in infos]
        if not addresses:
            raise FetchRefused(f"{host} doesn't resolve")
        if host.lower() not in self._allow and not all(public(a) for a in addresses):
            raise FetchRefused(
                f"{host} is a private or internal address: pages there can't be read"
            )
        return await self._inner.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's interface)
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise FetchRefused("local sockets can't be read")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _check(url: str, allowlist: Iterable[str]) -> str:
    if len(url) > 2_000:
        raise FetchRefused("that address is too long")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise FetchRefused("only http and https addresses can be read")
    if not parts.hostname:
        raise FetchRefused("that isn't a web address")
    if parts.username or parts.password:
        raise FetchRefused("addresses with a user name or password can't be read")
    allowed = [d.lower().lstrip(".") for d in allowlist if d]
    host = parts.hostname.lower()
    if allowed and not any(host == d or host.endswith("." + d) for d in allowed):
        raise FetchRefused(f"{host} isn't on the list of sites agents may read")
    return parts.geturl()


async def fetch(
    url: str,
    *,
    allowlist: Iterable[str] = (),
    allow_hosts: Iterable[str] = (),
    max_chars: int = MAX_CHARS,
) -> Page:
    """The page at `url`, as readable text. Raises FetchRefused (with the reason)."""
    allowed = list(allowlist)
    current = _check(url, allowed)
    async with httpcore.AsyncConnectionPool(
        network_backend=GuardedBackend(allow_hosts), retries=0, max_connections=4
    ) as pool:
        for _ in range(MAX_REDIRECTS + 1):
            status, headers, body = await _get(pool, current)
            location = headers.get("location")
            if status in (301, 302, 303, 307, 308) and location:
                current = _check(urljoin(current, location), allowed)
                continue
            if status >= 400:
                raise FetchRefused(f"the site answered {status}")
            content_type = headers.get("content-type", "").split(";")[0].strip().lower()
            text, title = await asyncio.to_thread(_readable, body, content_type, headers)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            return Page(
                url, current, status, content_type, title, text[:max_chars], len(text) > max_chars
            )
    raise FetchRefused(f"more than {MAX_REDIRECTS} redirects")


async def _get(pool: httpcore.AsyncConnectionPool, url: str) -> tuple[int, dict[str, str], bytes]:
    timeouts = {"connect": 5.0, "read": TIMEOUT_S, "write": 5.0, "pool": 5.0}
    headers = [
        (b"User-Agent", USER_AGENT.encode()),
        (b"Accept", b"text/html,application/xhtml+xml,text/plain,application/pdf;q=0.9,*/*;q=0.1"),
    ]
    try:
        with anyio.fail_after(TIMEOUT_S + 5):
            async with pool.stream(
                "GET", url, headers=headers, extensions={"timeout": timeouts}
            ) as response:
                found = {
                    k.decode("latin-1").lower(): v.decode("latin-1") for k, v in response.headers
                }
                body = bytearray()
                if response.status < 300 or response.status >= 400:
                    async for chunk in response.aiter_stream():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break  # read what fits: the text is capped anyway
                return response.status, found, bytes(body[:MAX_BYTES])
    except FetchRefused:
        raise
    except TimeoutError as exc:
        raise FetchRefused("the site didn't answer in time") from exc
    except httpcore.ConnectError as exc:
        if isinstance(exc.__context__, FetchRefused):
            raise exc.__context__ from exc
        raise FetchRefused("couldn't reach the site") from exc
    except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError) as exc:
        raise FetchRefused("couldn't read the site") from exc


def _readable(body: bytes, content_type: str, headers: dict[str, str]) -> tuple[str, str | None]:
    if content_type and content_type not in READABLE:
        raise FetchRefused(f"this kind of file ({content_type}) can't be read as text")
    if content_type == "application/pdf" or body[:5] == b"%PDF-":
        return _pdf(body), None
    text = _decode(body, headers.get("content-type", ""))
    if content_type in ("text/html", "application/xhtml+xml") or "<html" in text[:2000].lower():
        return _html(text)
    return text, None


def _decode(body: bytes, content_type: str) -> str:
    found = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    for encoding in ([found.group(1)] if found else []) + ["utf-8", "latin-1"]:
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _html(html: str) -> tuple[str, str | None]:
    import trafilatura

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = " ".join(title_match.group(1).split())[:200] if title_match else None
    text = (
        trafilatura.extract(html, include_comments=False, include_tables=True, favor_recall=True)
        or ""
    )
    if not text:  # a page with little "main" text: fall back to all visible text
        stripped = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", stripped)).strip()
    return text, title


def _pdf(body: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(body))
        pages = [p.extract_text() or "" for p in reader.pages[:MAX_PDF_PAGES]]
    except Exception as exc:  # pypdf raises many types on a broken file
        raise FetchRefused("the PDF couldn't be read") from exc
    return "\n\n".join(pages)
