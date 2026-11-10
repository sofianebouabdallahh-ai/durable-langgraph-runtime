"""Where Nuria may send a request it was given an address for (phase H3, net.py)."""

import ipaddress

import pytest

from agent_runtime import net
from agent_runtime.net import DestinationRefused, Guard, check_destination, same_destination


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    net._own_cache.clear()


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://2852039166/",  # decimal
        "http://0xa9fea9fe/",  # hex
        "http://0251.0376.0251.0376/",  # octal
        "http://[fd00:ec2::254]/",  # AWS IPv6 metadata
        "http://100.100.100.200/",  # Alibaba metadata
        "http://[::ffff:169.254.169.254]/",  # IPv4-mapped
        "http://[64:ff9b::a9fe:a9fe]/",  # NAT64 form of 169.254.169.254
        "http://metadata.google.internal./",  # trailing dot
        "http://0.0.0.0:8000/",  # unspecified
        "http://224.0.0.1/",  # multicast
    ],
)
async def test_metadata_and_reserved_forms_are_refused(url: str) -> None:
    with pytest.raises(DestinationRefused):
        await check_destination(url)


async def test_a_name_that_resolves_to_metadata_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(host: str, port: int) -> list[net.IP]:
        return [ipaddress.ip_address("169.254.169.254")] if "nip.io" in host else []

    monkeypatch.setattr(net, "_resolve", resolve)
    with pytest.raises(DestinationRefused, match="metadata"):
        await check_destination("http://169.254.169.254.nip.io/")


@pytest.mark.parametrize("url", ["http://postgres:5432", "http://API:8000/", "http://sandboxd/run"])
async def test_nurias_own_services_are_refused_by_name(url: str) -> None:
    with pytest.raises(DestinationRefused, match="Nuria's own"):
        await check_destination(url)


async def test_nurias_own_services_are_refused_by_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raw container IP, or another name for it, is refused too."""
    redis_ip = ipaddress.ip_address("172.18.0.5")

    async def resolve(host: str, port: int) -> list[net.IP]:
        return {"redis": [redis_ip], "sneaky.example": [redis_ip]}.get(host, [])

    monkeypatch.setattr(net, "_resolve", resolve)
    with pytest.raises(DestinationRefused, match="Nuria's own"):
        await check_destination("http://sneaky.example:6379/")


async def test_the_search_purpose_may_reach_the_stacks_searxng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(host: str, port: int) -> list[net.IP]:
        return [ipaddress.ip_address("172.18.0.9")] if host == "searxng" else []

    monkeypatch.setattr(net, "_resolve", resolve)
    url = await check_destination("http://searxng:8080", allowed_services=("searxng",))
    assert url == "http://searxng:8080"
    with pytest.raises(DestinationRefused):
        await check_destination("http://searxng:8080")  # not for an MCP server


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:11434/v1", "http://192.168.1.20:8080/mcp", "http://[::1]:9999"]
)
async def test_your_computer_and_network_are_allowed(url: str) -> None:
    assert await check_destination(url) == url


async def test_in_a_container_loopback_is_nuria_itself() -> None:
    with pytest.raises(DestinationRefused, match=r"host\.docker\.internal"):
        await Guard(in_container=True).check("http://127.0.0.1:8000/admin/cancel-all")


async def test_extra_internal_names_from_the_settings() -> None:
    guard = Guard.of(type("S", (), {"internal_hosts": "nuria-api, nuria-redis",
                                    "nuria_in_container": False})())  # fmt: skip
    with pytest.raises(DestinationRefused, match="Nuria's own"):
        await guard.check("http://nuria-redis:6379")


@pytest.mark.parametrize("url", ["ftp://example.com", "file:///etc/passwd", "example.com", ""])
async def test_only_http_and_https(url: str) -> None:
    with pytest.raises(DestinationRefused, match="http"):
        await check_destination(url)


def test_same_destination() -> None:
    assert same_destination("https://api.openai.com/v1", "https://API.openai.com:443/v2")
    assert not same_destination("https://api.openai.com/v1", "https://evil.example/v1")
    assert not same_destination("http://host:8000", "http://host:9000")
    assert not same_destination("http://host", "https://host")


async def test_own_addresses_are_looked_up_even_just_after_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """monotonic() counts from boot: on a machine up for under a minute, an empty cache
    must not pass for a fresh one (it made the check above pass on a fresh CI runner)."""
    monkeypatch.setattr("agent_runtime.net.time.monotonic", lambda: 5.0)

    async def resolve(host: str, port: int) -> list[net.IP]:
        return [ipaddress.ip_address("172.18.0.5")] if host in ("redis", "x.example") else []

    monkeypatch.setattr(net, "_resolve", resolve)
    with pytest.raises(DestinationRefused, match="Nuria's own"):
        await check_destination("http://x.example:6379/")
