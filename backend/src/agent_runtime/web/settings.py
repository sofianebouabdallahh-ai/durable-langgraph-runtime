"""Settings → Tools (phase L6a): which search answers, its key, which sites pages come from.

The key is sealed like a model key (L3b, envelope AES-256-GCM): bound to this row and
purpose, never returned (a fingerprint tells keys apart), opened in memory only when a
search is made. Workers resolve the provider per call, cached per settings version.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from agent_runtime.audit import AuditLog, key_change
from agent_runtime.config import Settings
from agent_runtime.db import Conn, Pool
from agent_runtime.keys import Sealed, fingerprint, open_secret, seal, secret_aad
from agent_runtime.models.connections import kek_for
from agent_runtime.web.search import (
    BraveProvider,
    Hit,
    Provider,
    SearchProvider,
    SearchUnavailable,
    SearxngProvider,
    TavilyProvider,
)

WORKSPACE = "local"
AAD = secret_aad(WORKSPACE, "tool_settings", "search-api-key")
KEYED: tuple[Provider, ...] = ("tavily", "brave")


class ToolSettingsInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ToolConfig:
    search_provider: Provider
    searxng_url: str | None
    has_key: bool
    key_fingerprint: str | None
    web_allowlist: list[str]
    updated_at: datetime | None


async def _row(conn: Conn) -> dict[str, Any] | None:
    cur = await conn.execute("SELECT * FROM tool_settings WHERE workspace_id = %s", (WORKSPACE,))
    return await cur.fetchone()


def _config(row: dict[str, Any] | None) -> ToolConfig:
    if row is None:
        return ToolConfig("searxng", None, False, None, [], None)
    return ToolConfig(
        row["search_provider"],
        row["searxng_url"],
        row["key_ciphertext"] is not None,
        row["key_fingerprint"],
        list(row["web_allowlist"]),
        row["updated_at"],
    )


def _sealed(row: dict[str, Any]) -> Sealed | None:
    if row.get("key_ciphertext") is None:
        return None
    return Sealed(
        bytes(row["key_ciphertext"]),
        bytes(row["key_nonce"]),
        bytes(row["wrapped_key"]),
        bytes(row["wrapped_nonce"]),
        row["kek_version"],
    )


class ToolSettings:
    def __init__(self, pool: Pool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings
        self._cache: tuple[datetime | None, SearchProvider] | None = None

    async def current(self) -> ToolConfig:
        async with self._pool.connection() as conn:
            return _config(await _row(conn))

    async def update(
        self,
        *,
        search_provider: Provider | None = None,
        api_key: str | None = None,
        searxng_url: str | None = None,
        web_allowlist: list[str] | None = None,
    ) -> ToolConfig:
        """Change what's given. A new key replaces the old one; a keyed provider needs a
        key (now, or one already saved)."""
        async with self._pool.connection() as conn, conn.transaction():
            row = await _row(conn) or {}
            before = _audited(row) if row else None
            provider = search_provider or row.get("search_provider") or "searxng"
            sets: dict[str, Any] = {"search_provider": provider}
            if api_key is not None and api_key.strip():
                kek = kek_for(self._settings)  # MasterKeyMissing → can't save a key
                sealed = seal(api_key.strip(), AAD, kek)
                sets |= {
                    "key_ciphertext": sealed.ciphertext,
                    "key_nonce": sealed.nonce,
                    "wrapped_key": sealed.wrapped_key,
                    "wrapped_nonce": sealed.wrapped_nonce,
                    "kek_version": sealed.kek_version,
                    "key_fingerprint": fingerprint(api_key.strip(), kek),
                }
            elif provider in KEYED and row.get("key_ciphertext") is None:
                raise ToolSettingsInvalid(f"{provider.title()} needs an API key")
            if searxng_url is not None:
                url = searxng_url.strip().rstrip("/") or None
                if url and not url.startswith(("http://", "https://")):
                    raise ToolSettingsInvalid(
                        "the SearXNG address must start with http:// or https://"
                    )
                sets["searxng_url"] = url
            if web_allowlist is not None:
                sites = sorted({s.strip().lower().lstrip(".") for s in web_allowlist if s.strip()})
                sets["web_allowlist"] = Jsonb(sites)
            columns = ", ".join(sets)
            await conn.execute(
                f"INSERT INTO tool_settings (workspace_id, {columns}) "
                f"VALUES (%s, {', '.join(['%s'] * len(sets))}) "
                f"ON CONFLICT (workspace_id) DO UPDATE SET "
                f"{', '.join(f'{c} = EXCLUDED.{c}' for c in sets)}, updated_at = now()",
                (WORKSPACE, *sets.values()),
            )
            after = await _row(conn) or {}
            await AuditLog(conn).record("tool_settings.changed", "setting", "tools",
                                        before=before, after=_audited(after))  # fmt: skip
            return _config(after)

    async def provider(self) -> SearchProvider:
        """The search to use now (a worker opens the key in memory, cached per version)."""
        async with self._pool.connection() as conn:
            row = await _row(conn)
        version = row["updated_at"] if row else None
        if self._cache is not None and self._cache[0] == version:
            return self._cache[1]
        config = _config(row)
        found: SearchProvider
        if config.search_provider == "searxng":
            found = SearxngProvider(config.searxng_url or self._settings.searxng_url)
        else:
            sealed = _sealed(row or {})
            if sealed is None:
                raise SearchUnavailable(
                    f"{config.search_provider.title()} has no key (Settings → Tools)"
                )
            key = open_secret(sealed, AAD, kek_for(self._settings))
            found = (
                TavilyProvider(key) if config.search_provider == "tavily" else BraveProvider(key)
            )
        self._cache = (version, found)
        return found

    async def allowlist(self) -> list[str]:
        return (await self.current()).web_allowlist

    async def test(self, query: str = "weather today") -> tuple[bool, str, list[Hit]]:
        """A real search, to show it works (Settings → Tools)."""
        try:
            hits = await (await self.provider()).search(query, 3)
        except SearchUnavailable as exc:
            return False, str(exc), []
        if not hits:
            return False, "The search answered, but with no results", []
        return True, f"Works: {len(hits)} results for “{query}”", hits


def _audited(row: dict[str, Any]) -> dict[str, Any]:
    """Tool settings as the audit trail shows them: never the key, only its fingerprint."""
    return {"search_provider": row.get("search_provider"), "searxng_url": row.get("searxng_url"),
            "web_allowlist": row.get("web_allowlist"),
            **key_change(row.get("key_fingerprint"))}  # fmt: skip
