"""Which agent a turn runs, pinned by hash (CR-004 R15.4, CR-006 R17.1).

    resolve(name)          a built-in (files) or a user agent's published version
    resolve(name, draft)   a user agent's draft (its test chat)
        → validate (the one validator) → snapshot the bundle → bundle hash
    spec(bundle hash)      the compiled agent, rebuilt from the snapshots, cached

A run stores the bundle hash when it is created, and every worker builds the agent
from that snapshot. So:
- publishing a new version never changes a running turn; the next turn uses it (AC47);
- a built-in file edited during a rolling upgrade can't change a queued turn (R15.4);
- skills are in the bundle too, as exact versions: a draft takes the library's current
  ones, a published version the ones it locked (CR-006 R17.4);
- so are MCP tools (L8), as the definitions people approved: a draft takes the tools
  switched on now, a published version the ones it locked.

Patterns: Registry (two sources behind one lookup); content-addressed snapshots;
memoised factory (one compiled spec per hash per process: specs are immutable).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from agent_runtime.agents.document import AgentDocument, to_raw
from agent_runtime.agents.loader import Catalog, Ceilings, Issue, validate_definition
from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.agents.store import load_bundle, snapshot_bundle
from agent_runtime.agents.studio_store import AgentStore, Version
from agent_runtime.catalog import default_catalog
from agent_runtime.config import get_agent_settings
from agent_runtime.db import Conn, Pool
from agent_runtime.graphs import GraphRegistry, GraphSpec
from agent_runtime.mcp import tools as mcp_tools
from agent_runtime.skills.binding import MissingSkills, SkillSet, bind
from agent_runtime.tools.spec import RiskClass, ToolRegistry

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
    skills: SkillSet = field(default_factory=dict)
    mcp: Mapping[str, Any] = field(default_factory=dict)  # MCP tool → locked definition


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

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    @property
    def ceilings(self) -> Ceilings:
        return self._ceilings

    # --------------------------------------------------------------- lookups

    def builtins(self) -> list[AgentDefinition]:
        return [s.agent for s in self._graphs if s.agent is not None]

    def builtin(self, name: str) -> AgentDefinition | None:
        try:
            return self._graphs.get(name).agent
        except LookupError:
            return None

    def validate(
        self, document: AgentDocument, version: int, mcp: Mapping[str, RiskClass] | None = None
    ) -> tuple[AgentDefinition | None, list[Issue]]:
        """`mcp`: the MCP tools it may use (name → risk class), besides the built-in ones."""
        main, helpers = to_raw(document, version)
        catalog = self._catalog
        if mcp:
            catalog = replace(catalog, tools={**catalog.tools, **mcp})
        return validate_definition(main, helpers, catalog, self._ceilings)

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
            skills = await self._bind(conn, builtin, None)
            digest = await snapshot_bundle(conn, builtin, skills)
            self._remember(digest, builtin, skills)
            return Resolved(builtin, digest, builtin.frontmatter.version, "builtin", None, skills)
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
        draft = version.state == "draft"
        available = await mcp_tools.usable(conn) if draft else mcp_tools.unlock(version.mcp_lock)
        definition, issues = self.validate(
            AgentDocument.model_validate(version.document), version.number,
            mcp_tools.risks(available),
        )  # fmt: skip
        if definition is None:  # e.g. a ceiling lowered since it was published
            raise AgentUnavailable("; ".join(str(i) for i in issues))
        skills = await self._bind(conn, definition, None if draft else version.skill_lock)
        mcp = mcp_tools.lock(available, mcp_tools.granted(definition))
        digest = await snapshot_bundle(conn, definition, skills, mcp)
        self._remember(digest, definition, skills, mcp)
        return Resolved(definition, digest, version.number, source, version.agent_id, skills,
                        mcp)  # fmt: skip

    @staticmethod
    async def _bind(
        conn: Conn, definition: AgentDefinition, lock: dict[str, str] | None
    ) -> SkillSet:
        try:
            return await bind(conn, definition, lock)
        except MissingSkills as exc:
            raise AgentUnavailable(str(exc)) from exc

    # ----------------------------------------------------------------- specs

    def spec_of(self, resolved: Resolved) -> GraphSpec:
        return self._remember(resolved.bundle_hash, resolved.definition, resolved.skills,
                              resolved.mcp)  # fmt: skip

    async def spec(self, bundle_hash: str) -> GraphSpec:
        """The compiled agent a run pinned (from its snapshot; any worker, any time)."""
        if (cached := self._specs.get(bundle_hash)) is not None:
            self._specs.move_to_end(bundle_hash)
            return cached
        async with self._pool.connection() as conn:
            bundle = await load_bundle(conn, bundle_hash)
        return self._remember(bundle_hash, bundle.definition, bundle.skills, bundle.mcp)

    def _remember(
        self,
        digest: str,
        definition: AgentDefinition,
        skills: SkillSet | None = None,
        mcp: Mapping[str, Any] | None = None,
    ) -> GraphSpec:
        from agent_runtime.graphs.assistant import agent_spec

        spec = self._specs.get(digest)
        if spec is None:
            tools = mcp_tools.registry_with(self._tools, mcp_tools.unlock(mcp))
            spec = agent_spec(definition, tools, skills or {})
            self._specs[digest] = spec
            while len(self._specs) > CACHE_SIZE:
                self._specs.popitem(last=False)
        return spec
