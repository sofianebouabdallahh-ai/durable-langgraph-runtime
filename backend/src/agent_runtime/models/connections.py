"""Model connections (phase L3b, CR-006 R18.2 to R18.4): your own models, your own keys.

    add / edit ──► seal(key) ──► model_connections (ciphertext only)
    test ──► one tool-calling request through the same adapter runs use ──► ready | why
    a turn ──► bind: each model string of its agent → (connection, model), stored on the run
    a call ──► the binding ──► open(key) in memory ──► OpenAI-compatible adapter

Model strings (agent definitions, unchanged schema):
- a role (`chat`, `researcher`, …): the workspace's default connection and model, or,
  with none set, the model chosen in setup (`.env`: the "setup" connection);
- `<connection>:<model>`: that connection, that model (`ollama:qwen2.5:7b`).

Patterns: Repository (ConnectionStore), Service Layer (ConnectionService), Strategy
(the key's master key, keys.py), memoised factory (one adapter per connection
version, model and temperature).
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.audit import AuditLog, key_change
from agent_runtime.config import Settings
from agent_runtime.db import Conn, Pool
from agent_runtime.ids import new_id
from agent_runtime.keys import (
    LocalKek,
    MasterKeyMissing,
    Sealed,
    SecretUnavailable,
    fingerprint,
    open_secret,
    seal,
    secret_aad,
)
from agent_runtime.models.pricing import Price, resolve_price
from agent_runtime.models.provider import (
    ModelProvider,
    OpenAICompatibleProvider,
    call_timeout_s,
    configured_provider,
    is_local,
)
from agent_runtime.redaction import redact

Kind = Literal["ollama", "openai", "azure_foundry", "compatible"]
Status = Literal["untested", "ready", "failed"]
WORKSPACE = "local"
TEST_TIMEOUT_S = 30.0  # a cloud model's test; a local one's gets the local call limit
OLLAMA_PROBES = (
    "http://host.docker.internal:11434",  # the app on the host (macOS, Windows)
    "http://ollama:11434",  # the Compose `llm` profile
    "http://127.0.0.1:11434",  # the developer loop
)
# Ollama ignores the key, but the OpenAI client wants one.
KEYLESS = "not-needed"


class ConnectionNotFound(LookupError):
    pass


class ConnectionInvalid(ValueError):
    """A connection that can't be saved as given (a missing key, a bad URL)."""


