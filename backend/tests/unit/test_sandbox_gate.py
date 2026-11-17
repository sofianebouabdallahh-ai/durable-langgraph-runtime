"""sandbox-gate (H9): what sandboxd sends passes, and what a sandboxd taken over would
try is refused (a privileged container, the host's disk, its network, another image,
someone else's container), before Docker sees it."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from collections.abc import MutableMapping
from typing import Any

import httpx
import pytest

from agent_runtime.sandbox import docker as dock
from agent_runtime.sandbox.backend import Isolation, Limits
from agent_runtime.sandbox.gate import Refused, Rules, create_app

IMAGE = "nuria-sandbox:1.0"
RUN = str(uuid.uuid4())
OURS, THEIRS = "c-sandbox", "c-postgres"


class Daemon:
    """Docker behind the gate: records what reached it."""

    def __init__(self) -> None:
        self.reached: list[tuple[str, str, Any]] = []
        self.created: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/v1.44")
        self.reached.append((request.method, path, body))
        if path == "/version":
            return httpx.Response(200, json={"ApiVersion": "1.52", "MinAPIVersion": "1.44"})
        if path == "/containers/create":
            self.created.append(body)
            return httpx.Response(201, json={"Id": OURS})
        for name, labels in ((OURS, {"nuria.sandbox": "1"}), (THEIRS, {})):
            if path == f"/containers/{name}/json":
                return httpx.Response(200, json={"Config": {"Labels": labels}})
            if path == f"/exec/e-{name}/json":
                return httpx.Response(200, json={"ContainerID": name, "ExitCode": 0})
        if path.endswith("/exec") and request.method == "POST":
            return httpx.Response(201, json={"Id": "e-c-sandbox"})
        if path.endswith("/start") and path.startswith("/exec/"):
            return httpx.Response(200, content=b"\x01\x00\x00\x00\x00\x00\x00\x02ok")
        if path == "/containers/json":
            return httpx.Response(200, json=[])
        if path == "/info":
            return httpx.Response(200, json={"Runtimes": {"runc": {}, "runsc": {}}})
        if path == "/_ping":
            return httpx.Response(200, text="OK")
        return httpx.Response(204)


class Streaming(httpx.AsyncBaseTransport):
    """Like the socket, its responses are streams (MockTransport reads them first)."""

    def __init__(self, daemon: Daemon) -> None:
        self.daemon = daemon

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        r = self.daemon.handle(request)
        return httpx.Response(r.status_code, headers=r.headers, stream=httpx.ByteStream(r.content))


def gate(daemon: Daemon, gvisor_only: bool = False) -> httpx.AsyncBaseTransport:
    rules = Rules(IMAGE, Limits(), "runsc", gvisor_only)
    return httpx.ASGITransport(app=create_app(Streaming(daemon), rules))


async def sent_by_sandboxd(isolation: Isolation) -> dict[str, Any]:
    """The create body the real Docker adapter sends (the contract the gate checks)."""
    daemon = Daemon()
    adapter = dock.Docker(transport=httpx.MockTransport(daemon.handle))
    await adapter.create(RUN, 1, IMAGE, Limits(), isolation)
    await adapter.close()
    return daemon.created[0]


@pytest.mark.parametrize("isolation", ["container", "gvisor"])
async def test_sandboxd_works_through_the_gate(isolation: Isolation) -> None:
    daemon = Daemon()
    adapter = dock.Docker(transport=gate(daemon), runtime="runsc")
    assert await adapter.ping() and await adapter.supports("gvisor")
    assert await adapter.create(RUN, 1, IMAGE, Limits(), isolation) == OURS
    done = await adapter.exec(OURS, ["python", "-c", "print(1)"], 10, processes=64)
    assert done == {**done, "stdout": "ok", "exit_code": 0}
    assert await adapter.sandboxes() == []  # the listing went through, filtered
    await adapter.remove(OURS)
    assert ("DELETE", f"/containers/{OURS}", None) in daemon.reached
    await adapter.close()


def refused(rules: Rules, body: dict[str, Any], name: str = "") -> str:
    with pytest.raises(Refused) as why:
        rules.create(name or f"nuria-sbx-{RUN[:8]}-1-1700000000", body)
    return str(why.value)


def changed(body: dict[str, Any], **host: Any) -> dict[str, Any]:
    out = copy.deepcopy(body)
    out["HostConfig"].update(host)
    return out


async def test_a_create_that_isnt_our_sandbox_is_refused() -> None:
    body = await sent_by_sandboxd("container")
    rules = Rules(IMAGE, Limits(), "runsc", gvisor_only=False)
    rules.create(f"nuria-sbx-{RUN[:8]}-1-1700000000", body)  # the real one passes
    attempts = {
        "privileged": changed(body, Privileged=True),
        "the host's disk": changed(body, Binds=["/:/host"]),
        "a mount": changed(body, Mounts=[{"Type": "bind", "Source": "/", "Target": "/h"}]),
        "a device": changed(body, Devices=[{"PathOnHost": "/dev/kvm"}]),
        "a capability": changed(body, CapAdd=["SYS_ADMIN"]),
        "the host's network": changed(body, NetworkMode="host"),
        "the host's processes": changed(body, PidMode="host"),
        "no seccomp": changed(body, SecurityOpt=["seccomp=unconfined"]),
        "a writable system": changed(body, ReadonlyRootfs=False),
        "more memory": changed(body, Memory=8 * 2**30, MemorySwap=8 * 2**30),
        "swap": changed(body, MemorySwap=-1),
        "more CPUs": changed(body, NanoCpus=8 * 10**9),
        "no process limit": changed(body, PidsLimit=-1),
        "another runtime": changed(body, Runtime="runc-unsafe"),
        "an executable /tmp": changed(body, Tmpfs={"/workspace": "size=64m", "/tmp": "exec"}),
        "another tmpfs": changed(body, Tmpfs={"/workspace": "", "/tmp": "", "/etc": ""}),
        "another image": {**body, "Image": "alpine"},
        "root": {**body, "User": "0"},
        "a network": {**body, "NetworkDisabled": False},
        "a secret": {**body, "Env": ["POSTGRES_PASSWORD=x"]},
        "an unknown field": {**body, "Volumes": {"/x": {}}},
        "no label": {**body, "Labels": {}},
    }
    for what, attempt in attempts.items():
        assert refused(rules, attempt), what
    assert "name" in refused(rules, body, name="postgres")


async def test_with_gvisor_required_only_gvisor_sandboxes_are_created() -> None:
    rules = Rules(IMAGE, Limits(), "runsc", gvisor_only=True)
    rules.create(f"nuria-sbx-{RUN[:8]}-1-1", await sent_by_sandboxd("gvisor"))
    assert "gVisor is required" in refused(rules, await sent_by_sandboxd("container"))
    gvisor = await sent_by_sandboxd("gvisor")
    assert "processes" in refused(rules, changed(gvisor, PidsLimit=10_000))


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", f"/containers/{THEIRS}/exec", {"Cmd": ["sh"], "User": "10002", "Tty": False}),
        ("POST", f"/containers/{OURS}/exec", {"Cmd": ["sh"], "User": "0", "Tty": False}),
        ("POST", f"/containers/{OURS}/exec",
         {"Cmd": ["sh"], "User": "10002", "Tty": False, "Privileged": True}),
        ("POST", f"/containers/{THEIRS}/start", None),
        ("DELETE", f"/containers/{THEIRS}", None),
        ("POST", f"/exec/e-{THEIRS}/start", {"Detach": False, "Tty": False}),
        ("GET", f"/containers/{THEIRS}/json", None),
        ("GET", "/containers/json", None),  # unfiltered: every container on the host
        ("POST", "/images/create", None),
        ("POST", "/build", None),
        ("PUT", f"/containers/{OURS}/archive", None),
        ("GET", f"/containers/{THEIRS}/logs", None),
        ("POST", "/volumes/create", None),
        ("POST", "/networks/create", None),
        ("GET", "/../../containers/json", None),
    ],
)  # fmt: skip
async def test_anything_else_never_reaches_docker(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    daemon = Daemon()
    async with httpx.AsyncClient(transport=gate(daemon), base_url="http://gate") as c:
        r = await c.request(method, f"/v1.44{path}", json=body)
    assert r.status_code == 403 and r.json()["message"].startswith("sandbox-gate:")
    assert all(m == "GET" and p.endswith("/json") for m, p, _ in daemon.reached)  # lookups only


async def test_a_request_without_a_host_header_is_judged_by_its_path() -> None:
    """The health check speaks HTTP/1.0 on the socket, with no Host header."""
    daemon = Daemon()
    app = create_app(Streaming(daemon), Rules(IMAGE, Limits(), "runsc", False))
    sent: list[Any] = []
    scope = {"type": "http", "method": "GET", "path": "/_ping", "raw_path": b"/_ping",
             "query_string": b"", "headers": [], "http_version": "1.0",
             "server": ("/run/sandbox-gate/docker.sock", None)}  # fmt: skip

    done, asked = asyncio.Event(), []

    async def receive() -> dict[str, Any]:
        asked.append(1)
        if len(asked) == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await done.wait()  # then the client goes, once the answer is in
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body"):
            done.set()

    await app(scope, receive, send)
    assert sent[0]["status"] == 200 and ("GET", "/_ping", None) in daemon.reached
