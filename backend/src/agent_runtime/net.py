"""Where Nuria may send a request it was given an address for (phase H3).

One check for every address a person (or a page) can give Nuria: an MCP server, a model
connection, the SearXNG instance. `web/fetch.py` guards the page reader on its own, and
connects to the address it checked.

`check_destination` resolves the host and checks EVERY address it resolves to, so the
forms a name check misses are refused too: decimal, hex and octal IPs (the resolver
reads them), names that resolve to metadata (`169.254.169.254.nip.io`), IPv4-mapped and
NAT64 IPv6 forms. Refused, whatever the purpose:

- cloud metadata and the link-local range it lives in;
- multicast, unspecified and reserved addresses;
- Nuria's own services (the database, Redis, the API, the sandbox daemon…), by name AND
  by the addresses their names resolve to.

This machine and your network stay allowed: a model on Ollama or an MCP server on
your laptop is the common case.

Remaining window (documented in SECURITY.md): the HTTP clients of the model and MCP
SDKs resolve the name again when they connect, so a name that changes its answer in
between (DNS rebinding) is checked at save, test and call time, not at connect time.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

IP = ipaddress.IPv4Address | ipaddress.IPv6Address

# Nuria's own services, as Compose names them. Kubernetes adds its Service names
# through INTERNAL_HOSTS (the chart sets it).
OWN_SERVICES = frozenset({
    "postgres", "redis", "api", "worker", "ui", "sandboxd", "fetcher", "searxng",
    "otel-collector", "tempo", "loki", "prometheus", "grafana", "migrate",
})  # fmt: skip
METADATA_NAMES = frozenset({"metadata", "metadata.google.internal", "instance-data"})
METADATA_IPS = frozenset(
    ipaddress.ip_address(a)
    for a in ("169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254")
)
NAT64 = ipaddress.ip_network("64:ff9b::/96")

_own_cache: dict[frozenset[str], tuple[float, frozenset[IP]]] = {}
_OWN_TTL_S = 60.0


class DestinationRefused(ValueError):
    """The address can't be used, in plain words (shown to the person)."""


@dataclass(frozen=True, slots=True)
class Guard:
    """`check_destination` with this deployment's facts (from the settings)."""

    internal: frozenset[str] = frozenset()  # more of Nuria's own names (INTERNAL_HOSTS)
    in_container: bool = False  # NURIA_IN_CONTAINER: 127.0.0.1 is Nuria itself

    @classmethod
    def of(cls, settings: Any) -> Guard:
        names = str(getattr(settings, "internal_hosts", "") or "").replace(",", " ").split()
        return cls(frozenset(n.lower() for n in names),
                   bool(getattr(settings, "nuria_in_container", False)))  # fmt: skip

    async def check(self, url: str, *, allowed_services: Iterable[str] = ()) -> str:
        return await check_destination(
            url, allowed_services=allowed_services, extra_internal=self.internal,
            in_container=self.in_container,
        )  # fmt: skip


def same_destination(a: str, b: str) -> bool:
    """Do two URLs reach the same place (scheme, host, port)? A saved key may only be
    sent where it was entered for (phase H3)."""
    return _origin(a) == _origin(b)


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url.strip())
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    return parts.scheme.lower(), (parts.hostname or "").rstrip(".").lower(), port


async def check_destination(
    url: str,
    *,
    allowed_services: Iterable[str] = (),
    extra_internal: Iterable[str] = (),
    in_container: bool = False,
) -> str:
    """`url`, stripped, if it may be used; DestinationRefused otherwise.

    `allowed_services`: own services this purpose legitimately calls (the search tool
    calls the stack's `searxng`). `extra_internal`: more names that are Nuria's own (the
    Kubernetes Service names). `in_container`: Nuria runs in a container, where
    127.0.0.1 is Nuria itself, not your machine (that is host.docker.internal)."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise DestinationRefused("The address must start with http:// or https://")
    host = parts.hostname.rstrip(".").lower()
    allowed = {s.lower() for s in allowed_services}
    internal = (OWN_SERVICES | {n.lower() for n in extra_internal}) - allowed
    if host in METADATA_NAMES:
        raise DestinationRefused(f"{host} is a cloud metadata address")
    if host in internal:
        raise DestinationRefused(f"{host} is one of Nuria's own services")
    addresses = await _resolve(host, parts.port or (443 if parts.scheme == "https" else 80))
    if not addresses:
        raise DestinationRefused(f"Nothing answers to the name {host}")
    own = await _own_addresses(internal)
    for ip in addresses:
        if (reason := _refused(ip)) is not None:
            raise DestinationRefused(f"{host} leads to {ip}, {reason}")
        if _effective(ip) in own:
            raise DestinationRefused(f"{host} leads to one of Nuria's own services")
        if in_container and _effective(ip).is_loopback:
            raise DestinationRefused(
                f"Inside Nuria's container, {host} is Nuria itself. For a server on your "
                "computer, use host.docker.internal"
            )
    return url


def _effective(ip: IP) -> IP:
    """The IPv4 address behind an IPv4-mapped or NAT64 IPv6 one."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip in NAT64:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def _refused(ip: IP) -> str | None:
    ip = _effective(ip)
    if ip in METADATA_IPS:
        return "a cloud metadata address"
    if ip.is_link_local:
        return "a link-local address (where cloud metadata lives)"
    if ip.is_multicast or ip.is_unspecified or (ip.is_reserved and not ip.is_loopback):
        return "a reserved address"  # (::1 sits in IPv6's reserved ::/8: it's loopback)
    return None


async def _resolve(host: str, port: int) -> list[IP]:
    """Every address `host` resolves to (the resolver reads decimal, hex and octal IPs
    too). An address literal is returned as is."""
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=5.0
        )
    except (OSError, TimeoutError):
        return []
    found: list[IP] = []
    for info in infos:
        try:
            found.append(ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]))
        except ValueError:
            continue
    return found


async def _own_addresses(names: frozenset[str]) -> frozenset[IP]:
    """The addresses Nuria's own services resolve to now (cached a minute). Names that
    don't resolve (outside Compose) add nothing."""
    # No entry is never fresh: `monotonic()` counts from boot, so a default of 0.0 would
    # look a few seconds old on a machine that has just started (a CI runner, a pod).
    if (entry := _own_cache.get(names)) is not None and time.monotonic() - entry[0] < _OWN_TTL_S:
        return entry[1]
    results = await asyncio.gather(*(_resolve_quietly(n) for n in sorted(names)))
    own = frozenset(_effective(ip) for found in results for ip in found)
    _own_cache[names] = (time.monotonic(), own)
    return own


async def _resolve_quietly(name: str) -> list[IP]:
    try:
        return await asyncio.wait_for(_resolve(name, 80), timeout=1.0)
    except TimeoutError:
        return []
