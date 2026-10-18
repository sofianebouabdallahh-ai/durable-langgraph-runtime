"""The Agent Studio's use cases (CR-006 R17.1 to R17.3, phase L3a). Pattern: Service Layer.

    create (blank, or a copy)  ─► draft ─save─► validate ─► test chat ─► publish ─► v N
                                    ▲                                              │
                                    └──────── edit / restore (a new draft) ◄───────┘

- One validator: a draft is checked by `validate_definition`, like a file. While it is
  valid it is snapshotted, and `bundle_hash` is what a test chat runs and what gets
  published.
- **Publish needs a test** (R17.3): a completed test-chat turn pinned to the draft's
  exact hash. Any edit changes the hash, so it needs a new test.
- A published version is immutable (AC47): the database refuses to change it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agent_runtime.agents.document import (
    AgentDocument,
    ImportRejected,
    from_definition,
    from_files,
    read_upload,
    to_files,
    to_zip,
)
from agent_runtime.agents.loader import Issue, validate_definition
from agent_runtime.agents.resolver import AgentResolver
from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.agents.store import snapshot_bundle
from agent_runtime.agents.studio_store import AgentStore, NameTaken, StoredAgent, Version
from agent_runtime.config import AgentSettings
from agent_runtime.db import Conn, Pool
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import Session

# ------------------------------------------------------------------ the catalog

# The tools a person picks from, in plain words. The sub-agent tools (spawn, wait,
# report, return) are granted automatically and never shown.
TOOLS: dict[str, tuple[str, str]] = {
    "search": ("Search", "Searches the documents it was given and cites them"),
    "calculator": ("Calculator", "Does exact arithmetic"),
    "save_note": ("Notes", "Keeps notes you ask it to remember"),
    "notify": ("Notifications", "Sends messages to people, always after you approve"),
}
# Protections: built-in hooks a person switches on or off (they never write hooks).
PROTECTIONS: dict[str, tuple[str, str, str, bool]] = {
    "redact_secrets_in_args": ("pre_tool", "Hide secrets sent to tools",
                               "Passwords and keys in what it sends to a tool are masked", True),
    "redact_secrets_in_result": ("post_tool", "Hide secrets in tool results",
                                 "Passwords and keys in what tools return are masked", True),
    "session_clock": ("session_start", "Know the date and time",
                      "Tells it the current date and time when a chat starts", True),
    "summarize_session": ("session_end", "Summarise each chat",
                          "Writes a short summary when a chat ends", False),
}  # fmt: skip
HELPER_HOOK_POINTS = frozenset({"pre_tool", "post_tool"})
PRESETS: dict[str, dict[str, Any]] = {
    "quick": {"max_turns": 8, "limits": {"max_tool_calls": 10, "timeout_s": 120}},
    "standard": {"max_turns": 20, "limits": {"max_tool_calls": 30, "timeout_s": 300}},
    "thorough": {"max_turns": 40, "limits": {"max_tool_calls": 50, "timeout_s": 600}},
}
HELPER_PRESET = {"max_turns": 6, "limits": {"max_tool_calls": 8, "timeout_s": 180}}


def presets(settings: AgentSettings) -> dict[str, dict[str, Any]]:
    """The presets, never above the server's ceilings (R14.3)."""

    def clamp(p: dict[str, Any]) -> dict[str, Any]:
        lim = p["limits"]
        return {
            "max_turns": min(p["max_turns"], settings.ceiling_model_calls),
            "limits": {
                "max_tool_calls": min(lim["max_tool_calls"], settings.ceiling_tool_calls),
                "timeout_s": min(lim["timeout_s"], settings.run_timeout_s),
            },
        }

    return {**{k: clamp(v) for k, v in PRESETS.items()}, "helper": clamp(HELPER_PRESET)}


# -------------------------------------------------------------------- results


@dataclass(frozen=True)
class PlainIssue:
    """An issue as the form shows it: which section, which field, in plain words."""

    where: str  # "agent" or "helpers.<name>"
    field: str | None  # the document's field ("instructions", "tools", "limits.timeout_s")
    message: str


@dataclass(frozen=True)
class Draft:
    version: Version
    issues: list[PlainIssue]
    tested: bool
    untested_models: list[str] = field(default_factory=list)  # connections not ready (R17.3)

    @property
    def blockers(self) -> list[str]:
        out: list[str] = []
        if self.issues:
            out.append("Fix the highlighted fields")
        out += [f"Test the model “{m}” (Settings → Models)" for m in self.untested_models]
        if not self.tested:
            out.append("Try it in the test chat (one complete reply)")
        return out