@dataclass(frozen=True, slots=True)
class Connection:
    id: uuid.UUID
    name: str
    display_name: str
    kind: Kind
    base_url: str
    sealed: Sealed | None
    key_fingerprint: str | None
    models: list[str]
    prices: dict[str, dict[str, float]]  # model → {input_per_mtok, output_per_mtok} (H2)
    test_status: Status
    test_detail: str | None
    tested_model: str | None
    tested_at: datetime | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    @property
    def has_key(self) -> bool:
        return self.sealed is not None

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> Connection:
        sealed = None
        if r["key_ciphertext"] is not None:
            sealed = Sealed(
                bytes(r["key_ciphertext"]),
                bytes(r["key_nonce"]),
                bytes(r["wrapped_key"]),
                bytes(r["wrapped_nonce"]),
                r["kek_version"],
            )
        return cls(
            id=r["id"],
            name=r["name"],
            display_name=r["display_name"],
            kind=r["kind"],
            base_url=r["base_url"],
            sealed=sealed,
            key_fingerprint=r["key_fingerprint"],
            models=list(r["models"] or []),
            prices=dict(r.get("prices") or {}),
            test_status=r["test_status"],
            test_detail=r["test_detail"],
            tested_model=r["tested_model"],
            tested_at=r["tested_at"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            archived_at=r["archived_at"],
        )


_COLUMNS = """id, name, display_name, kind, base_url, key_ciphertext, key_nonce, wrapped_key,
    wrapped_nonce, kek_version, key_fingerprint, models, prices, test_status, test_detail,
    tested_model, tested_at, created_at, updated_at, archived_at"""


def _aad(connection_id: uuid.UUID) -> str:
    return secret_aad(WORKSPACE, str(connection_id), "model-api-key")


# ------------------------------------------------------------------ the store


class ConnectionStore:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def all(self, *, archived: bool = False) -> list[Connection]:
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM model_connections WHERE workspace_id = %s "
            "AND (%s OR archived_at IS NULL) ORDER BY created_at",
            (WORKSPACE, archived),
        )
        return [Connection.from_row(r) for r in await cur.fetchall()]

    async def get(self, connection_id: uuid.UUID) -> Connection:
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM model_connections WHERE id = %s", (connection_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise ConnectionNotFound(str(connection_id))
        return Connection.from_row(row)

    async def by_name(self, name: str) -> Connection | None:
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM model_connections WHERE workspace_id = %s AND name = %s "
            "AND archived_at IS NULL",
            (WORKSPACE, name),
        )
        row = await cur.fetchone()
        return Connection.from_row(row) if row else None

    async def insert(
        self,
        cid: uuid.UUID,
        name: str,
        display_name: str,
        kind: Kind,
        base_url: str,
        sealed: Sealed | None,
        key_fingerprint: str | None,
        models: list[str],
    ) -> Connection:
        from psycopg.types.json import Jsonb

        cur = await self._conn.execute(
            f"""
            INSERT INTO model_connections (id, workspace_id, name, display_name, kind, base_url,
                key_ciphertext, key_nonce, wrapped_key, wrapped_nonce, kek_version,
                key_fingerprint, models)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_COLUMNS}
            """,
            (
                cid,
                WORKSPACE,
                name,
                display_name,
                kind,
                base_url,
                *(_sealed_columns(sealed)),
                key_fingerprint,
                Jsonb(models),
            ),
        )
        row = await cur.fetchone()
        assert row is not None
        return Connection.from_row(row)

    async def update(self, cid: uuid.UUID, **changes: Any) -> Connection:
        from psycopg.types.json import Jsonb

        sets, values = ["updated_at = now()"], []
        for column, value in changes.items():
            if column == "sealed":
                cols = (
                    "key_ciphertext",
                    "key_nonce",
                    "wrapped_key",
                    "wrapped_nonce",
                    "kek_version",
                )
                for col, val in zip(cols, _sealed_columns(value), strict=True):
                    sets.append(f"{col} = %s")
                    values.append(val)
                continue
            sets.append(f"{column} = %s")
            values.append(Jsonb(value) if column in ("models", "prices") else value)
        cur = await self._conn.execute(
            f"UPDATE model_connections SET {', '.join(sets)} WHERE id = %s RETURNING {_COLUMNS}",
            (*values, cid),
        )
        row = await cur.fetchone()
        if row is None:
            raise ConnectionNotFound(str(cid))
        return Connection.from_row(row)

    async def default(self) -> tuple[uuid.UUID, str] | None:
        cur = await self._conn.execute(
            "SELECT s.default_connection_id AS id, s.default_model AS model "
            "FROM workspace_settings s JOIN model_connections c ON c.id = s.default_connection_id "
            "WHERE s.workspace_id = %s AND c.archived_at IS NULL",
            (WORKSPACE,),
        )
        row = await cur.fetchone()
        return (row["id"], row["model"]) if row else None

    async def set_default(self, cid: uuid.UUID | None, model: str | None) -> None:
        await self._conn.execute(
            """
            INSERT INTO workspace_settings (workspace_id, default_connection_id, default_model)
            VALUES (%s, %s, %s)
            ON CONFLICT (workspace_id) DO UPDATE
               SET default_connection_id = EXCLUDED.default_connection_id,
                   default_model = EXCLUDED.default_model, updated_at = now()
            """,
            (WORKSPACE, cid, model),
        )


def _sealed_columns(sealed: Sealed | None) -> tuple[Any, ...]:
    if sealed is None:
        return (None, None, None, None, None)
    return (
        sealed.ciphertext,
        sealed.nonce,
        sealed.wrapped_key,
        sealed.wrapped_nonce,
        sealed.kek_version,
    )


