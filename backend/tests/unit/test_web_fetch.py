"""Reading pages, safely (L6a, SC3): private addresses refused everywhere, pages readable.

A small local web server stands in for the web. It's on 127.0.0.1, which the guard
refuses like any internal address, so the tests that read from it say so explicitly
(`allow_hosts`), exactly as the test stack lets the fake web through.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from agent_runtime.web import fetch as web
from agent_runtime.web.fetch import FetchRefused, fetch, public

ARTICLE = """<html><head><title>Ferries to Naxos</title><script>var x = 1;</script></head>
<body><nav>Home | About</nav><article><h1>Ferries to Naxos</h1>
<p>The morning ferry from Piraeus leaves at 07:25 and arrives at 13:10.</p>
<p>Book a day ahead in August: the boats fill up quickly in high season.</p>
</article><footer>Contact us</footer></body></html>"""


def _pdf(text: str) -> bytes:
    """A valid one-page PDF showing `text` (built by hand: no PDF library needed)."""
    stream = f"BT /F1 12 Tf 20 50 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj" % n + body + b"endobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref)
    return bytes(out)


PDF = _pdf("Hello PDF")


async def article(_: Request) -> Response:
    return Response(ARTICLE, media_type="text/html; charset=utf-8")


async def slow(_: Request) -> Response:
    await asyncio.sleep(5)
    return PlainTextResponse("late")


ROUTES = [
    Route("/article", article),
    Route("/plain", lambda _: PlainTextResponse("just text")),
    Route("/pdf", lambda _: Response(PDF, media_type="application/pdf")),
    Route("/image", lambda _: Response(b"\x89PNG", media_type="image/png")),
    Route("/missing", lambda _: PlainTextResponse("no", status_code=404)),
    Route("/big", lambda _: PlainTextResponse("x" * 3_000_000)),
    Route("/slow", slow),
    Route("/to-metadata", lambda _: RedirectResponse("http://169.254.169.254/latest/meta-data")),
    Route("/to-article", lambda _: RedirectResponse("/article")),
    Route("/loop", lambda _: RedirectResponse("/loop")),
]


@pytest.fixture
async def site() -> AsyncIterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(Starlette(routes=ROUTES), port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


LOCAL = ("127.0.0.1",)


@pytest.mark.parametrize(
    ("address", "ok"),
    [
        ("8.8.8.8", True),
        ("2001:4860:4860::8888", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("172.18.0.5", False),  # a Docker network: Postgres, Redis, sandboxd live there
        ("192.168.1.1", False),
        ("169.254.169.254", False),  # cloud metadata
        ("100.64.0.1", False),  # carrier-grade NAT
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fe80::1", False),
        ("::ffff:127.0.0.1", False),  # IPv4-mapped loopback
        ("64:ff9b::a9fe:a9fe", False),  # NAT64 (RFC 6052) form of cloud metadata (H10)
        ("64:ff9b:1::a9fe:a9fe", False),  # the same behind RFC 8215's local-use prefix
        ("64:ff9b::808:808", True),  # NAT64 form of 8.8.8.8: public, as 8.8.8.8 is
    ],
)
def test_only_public_addresses_pass(address: str, ok: bool) -> None:
    assert public(address) is ok


async def test_private_addresses_are_refused_however_they_are_spelled(site: str) -> None:
    port = site.rsplit(":", 1)[1]
    for url in (f"{site}/article", f"http://localhost:{port}/article", f"http://[::1]:{port}/x"):
        with pytest.raises(FetchRefused, match=r"private or internal|couldn't reach"):
            await fetch(url)


async def test_a_page_reads_as_its_main_text(site: str) -> None:
    page = await fetch(f"{site}/article", allow_hosts=LOCAL)
    assert page.title == "Ferries to Naxos" and page.status == 200
    assert "07:25" in page.text and "var x" not in page.text
    plain = await fetch(f"{site}/plain", allow_hosts=LOCAL)
    assert plain.text == "just text" and plain.content_type == "text/plain"
    pdf = await fetch(f"{site}/pdf", allow_hosts=LOCAL)
    assert "Hello PDF" in pdf.text


async def test_redirects_are_followed_and_checked_again(site: str) -> None:
    followed = await fetch(f"{site}/to-article", allow_hosts=LOCAL)
    assert followed.final_url.endswith("/article") and "07:25" in followed.text
    with pytest.raises(FetchRefused, match="private or internal"):
        await fetch(f"{site}/to-metadata", allow_hosts=LOCAL)
    with pytest.raises(FetchRefused, match="redirects"):
        await fetch(f"{site}/loop", allow_hosts=LOCAL)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///etc/passwd", "only http and https"),
        ("ftp://example.com/x", "only http and https"),
        ("http://user:secret@example.com/", "user name or password"),
        ("http:///nohost", "isn't a web address"),
        ("https://example.com/" + "a" * 2100, "too long"),
    ],
)
async def test_bad_addresses_are_refused_before_any_connection(url: str, reason: str) -> None:
    with pytest.raises(FetchRefused, match=reason):
        await fetch(url)


async def test_the_allowlist_limits_which_sites(site: str) -> None:
    with pytest.raises(FetchRefused, match="isn't on the list"):
        await fetch("https://example.com/", allowlist=["wikipedia.org"])
    page = await fetch(f"{site}/plain", allow_hosts=LOCAL, allowlist=["127.0.0.1"])
    assert page.text == "just text"


async def test_size_time_and_kind_are_bounded(site: str, monkeypatch: pytest.MonkeyPatch) -> None:
    big = await fetch(f"{site}/big", allow_hosts=LOCAL)
    assert big.truncated and len(big.text) == web.MAX_CHARS
    with pytest.raises(FetchRefused, match="can't be read as text"):
        await fetch(f"{site}/image", allow_hosts=LOCAL)
    with pytest.raises(FetchRefused, match="answered 404"):
        await fetch(f"{site}/missing", allow_hosts=LOCAL)
    monkeypatch.setattr(web, "TIMEOUT_S", 0.5)
    with pytest.raises(FetchRefused, match=r"in time|couldn't read"):
        await fetch(f"{site}/slow", allow_hosts=LOCAL)


async def test_a_host_that_doesnt_exist_is_a_plain_refusal() -> None:
    with pytest.raises(FetchRefused, match="can't be found"):
        await fetch("http://no-such-host.invalid/")