@dataclass(frozen=True)
class AgentState:
    agent: StoredAgent
    draft: Draft | None
    published: Version | None
    versions: list[Version] = field(default_factory=list)


class PublishBlocked(Exception):
    def __init__(self, blockers: list[str]) -> None:
        super().__init__("can't publish yet: " + "; ".join(blockers))
        self.blockers = blockers


class BuiltinName(ValueError):
    pass


# ------------------------------------------------------------------- the service


class StudioService:
    def __init__(
        self,
        pool: Pool,
        resolver: AgentResolver,
        sessions: SessionService,
        settings: AgentSettings,
    ) -> None:
        self._pool = pool
        self._agents = resolver
        self._sessions = sessions
        self._settings = settings

    # -------------------------------------------------------------- creating

    async def create(
        self, display_name: str, description: str = "", copy_of: str | None = None
    ) -> AgentState:
        """A new agent with a draft: blank, or a copy of a built-in or user agent."""
        async with self._pool.connection() as conn, conn.transaction():
            store = AgentStore(conn)
            name = await self._free_name(store, display_name)
            if copy_of is not None:
                document = await self._copy(store, copy_of, name)
                document = document.model_copy(update={"display_name": display_name[:60]})
            else:
                document = self._blank(name, display_name, description)
            agent, _ = await store.create(name, document.model_dump(mode="json"))
        return await self.save_draft(agent.id, document)

    def _blank(self, name: str, display_name: str, description: str) -> AgentDocument:
        standard = presets(self._settings)["standard"]
        hooks: dict[str, list[str]] = {}
        for hook, (point, _, _, default) in PROTECTIONS.items():
            if default:
                hooks.setdefault(point, []).append(hook)
        return AgentDocument(
            name=name,
            display_name=display_name[:60],
            description=description,
            instructions=(
                f"You are {display_name}. Today is {{{{date}}}}.\n\n"
                "Describe here what you do, how you answer, and what you never do."
            ),
            max_turns=standard["max_turns"],
            limits=standard["limits"],
            hooks=hooks,
        )

    async def _copy(self, store: AgentStore, source: str, name: str) -> AgentDocument:
        if (builtin := self._agents.builtin(source)) is not None:
            return from_definition(builtin, name=name)
        stored = await store.by_name(source)
        if stored is None:
            raise LookupError(f"unknown agent {source!r}")
        version = await store.draft(stored.id) or await store.published(stored.id)
        if version is None:
            raise LookupError(f"agent {source!r} has nothing to copy")
        return AgentDocument.model_validate({**version.document, "name": name})

    async def _free_name(self, store: AgentStore, display_name: str) -> str:
        base = slug(display_name)
        for n in range(1, 100):
            name = base if n == 1 else f"{base}-{n}"
            if self._agents.builtin(name) is None and await store.by_name(name) is None:
                return name
        raise NameTaken(base)

    # --------------------------------------------------------------- drafts

    async def get(self, agent_id: uuid.UUID) -> AgentState:
        async with self._pool.connection() as conn:
            store = AgentStore(conn)
            agent = await store.get(agent_id)
            versions = await store.versions(agent_id)
            draft_version = next((v for v in versions if v.state == "draft"), None)
            published = next((v for v in versions if v.state == "published"), None)
            draft = None
            if draft_version is not None:
                issues = self._check(draft_version.document, draft_version.number)[1]
                model_issues, untested = await self._models_of(conn, draft_version.document)
                tested = bool(draft_version.bundle_hash) and await store.tested(
                    agent_id, str(draft_version.bundle_hash)
                )
                draft = Draft(draft_version, issues + model_issues, tested, untested)
        return AgentState(agent, draft, published, versions)

    async def save_draft(self, agent_id: uuid.UUID, document: AgentDocument) -> AgentState:
        """Save the form (autosave). Valid → snapshotted, and its hash is what a test
        chat runs; invalid → saved anyway (a draft may be unfinished), issues returned."""
        async with self._pool.connection() as conn, conn.transaction():
            store = AgentStore(conn)
            agent = await store.get(agent_id)
            document = document.model_copy(update={"name": agent.name})  # the id is fixed
            draft = await store.open_draft(agent_id, document.model_dump(mode="json"))
            definition, _ = self._check(document.model_dump(mode="json"), draft.number)
            bundle = await snapshot_bundle(conn, definition) if definition else None
            await store.save_draft(agent_id, document.model_dump(mode="json"), bundle)
        return await self.get(agent_id)

    async def edit(self, agent_id: uuid.UUID) -> AgentState:
        """A draft to edit: the existing one, or a copy of the published version."""
        async with self._pool.connection() as conn, conn.transaction():
            store = AgentStore(conn)
            if await store.draft(agent_id) is None:
                published = await store.published(agent_id)
                if published is None:
                    raise LookupError("nothing to edit")
                await store.open_draft(agent_id, published.document)
        state = await self.get(agent_id)
        assert state.draft is not None
        return await self.save_draft(agent_id, AgentDocument.model_validate(
            state.draft.version.document))  # fmt: skip

    async def restore(self, agent_id: uuid.UUID, number: int) -> AgentState:
        """Version `number` becomes the draft (rolling back = restore, then publish)."""
        async with self._pool.connection() as conn:
            old = await AgentStore(conn).version(agent_id, number)
        if old is None:
            raise LookupError(f"no version {number}")
        return await self.save_draft(agent_id, AgentDocument.model_validate(old.document))

    async def discard(self, agent_id: uuid.UUID) -> AgentState:
        async with self._pool.connection() as conn, conn.transaction():
            store = AgentStore(conn)
            if await store.published(agent_id) is None:
                raise PublishBlocked(["An agent that was never published has only its draft"])
            await store.discard_draft(agent_id)
        return await self.get(agent_id)

    async def publish(self, agent_id: uuid.UUID, changelog: str | None) -> AgentState:
        state = await self.get(agent_id)
        if state.draft is None:
            raise PublishBlocked(["There are no changes to publish"])
        if state.draft.blockers:
            raise PublishBlocked(state.draft.blockers)
        async with self._pool.connection() as conn, conn.transaction():
            await AgentStore(conn).publish(agent_id, (changelog or "").strip()[:500] or None)
        return await self.get(agent_id)

    async def archive(self, agent_id: uuid.UUID) -> AgentState:
        async with self._pool.connection() as conn, conn.transaction():
            await AgentStore(conn).archive(agent_id)
        return await self.get(agent_id)

    def tool_risks(self) -> dict[str, str]:
        return dict(self._agents.catalog.tools)

    def builtin(self, name: str) -> AgentDefinition | None:
        return self._agents.builtin(name)

    def builtins(self) -> list[AgentDefinition]:
        return self._agents.builtins()

    async def published_definitions(self) -> list[tuple[AgentDefinition, int, uuid.UUID]]:
        """Every user agent people can chat with: its current version, validated."""
        out: list[tuple[AgentDefinition, int, uuid.UUID]] = []
        async with self._pool.connection() as conn:
            store = AgentStore(conn)
            for agent in await store.all():
                if agent.archived_at is not None:
                    continue
                version = await store.published(agent.id)
                if version is None:
                    continue
                definition, _ = self._check(version.document, version.number)
                if definition is not None:
                    out.append((definition, version.number, agent.id))
        return out

    async def all(self) -> list[AgentState]:
        async with self._pool.connection() as conn:
            agents = await AgentStore(conn).all()
        return [await self.get(a.id) for a in agents if a.archived_at is None]

    # ---------------------------------------------------------- test chats

    async def playground(self, agent_id: uuid.UUID) -> Session:
        """A new test chat with the draft (or, without one, the published version)."""
        async with self._pool.connection() as conn:
            agent = await AgentStore(conn).get(agent_id)
        return await self._sessions.create(agent.name, "Test chat", playground_of=agent_id)

    # ------------------------------------------------------- import / export

    async def export(self, agent_id: uuid.UUID, number: int | None) -> tuple[str, bytes, str]:
        """(filename, data, media type): a folder zip, or a single agent.md."""
        async with self._pool.connection() as conn:
            store = AgentStore(conn)
            agent = await store.get(agent_id)
            if number is not None:
                version = await store.version(agent_id, number)
            else:
                version = await store.draft(agent_id) or await store.published(agent_id)
        if version is None:
            raise LookupError("no such version")
        definition, issues = self._check(version.document, version.number)
        if definition is None:
            raise PublishBlocked([f"{i.where}: {i.message}" for i in issues])
        if definition.subagents:
            return f"{agent.name}.zip", to_zip(definition), "application/zip"
        (text,) = to_files(definition).values()
        return f"{agent.name}.agent.md", text.encode(), "text/markdown; charset=utf-8"

    async def import_(self, filename: str, data: bytes) -> AgentState:
        """A new agent from an uploaded agent.md or zipped folder, as a draft."""
        files = read_upload(filename, data)  # ImportRejected → 422
        main, helpers, problems = from_files(files)
        if main is None or problems:
            raise ImportRejected("; ".join(str(p) for p in problems) or "no agent found")
        definition, issues = validate_definition(
            main, helpers, self._agents.catalog, self._agents.ceilings
        )
        if definition is None:
            raise ImportRejected("; ".join(str(i) for i in issues))
        async with self._pool.connection() as conn, conn.transaction():
            store = AgentStore(conn)
            name = await self._free_name(store, definition.id)  # never replaces an agent
            document = from_definition(definition, name=name)
            agent, _ = await store.create(name, document.model_dump(mode="json"))
        return await self.save_draft(agent.id, document)

    # --------------------------------------------------------------- checks

    async def _models_of(
        self, conn: Conn, raw: dict[str, Any]
    ) -> tuple[list[PlainIssue], list[str]]:
        """The models a document names: an issue for a connection that doesn't exist,
        and the connections that haven't passed their test (publishing waits, R17.3)."""
        from agent_runtime.models.connections import ConnectionStore

        places = [("agent", raw.get("model", "chat"))]
        places += [
            (f"helpers.{h.get('name')}", h.get("model", "chat")) for h in raw.get("helpers") or []
        ]
        store = ConnectionStore(conn)
        issues: list[PlainIssue] = []
        untested: list[str] = []
        for where, model in places:
            if not isinstance(model, str) or ":" not in model:
                continue  # a role: the default model
            name = model.split(":", 1)[0]
            connection = await store.by_name(name)
            if connection is None:
                message = (f"There's no model connection called “{name}”: add it in "
                           "Settings → Models, or pick another")  # fmt: skip
                issues.append(PlainIssue(where, "model", message))
            elif connection.test_status != "ready" and connection.display_name not in untested:
                untested.append(connection.display_name)
        return issues, untested

    def _check(self, raw: dict[str, Any], version: int) -> tuple[Any, list[PlainIssue]]:
        try:
            document = AgentDocument.model_validate(raw)
        except ValidationError as exc:
            return None, [PlainIssue("agent", ".".join(str(p) for p in e["loc"]) or None,
                                     plain(e["msg"])) for e in exc.errors()]  # fmt: skip
        definition, issues = self._agents.validate(document, version)
        return definition, [_plain(i) for i in issues]


