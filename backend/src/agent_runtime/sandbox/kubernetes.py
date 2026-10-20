"""Sandboxes as Pods (Adapter; Kubernetes, L6c): no Docker socket anywhere.

sandboxd's own ServiceAccount may create, list, delete and exec into Pods in one
namespace, the sandboxes' (a Role there, nothing else). Each sandbox is a Pod built to
pass the restricted Pod Security Standard, with no service account token, no service
links and, from the namespace's NetworkPolicy, no network at all. A Pod's name is the
run and epoch, so two sandboxd replicas asking at once get the same Pod.

Commands run through the exec API's WebSocket (channel protocol v4: 0 stdin, 1 stdout,
2 stderr, 3 the exit status). The argv travels on stdin, not in the URL (code and file
contents can be large): a one-line launcher in the sandbox reads it and execs it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Subprotocol

from agent_runtime.sandbox.backend import (
    ENV,
    LABEL,
    USER_ID,
    Limits,
    Output,
    Sandbox,
    killed_after,
    labels,
    result,
)

ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
CONTAINER = "sandbox"
START_TIMEOUT_S = 120  # the first start on a node pulls the image
# Reads the argv (one JSON line), gives the command an empty stdin, becomes the command.
LAUNCHER = (
    "import json,os,sys;a=json.loads(sys.stdin.buffer.readline());"
    "os.dup2(os.open(os.devnull,os.O_RDONLY),0);os.execvp(a[0],a)"
)
# The image can't be pulled or started: waiting longer won't help.
STUCK = {"ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError"}


class SandboxStartFailed(RuntimeError):
    pass


class Kubernetes:
    def __init__(
        self,
        namespace: str | None = None,
        *,
        runtime_class: str | None = None,
        pull_policy: str = "IfNotPresent",
        user_namespaces: bool = False,
        account: Path = ACCOUNT,
    ) -> None:
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self._api = f"https://{host}:{port}" if ":" not in host else f"https://[{host}]:{port}"
        self._token_file = account / "token"
        self._ssl = ssl.create_default_context(cafile=str(account / "ca.crt"))
        self.namespace = namespace or (account / "namespace").read_text().strip()
        self._runtime_class = runtime_class
        self._pull_policy = pull_policy
        self._user_namespaces = user_namespaces
        self._client = httpx.AsyncClient(
            base_url=self._api, verify=self._ssl, timeout=30.0, trust_env=False
        )

    def _headers(self) -> dict[str, str]:
        # Read every time: the kubelet rotates the projected token.
        return {"Authorization": f"Bearer {self._token_file.read_text().strip()}"}

    def _pods(self, name: str = "") -> str:
        return f"/api/v1/namespaces/{self.namespace}/pods" + (f"/{name}" if name else "")

    async def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        response = await self._client.request(method, path, headers=self._headers(), **kw)
        if response.status_code >= 400 and response.status_code not in (404, 409):
            raise RuntimeError(
                f"kubernetes {method} {path}: {response.status_code} {response.text[:300]}"
            )
        return response

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        return (await self._call("GET", self._pods(), params={"limit": 1})).status_code == 200

    async def sandboxes(self, run: str | None = None) -> list[Sandbox]:
        selector = f"{LABEL}=1" + (f",{LABEL}.run={run}" if run else "")
        response = await self._call("GET", self._pods(), params={"labelSelector": selector})
        return [_sandbox(pod) for pod in response.json().get("items", [])]

    async def create(self, run: str, epoch: int, image: str, limits: Limits) -> str:
        name = f"nuria-sbx-{run}-{epoch}"
        deadline = time.monotonic() + START_TIMEOUT_S
        while True:
            response = await self._call(
                "POST", self._pods(), json=self._pod(name, run, epoch, image, limits)
            )
            if response.status_code != 409:
                break
            # Another replica's, or a removed one still going: use it, or wait it out.
            existing = await self._call("GET", self._pods(name))
            if existing.status_code == 200 and _sandbox(existing.json()).state != "gone":
                break
            if time.monotonic() > deadline:
                raise SandboxStartFailed(f"{name} is still being removed")
            await asyncio.sleep(0.5)
        await self._running(name, deadline)
        return name

    async def _running(self, name: str, deadline: float) -> None:
        while True:
            pod = (await self._call("GET", self._pods(name))).json()
            status = pod.get("status") or {}
            if status.get("phase") == "Running":
                return
            if status.get("phase") in ("Failed", "Succeeded"):
                raise SandboxStartFailed(f"{name} stopped: {status.get('reason', 'unknown')}")
            for c in status.get("containerStatuses") or []:
                waiting = (c.get("state") or {}).get("waiting") or {}
                if waiting.get("reason") in STUCK:
                    raise SandboxStartFailed(f"{name}: {waiting['reason']}")
            if time.monotonic() > deadline:
                raise SandboxStartFailed(f"{name} didn't start in {START_TIMEOUT_S} s")
            await asyncio.sleep(0.5)

    def _pod(self, name: str, run: str, epoch: int, image: str, limits: Limits) -> dict[str, Any]:
        memory = f"{limits.memory_mb}Mi"
        spec: dict[str, Any] = {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            # The pause container is PID 1 and reaps what the commands leave behind.
            "shareProcessNamespace": True,
            "terminationGracePeriodSeconds": 0,
            # A backstop to the sweep: the kubelet stops it whatever happens to sandboxd.
            "activeDeadlineSeconds": 2 * 3600,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": USER_ID,
                "runAsGroup": USER_ID,
                "fsGroup": USER_ID,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": CONTAINER,
                    "image": image,
                    "imagePullPolicy": self._pull_policy,
                    "command": ["sleep", "infinity"],
                    "workingDir": "/workspace",
                    "env": [{"name": k, "value": v} for k, v in ENV.items()],
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "resources": {
                        "requests": {"cpu": "50m", "memory": "64Mi"},
                        "limits": {"cpu": f"{limits.cpus:g}", "memory": memory},
                    },
                    "volumeMounts": [
                        {"name": "workspace", "mountPath": "/workspace"},
                        {"name": "tmp", "mountPath": "/tmp"},
                    ],
                }
            ],
            # In memory, like Docker's tmpfs, and counted against the memory limit.
            "volumes": [
                {
                    "name": "workspace",
                    "emptyDir": {"medium": "Memory", "sizeLimit": f"{limits.workspace_mb}Mi"},
                },
                {"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}},
            ],
        }
        if self._runtime_class:
            spec["runtimeClassName"] = self._runtime_class  # e.g. gVisor, Kata
        if self._user_namespaces:
            spec["hostUsers"] = False  # root inside isn't root on the node
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": name,
                "labels": labels(run, epoch, int(time.time()))
                | {"app.kubernetes.io/name": "sandbox", "app.kubernetes.io/part-of": "nuria"},
            },
            "spec": spec,
        }

    async def remove(self, sandbox: str) -> None:
        await self._call(
            "DELETE",
            self._pods(sandbox),
            json={"gracePeriodSeconds": 0, "propagationPolicy": "Background"},
        )

    async def exec(self, sandbox: str, argv: list[str], timeout_s: float) -> dict[str, Any]:
        query = urlencode(
            {
                "container": CONTAINER,
                "stdin": "true",
                "stdout": "true",
                "stderr": "true",
                "command": ["python", "-c", LAUNCHER],
            },
            doseq=True,
        )
        url = self._api.replace("https://", "wss://", 1) + self._pods(sandbox) + "/exec?" + query
        out, err = Output(), Output()
        status: dict[str, Any] | None = None
        async with asyncio.timeout(timeout_s + 15):
            async with connect(
                url,
                ssl=self._ssl,
                additional_headers=self._headers(),
                subprotocols=[Subprotocol("v4.channel.k8s.io")],
                max_size=4 * 1024 * 1024,
                proxy=None,
            ) as ws:
                await ws.send(b"\x00" + json.dumps(killed_after(argv, timeout_s)).encode() + b"\n")
                with contextlib.suppress(ConnectionClosed):
                    async for message in ws:
                        data = message.encode() if isinstance(message, str) else message
                        if not data:
                            continue
                        channel, body = data[0], data[1:]
                        if channel == 1:
                            out.add(body)
                        elif channel == 2:
                            err.add(body)
                        elif channel == 3 and body:
                            status = json.loads(body)
        return result(_exit_code(status), out, err)


def _sandbox(pod: dict[str, Any]) -> Sandbox:
    meta = pod.get("metadata") or {}
    found = meta.get("labels") or {}
    phase = (pod.get("status") or {}).get("phase")
    if meta.get("deletionTimestamp") or phase in ("Failed", "Succeeded"):
        state: Any = "gone"
    else:
        state = "running" if phase == "Running" else "starting"
    return Sandbox(
        id=meta.get("name", ""),
        epoch=int(found.get(f"{LABEL}.epoch", -1)),
        created=int(found.get(f"{LABEL}.created", 0)),
        state=state,
    )


def _exit_code(status: dict[str, Any] | None) -> int:
    """The exec's v1.Status: Success, or Failure with an ExitCode cause."""
    if status is None:
        raise RuntimeError("the command ended without an exit status")
    if status.get("status") == "Success":
        return 0
    for cause in (status.get("details") or {}).get("causes") or []:
        if cause.get("reason") == "ExitCode":
            return int(cause["message"])
    raise RuntimeError(f"the command couldn't run: {status.get('message')}")