# --------------------------------------------------------------- the service


@dataclass(frozen=True)
class TestResult:
    ok: bool
    detail: str
    model: str
    seconds: float


@dataclass
class OllamaFound:
    base_url: str
    models: list[str] = field(default_factory=list)


def kek_for(settings: Settings) -> LocalKek:
    secret = settings.nuria_secret_key.get_secret_value() if settings.nuria_secret_key else ""
    return LocalKek(secret)


def normalise_url(kind: Kind, url: str) -> str:
    """Where the OpenAI-compatible API lives, from what a person pastes."""
    url = url.strip().rstrip("/")
    if not re.match(r"^https?://", url):
        raise ConnectionInvalid("The address must start with http:// or https://")
    if kind == "ollama" and not url.endswith("/v1"):
        url += "/v1"  # Ollama's OpenAI-compatible API
    if kind == "azure_foundry" and "/openai/v1" not in url:
        url = re.sub(r"/openai(/.*)?$", "", url) + "/openai/v1"  # Foundry's v1 route
    return url


class ConnectionService:
    def __init__(self, pool: Pool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    async def all(self) -> list[Connection]:
        async with self._pool.connection() as conn:
            return await ConnectionStore(conn).all()

    async def get(self, cid: uuid.UUID) -> Connection:
        async with self._pool.connection() as conn:
            return await ConnectionStore(conn).get(cid)

    async def add(
        self,
        *,
        display_name: str,
        kind: Kind,
        base_url: str,
        api_key: str | None,
        models: list[str],
    ) -> Connection:
        url = normalise_url(kind, base_url)
        key = (api_key or "").strip() or None
        if kind in ("openai", "azure_foundry") and key is None:
            raise ConnectionInvalid("This kind of model needs its key")
        kek = kek_for(self._settings)  # MasterKeyMissing → can't save a key
        cid = new_id()
        sealed = seal(key, _aad(cid), kek) if key else None
        async with self._pool.connection() as conn, conn.transaction():
            store = ConnectionStore(conn)
            name = await self._free_name(store, display_name)
            added = await store.insert(
                cid,
                name,
                display_name.strip()[:60],
                kind,
                url,
                sealed,
                fingerprint(key, kek) if key else None,
                _clean(models),
            )
            await AuditLog(conn).record("model_connection.added", "model_connection", name,
                                        after=_audited(added))  # fmt: skip
            return added

    async def update(
        self,
        cid: uuid.UUID,
        *,
        display_name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        models: list[str] | None = None,
        prices: dict[str, dict[str, float] | None] | None = None,
    ) -> Connection:
        """A new key replaces the old one (the old ciphertext is gone); no key keeps it.
        A changed address or key needs a new test. `prices`: per model, USD per 1M tokens
        (input, output); None removes a model's price (phase H2)."""
        async with self._pool.connection() as conn, conn.transaction():
            store = ConnectionStore(conn)
            current = await store.get(cid)
            changes: dict[str, Any] = {}
            if display_name is not None:
                changes["display_name"] = display_name.strip()[:60]
            if models is not None:
                changes["models"] = _clean(models)
            if prices is not None:
                changes["prices"] = _priced(current.prices, prices)
            if base_url is not None and normalise_url(current.kind, base_url) != current.base_url:
                changes["base_url"] = normalise_url(current.kind, base_url)
            if api_key:
                kek = kek_for(self._settings)
                changes["sealed"] = seal(api_key.strip(), _aad(cid), kek)
                changes["key_fingerprint"] = fingerprint(api_key.strip(), kek)
            if "base_url" in changes or "sealed" in changes:
                changes.update(test_status="untested", test_detail=None, tested_at=None)
            if not changes:
                return current
            updated = await store.update(cid, **changes)
            await AuditLog(conn).record("model_connection.changed", "model_connection",
                                        current.name, before=_audited(current),
                                        after=_audited(updated))  # fmt: skip
            return updated

    async def archive(self, cid: uuid.UUID) -> None:
        async with self._pool.connection() as conn, conn.transaction():
            store = ConnectionStore(conn)
            if (default := await store.default()) and default[0] == cid:
                await store.set_default(None, None)
            gone = await store.update(cid, archived_at=datetime.now().astimezone())
            await AuditLog(conn).record("model_connection.removed", "model_connection",
                                        gone.name, before=_audited(gone))  # fmt: skip

    async def default(self) -> tuple[Connection, str] | None:
        async with self._pool.connection() as conn:
            store = ConnectionStore(conn)
            found = await store.default()
            return (await store.get(found[0]), found[1]) if found else None

    async def set_default(self, cid: uuid.UUID | None, model: str | None) -> None:
        async with self._pool.connection() as conn, conn.transaction():
            store = ConnectionStore(conn)
            if cid is not None:
                await store.get(cid)  # 404 for an unknown connection
            was = await store.default()
            await store.set_default(cid, model if cid else None)
            await AuditLog(conn).record(
                "default_model.changed", "setting", "default_model",
                before={"connection_id": str(was[0]), "model": was[1]} if was else None,
                after={"connection_id": str(cid), "model": model} if cid else None,
            )  # fmt: skip

    async def test(self, cid: uuid.UUID, model: str) -> TestResult:
        """One small request with a tool: proves the address, the key, the model and
        tool calling at once (agents need tools). The outcome is saved."""
        connection = await self.get(cid)
        started = time.monotonic()
        # A local model's first call loads it into memory: on a busy laptop, minutes.
        local = connection.kind == "ollama" or is_local(connection.base_url)
        timeout = self._settings.local_model_timeout_s if local else TEST_TIMEOUT_S
        try:
            provider = self.provider(connection, model, timeout_s=timeout)
            result = await asyncio.wait_for(_ping(provider), timeout)
        except TimeoutError:
            result = TestResult(False, f"Didn't answer in {timeout:.0f} s", model, 0)
        except (MasterKeyMissing, SecretUnavailable):
            result = TestResult(
                False,
                "The saved key can't be opened (was .env replaced?): enter the key again",
                model,
                0,
            )
        except Exception as exc:
            result = TestResult(False, explain(exc, connection.base_url), model, 0)
        result = TestResult(result.ok, result.detail, model, time.monotonic() - started)
        async with self._pool.connection() as conn, conn.transaction():
            await ConnectionStore(conn).update(
                cid,
                test_status="ready" if result.ok else "failed",
                test_detail=result.detail,
                tested_model=model,
                tested_at=datetime.now().astimezone(),
                **({"models": _clean([model, *connection.models])} if result.ok else {}),
            )
        return result

    def provider(
        self, connection: Connection, model: str, timeout_s: float = TEST_TIMEOUT_S
    ) -> OpenAICompatibleProvider:
        key = KEYLESS
        if connection.sealed is not None:
            key = open_secret(connection.sealed, _aad(connection.id), kek_for(self._settings))
        return OpenAICompatibleProvider(
            name=connection.name,
            base_url=connection.base_url,
            api_key=SecretStr(key),
            models={"default": model},
            timeout_s=timeout_s,
        )

    def prices_of(self, c: Connection) -> dict[str, Price]:
        """What a call to each of the connection's models costs, and why (phase H2)."""
        return {
            m: resolve_price(m, connection_prices=c.prices,
                             settings_prices=self._settings.model_prices, local=_local(c))
            for m in dict.fromkeys([*c.models, *c.prices])
        }  # fmt: skip

    async def remote_models(self, cid: uuid.UUID) -> list[str]:
        """What the service says it has (Ollama's pulled models; /v1/models elsewhere)."""
        connection = await self.get(cid)
        headers = {}
        if connection.sealed is not None:
            key = open_secret(connection.sealed, _aad(connection.id), kek_for(self._settings))
            headers["Authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                if connection.kind == "ollama":
                    root = connection.base_url.removesuffix("/v1")
                    tags = (await client.get(f"{root}/api/tags")).json()
                    return sorted(m["name"] for m in tags.get("models", []))
                listed = (await client.get(f"{connection.base_url}/models", headers=headers)).json()
                return sorted(m["id"] for m in listed.get("data", []))
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return []

    async def discover_ollama(self) -> list[OllamaFound]:
        """Ollama servers reachable from here (the host app, the Compose service)."""
        found: list[OllamaFound] = []
        async with httpx.AsyncClient(timeout=2) as client:
            for root in dict.fromkeys(
                [self._settings.ollama_base_url.removesuffix("/v1"), *OLLAMA_PROBES]
            ):
                try:
                    tags = (await client.get(f"{root}/api/tags")).json()
                except (httpx.HTTPError, ValueError):
                    continue
                models = sorted(m["name"] for m in tags.get("models", []))
                found.append(OllamaFound(f"{root}/v1", models))
        return found

    async def _free_name(self, store: ConnectionStore, display_name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")[:30].strip("-")
        if not base or not base[0].isalpha():
            base = f"model-{base}" if base else "model"
        for n in range(1, 100):
            name = base if n == 1 else f"{base}-{n}"
            if await store.by_name(name) is None:
                return name
        raise ConnectionInvalid("too many connections with this name")


def _priced(
    current: dict[str, dict[str, float]], changes: dict[str, dict[str, float] | None]
) -> dict[str, dict[str, float]]:
    """Apply price changes: a price per model (both rates ≥ 0, below $10,000 per 1M
    tokens), None to remove one. At most 50 priced models per connection."""
    out = dict(current)
    for model, price in changes.items():
        name = model.strip()
        if not name or len(name) > 200:
            raise ConnectionInvalid("A price needs the model's name")
        if price is None:
            out.pop(name, None)
            continue
        rates = {k: float(price.get(k, -1)) for k in ("input_per_mtok", "output_per_mtok")}
        if any(not 0 <= v < 10_000 for v in rates.values()):
            raise ConnectionInvalid(
                f"The price of {name} must be in US dollars per 1 million tokens, from 0"
            )
        out[name] = rates
    if len(out) > 50:
        raise ConnectionInvalid("At most 50 models can have a price on one connection")
    return out


def _clean(models: list[str]) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in models if m.strip()))[:50]


async def _ping(provider: ModelProvider) -> TestResult:
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import StructuredTool

    async def ping(value: int) -> str:
        return str(value)

    tool = StructuredTool.from_function(
        coroutine=ping, name="ping", description="Answer the connection test."
    )
    model = provider.chat("default", temperature=0, script=[], offset=0).bind_tools([tool])
    reply = await model.ainvoke(
        [
            HumanMessage(
                "This is a connection test. Call the tool `ping` with value 42, and nothing else."
            )
        ]
    )
    calls = getattr(reply, "tool_calls", []) or []
    if not calls:
        return TestResult(
            False,
            "It answered, but it doesn't use tools; agents need that. Try a larger or newer model.",
            "",
            0,
        )
    return TestResult(True, "Ready: it answers and uses tools", "", 0)


def explain(exc: BaseException, base_url: str) -> str:
    """A provider's failure, in plain words (and never with the key in it)."""
    host = urlparse(base_url).netloc or base_url
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if name == "AuthenticationError" or status in (401, 403):
        return "The key was refused. Check it, and that it has access to this model"
    if name == "NotFoundError" or status == 404:
        return "This model isn't available there. Check its name (Foundry: the deployment name)"
    if name == "RateLimitError" or status == 429:
        return "The service is busy or the key is over its quota. Try again later"
    unreachable = name in ("APIConnectionError", "ConnectError", "ConnectTimeout")
    if unreachable or "connect" in str(exc).lower():
        return f"Couldn't reach {host}. Is the address right, and is the service running?"
    if name in ("APITimeoutError", "ReadTimeout"):
        return f"{host} didn't answer in time"
    return str(redact(f"It failed: {name}: {exc}"))[:300]


# ---------------------------------------------------------------- the router


Binding = dict[str, Any]  # {"connection": id, "name": …, "model": …} or {"setup": True}


class ModelUnavailable(LookupError):
    pass


class ModelRouter:
    """Model strings → bindings (at turn creation) → chat models (in the worker)."""

    def __init__(self, pool: Pool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings
        self._service = ConnectionService(pool, settings)
        self._providers: dict[tuple[str, str, str], ModelProvider] = {}

    async def bind(self, conn: Conn, agent: AgentDefinition) -> dict[str, Binding]:
        """Resolve every model the agent and its helpers name, now: the run keeps these
        even if the default changes. Raises ModelUnavailable for an unknown connection."""
        store = ConnectionStore(conn)
        default = await store.default()
        bindings: dict[str, Binding] = {}
        for model in {agent.frontmatter.model, *(s.frontmatter.model for s in agent.subagents)}:
            if ":" in model:
                name, model_id = model.split(":", 1)
                connection = await store.by_name(name)
                if connection is None:
                    raise ModelUnavailable(
                        f"There's no model connection called {name!r} (Settings → Models)"
                    )
                bindings[model] = {
                    "connection": str(connection.id),
                    "name": name,
                    "model": model_id,
                    "local": _local(connection),
                    "price": self._price(model_id, connection).as_dict(),
                }
            elif default is not None:
                connection = await store.get(default[0])
                bindings[model] = {
                    "connection": str(default[0]),
                    "name": connection.name,
                    "model": default[1],
                    "local": _local(connection),
                    "price": self._price(default[1], connection).as_dict(),
                }
            else:
                local = self._setup_is_local()
                model_id = self._setup_model(model)
                bindings[model] = {
                    "setup": True,
                    "local": local,
                    "price": resolve_price(
                        model_id, settings_prices=self._settings.model_prices, local=local
                    ).as_dict(),
                }
        return bindings

    def _price(self, model_id: str, connection: Connection) -> Price:
        """A turn's price for this model, pinned with its binding (phase H2)."""
        return resolve_price(
            model_id, connection_prices=connection.prices,
            settings_prices=self._settings.model_prices, local=_local(connection),
        )  # fmt: skip

    def _setup_model(self, role: str) -> str:
        """The model the setup's provider uses for `role` (its name for the scripted one)."""
        provider = configured_provider(self._settings)
        model_for = getattr(provider, "model_for", None)
        return str(model_for(role)) if callable(model_for) else provider.name

    def _setup_is_local(self) -> bool:
        """The model setup configured (.env): Ollama, or an address on this machine."""
        s = self._settings
        if s.model_provider == "scripted":
            return False
        url = s.ollama_base_url if s.model_provider == "ollama" else s.openai_base_url
        return s.model_provider == "ollama" or is_local(url)

    async def providers(self, bindings: dict[str, Binding]) -> dict[str, ModelProvider]:
        """The adapter for each bound model (the worker, before the run's graph starts).
        Keys are opened here, in memory; adapters are cached per connection version."""
        out: dict[str, ModelProvider] = {}
        for model, binding in bindings.items():
            if binding.get("setup"):
                out[model] = configured_provider(self._settings)
                continue
            connection = await self._service.get(uuid.UUID(binding["connection"]))
            cache_key = (str(connection.id), connection.updated_at.isoformat(), binding["model"])
            if cache_key not in self._providers:
                self._providers[cache_key] = self._service.provider(
                    connection, binding["model"],
                    timeout_s=call_timeout_s(connection.kind, connection.base_url,
                                             self._settings),
                )  # fmt: skip
            out[model] = self._providers[cache_key]
        return out


def _audited(c: Connection) -> dict[str, Any]:
    """A connection as the audit trail shows it: never the key, only that one is set."""
    return {"display_name": c.display_name, "kind": c.kind, "base_url": c.base_url,
            "models": c.models, "prices": c.prices,
            **key_change(c.key_fingerprint)}  # fmt: skip


def _local(c: Connection) -> bool:
    return c.kind == "ollama" or is_local(c.base_url)


def any_local(bindings: dict[str, Any] | None) -> bool:
    """Does a run with these bindings use a local model (slower: see local_model_limits)?"""
    return any(b.get("local") for b in (bindings or {}).values())