def _plain(issue: Issue) -> PlainIssue:
    field_ = "instructions" if issue.field == "prompt" else issue.field
    return PlainIssue(issue.path, field_, plain(issue.message))


_PLAIN = [
    (
        re.compile(r"unknown placeholder (\{\{[^}]*\}\}).*"),
        r"\1 isn't something it can fill in: use the Insert buttons below the instructions.",
    ),
    (
        re.compile(r"'(\w+)' needs human approval; sub-agents can't use it"),
        r"Helpers can't use \1: it needs your approval, and only the main agent can ask for it.",
    ),
    (re.compile(r"unknown tool '(\w+)'"), r"There's no tool called \1."),
    (re.compile(r"(\d+) exceeds the server ceiling (\d+)"), r"At most \2 here (\1 is too many)."),
    (re.compile(r"String should have at least 1 character"), "Required."),
    (re.compile(r"String should match pattern"), "Use lowercase letters, digits and dashes."),
    (re.compile(r"the body \(system prompt\) is empty"), "Write the instructions."),
    (re.compile(r"String should have at most (\d+) characters"), r"At most \1 characters."),
    (re.compile(r"Input should be greater than 0"), "Must be more than 0."),
]


def plain(message: str) -> str:
    """The validator's messages, as a person reads them next to a field."""
    for pattern, replacement in _PLAIN:
        if pattern.search(message):
            out = pattern.sub(replacement, message) if "\\" in replacement else replacement
            for tool, (label, _) in TOOLS.items():  # tools by the names people see
                out = re.sub(rf"\b{tool}\b", label, out)
            return out
    return message[:1].upper() + message[1:]


def slug(text: str) -> str:
    """'Trip Planner!' → 'trip-planner' (an agent's fixed id)."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:40].strip("-")
    if not s or not s[0].isalpha():
        s = f"agent-{s}" if s else "agent"
    return s
