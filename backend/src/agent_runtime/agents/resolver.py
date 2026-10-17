"""Which agent a turn runs, pinned by hash (CR-004 R15.4, CR-006 R17.1).

    resolve(name)          a built-in (files) or a user agent's published version
    resolve(name, draft)   a user agent's draft (its test chat)
        → validate (the one validator) → snapshot the bundle → bundle hash
    spec(bundle hash)      the compiled agent, rebuilt from the snapshots, cached

A run stores the bundle hash when it is created, and every worker builds the agent
from that snapshot. So:
- publishing a new version never changes a running turn; the next turn uses it (AC47);
- a built-in file edited during a rolling upgrade can't change a queued turn (R15.4).

Patterns: Registry (two sources behind one lookup); content-addressed snapshots;
memoised factory (one compiled spec per hash per process: specs are immutable).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from agent_runtime.agents.document import AgentDocument, to_raw
from agent_runtime.agents.loader import Catalog, Ceilings, Issue, validate_definition
from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.agents.store import load_bundle, snapshot_bundle
from agent_runtime.agents.studio_store import AgentStore, Version
from agent_runtime.catalog import default_catalog
from agent_runtime.config import get_agent_settings
from agent_runtime.db import Conn, Pool
from agent_runtime.graphs import GraphRegistry, GraphSpec
from agent_runtime.tools.spec import ToolRegistry

Source = Literal["builtin", "user"]
CACHE_SIZE = 256


class AgentUnavailable(LookupError):
    """No such agent, or nothing runnable: archived, never published, or no longer valid."""


@dataclass(frozen=True, slots=True)
class Resolved:
    definition: AgentDefinition
    bundle_hash: str
    version: int
    source: Source
    agent_id: uuid.UUID | None = None  # user agents


class AgentResolver:
    def __init__(
        self,
        pool: Pool,
        graphs: GraphRegistry,
        tools: ToolRegistry,
        *,
        catalog: Catalog | None = None,
        ceilings: Ceilings | None = None,
    ) -> None:
        self._pool = pool
        self._graphs = graphs
        self._tools = tools
        self._catalog = catalog or default_catalog()
        self._ceilings = ceilings or Ceilings.from_settings(get_agent_settings())
        self._specs: OrderedDict[str, GraphSpec] = OrderedDict()

    # --------------------------------------------------------------- lookups

    def builtin(self, name: str) -> AgentDefinition | None:
        try:
            return self._graphs.get(name).agent
        except LookupError:
            return None

    def validate(
        self, document: AgentDocument, version: int
    ) -> tuple[AgentDefinition | None, list[Issue]]:
        main, helpers = to_raw(document, version)
        return validate_definition(main, helpers, self._catalog, self._ceilings)

    async def resolve(
        self, conn: Conn, name: str, *, draft_of: uuid.UUID | None = None
    ) -> Resolved:
        """The definition a new turn of `name` runs, snapshotted. Raises AgentUnavailable."""
        if draft_of is not None:
            store = AgentStore(conn)
            draft = await store.draft(draft_of) or await store.published(draft_of)
            if draft is None:
                raise AgentUnavailable(f"agent {name!r} has nothing to test")
            return await self._from_version(conn, draft, "user")
        if (builtin := self.builtin(name)) is not None:
            digest = await snapshot_bundle(conn, builtin)
            self._remember(digest, builtin)
            return Resolved(builtin, digest, builtin.frontmatter.version, "builtin")
        stored = await AgentStore(conn).by_name(name)
        if stored is None or stored.archived_at is not None:
            raise AgentUnavailable(f"unknown agent {name!r}")
        published = await AgentStore(conn).published(stored.id)
        if published is None:
            raise AgentUnavailable(f"agent {name!r} isn't published yet")
        return await self._from_version(conn, published, "user")

    async def exists(self, name: str) -> bool:
        if self.builtin(name) is not None:
            return True
        async with self._pool.connection() as conn:
            stored = await AgentStore(conn).by_name(name)
            return bool(stored and stored.archived_at is None
                        and await AgentStore(conn).published(stored.id))  # fmt: skip

    async def _from_version(self, conn: Conn, version: Version, source: Source) -> Resolved:
        definition, issues = self.validate(
            AgentDocument.model_validate(version.document), version.number
        )
        if definition is None:  # e.g. a ceiling lowered since it was published
            raise AgentUnavailable("; ".join(str(i) for i in issues))
        digest = await snapshot_bundle(conn, definition)
        self._remember(digest, definition)
        return Resolved(definition, digest, version.number, source, version.agent_id)

    # ----------------------------------------------------------------- specs

    def spec_of(self, resolved: Resolved) -> GraphSpec:
        return self._remember(resolved.bundle_hash, resolved.definition)

    async def spec(self, bundle_hash: str) -> GraphSpec:
        """The compiled agent a run pinned (from its snapshot; any worker, any time)."""
        if (cached := self._specs.get(bundle_hash)) is not None:
            self._specs.move_to_end(bundle_hash)
            return cached
        async with self._pool.connection() as conn:
            definition = await load_bundle(conn, bundle_hash)
        return self._remember(bundle_hash, definition)

    def _remember(self, digest: str, definition: AgentDefinition) -> GraphSpec:
        from agent_runtime.graphs.assistant import agent_spec

        spec = self._specs.get(digest)
        if spec is None:
            spec = agent_spec(definition, self._tools)
            self._specs[digest] = spec
            while len(self._specs) > CACHE_SIZE:
                self._specs.popitem(last=False)
        return spec
