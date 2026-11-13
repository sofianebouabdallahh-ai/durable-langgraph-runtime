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

import contextlib
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from agent_runtime.agents import builder
from agent_runtime.agents.document import (
    AgentDocument,
    ImportRejected,
    from_definition,
    from_files,
    read_skill_folders,
    read_upload,
    to_files,
    to_zip,
)
from agent_runtime.agents.loader import Issue, validate_definition
from agent_runtime.agents.resolver import AgentResolver
from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.agents.store import bundle_digest, snapshot_bundle
from agent_runtime.agents.studio_store import AgentStore, NameTaken, StoredAgent, Version
from agent_runtime.audit import Action, AuditLog
from agent_runtime.config import AgentSettings
from agent_runtime.db import Conn, Pool
from agent_runtime.evals.store import EvalStore
from agent_runtime.ids import new_id
from agent_runtime.mcp import tools as mcp_tools
from agent_runtime.runs.service import RunService
from agent_runtime.runs.store import Run, RunRepository
from agent_runtime.sandbox.tools import SANDBOX_TOOLS
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import Session, SessionRepository
from agent_runtime.skills import spec as skill_spec
from agent_runtime.skills.binding import MissingSkills, bind, lock_of
from agent_runtime.skills.scan import ScanReport, scan
from agent_runtime.skills.spec import SkillContent
from agent_runtime.skills.store import SkillStore
from agent_runtime.tools.spec import RiskClass

# ------------------------------------------------------------------ the catalog

# The tools a person picks from, in plain words. The sub-agent tools (spawn, wait,
# report, return) are granted automatically and never shown.
TOOLS: dict[str, tuple[str, str]] = {
    "web_search": ("Search the web", "Finds pages on the web, so it can cite them"),
    "read_webpage": ("Read web pages", "Reads a page or a PDF as text"),
    "run_python": (
        "Run Python",
        "Runs Python (with numpy and pandas) in a sandbox: no internet, no access to your files",
    ),
    "run_shell": ("Use a terminal", "Runs commands in the same sandbox"),
    "workspace_files": ("Work with files", "Keeps files in the sandbox while it works"),
    "save_note": ("Notes", "Keeps notes you ask it to remember"),
    "notify": ("Notifications", "Sends messages to people, always after you approve"),
}
# Protections: built-in hooks a person switches on or off (they never write hooks).
PROTECTIONS: dict[str, tuple[str, str, str, bool]] = {
    "redact_secrets_in_args": ("pre_tool", "Hide secrets sent to tools",
                               "Passwords and keys in what it sends to a tool are masked", True),
    "redact_secrets_in_result": ("post_tool", "Hide secrets in tool results",
                                 "Passwords and keys in what tools return are masked", True),
    "redact_secrets_in_reply": ("post_model", "Hide secrets in its replies",
                                "Passwords and keys it writes are masked; replies then "
                                "appear whole, not word by word", False),
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
    tests: int = 0  # its test cases (H6)
    tests_failing: list[str] = field(default_factory=list)  # not passed on this draft
    digest: str | None = None  # the bundle a test chat runs now (tests are graded on it)
    # Skills it uses whose current version nobody has read (H10 2.2): they work as data
    # until the person approves them on the Skills page. Not a blocker: data is safe.
    skills_unread: list[str] = field(default_factory=list)

    @property
    def blockers(self) -> list[str]:
        out: list[str] = []
        if self.issues:
            out.append("Fix the highlighted fields")
        out += [f"Test the model “{m}” (Settings → Models)" for m in self.untested_models]
        if self.tests:  # its tests are the gate (H6); each one is a test-chat reply
            if self.tests_failing:
                n = len(self.tests_failing)
                tests = f"{n} tests haven't" if n > 1 else "1 test hasn't"
                out.append(f"{tests} passed on this draft: " + ", ".join(self.tests_failing[:5]))
        elif not self.tested:
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


@dataclass(frozen=True)
class Assist:
    """Where a "Describe it" or "Improve my instructions" request is."""

    status: Literal["working", "done", "failed"]
    kind: Literal["draft", "instructions"]
    proposal: dict[str, Any] | None = None
    problem: str | None = None
    repairs: list[str] = field(default_factory=list)  # what was fixed in the proposal


# ------------------------------------------------------------------- the service


class StudioService:
    def __init__(
        self,
        pool: Pool,
        resolver: AgentResolver,
        sessions: SessionService,
        settings: AgentSettings,
        runs: RunService | None = None,
        *,
        sandbox: bool = False,
    ) -> None:
        self._pool = pool
        self._agents = resolver
        self._sessions = sessions
        self._settings = settings
        self._runs = runs
        self._sandbox = sandbox  # sandboxd is set up: the code tools can be offered

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
            await AuditLog(conn).record("agent.created", "agent", name, after={
                "display_name": document.display_name, "copy_of": copy_of})  # fmt: skip
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

    # ---------------------------------------------- describe it, improve it

    async def _offered_now(self) -> list[str]:
        """The Studio's tools plus the MCP tools switched on now."""
        async with self._pool.connection() as conn:
            return [*self.offered_tools(), *await mcp_tools.usable(conn)]

    def offered_tools(self) -> list[str]:
        """The Studio's tools this installation has: the code tools only with a sandbox."""
        risks = self.tool_risks()
        return [n for n in TOOLS if n in risks and (n not in SANDBOX_TOOLS or self._sandbox)]

    async def describe(self, description: str) -> Run:
        """Start the builder agent on a description (R17.3). Nothing is saved: the
        result is a proposal (`assist`), which `create_from_proposal` turns into a draft."""
        skills = await self._library()
        offered = self.offered_tools()
        async with self._pool.connection() as conn:
            mcp = await mcp_tools.usable(conn)
        message = builder.describe_message(
            description, skills, offered, {n: t.definition.description for n, t in mcp.items()}
        )
        script = builder.demo_script(builder.demo_draft(description, skills, offered))
        return await self._assist_run(builder.BUILDER, message, script)

    async def improve(self, agent_id: uuid.UUID) -> Run:
        """Start the instructions coach on this agent's draft (or published) instructions."""
        async with self._pool.connection() as conn:
            store = AgentStore(conn)
            version = await store.draft(agent_id) or await store.published(agent_id)
        if version is None:
            raise LookupError("nothing to improve")
        doc = AgentDocument.model_validate(version.document)
        message = builder.improve_message(
            doc.display_name or doc.name, doc.description, doc.instructions,
            [t.name for t in doc.tools],
        )  # fmt: skip
        script = builder.demo_script(
            builder.demo_improve(doc.instructions, doc.display_name or doc.name)
        )
        return await self._assist_run(builder.COACH, message, script)

    async def assist(self, run_id: uuid.UUID) -> Assist:
        """The builder's answer, once there is one."""
        async with self._pool.connection() as conn:
            repo = RunRepository(conn)
            run = await repo.get(run_id)
            if run.graph_name not in (builder.BUILDER, builder.COACH):
                raise LookupError(f"run {run_id} isn't a Studio assist")
            result = await repo.get_result(run_id) if run.status.is_terminal else None
        kind: Literal["draft", "instructions"] = (
            "draft" if run.graph_name == builder.BUILDER else "instructions"
        )
        if not run.status.is_terminal:
            return Assist("working", kind)
        proposal = (result or {}).get("output", {}).get("proposal") if result else None
        if run.status.value == "completed" and proposal:
            repairs = list(proposal.pop("repairs", []) or [])
            if kind == "draft":  # only tools this installation has (and its MCP tools)
                draft = builder.DraftProposal.model_validate(proposal)
                proposal = builder.only_offered(draft, await self._offered_now()).model_dump()
            return Assist("done", kind, proposal, repairs=repairs)
        problem = (
            "The model didn't come up with a proposal. Try again, or describe it a little "
            "differently (a model that passed its test in Settings → Models works best)."
            if run.status.value == "completed"
            else f"It didn't finish ({plain(run.reason or run.status.value)}). Try again."
        )
        return Assist("failed", kind, None, problem)

    async def create_from_proposal(self, proposal: builder.DraftProposal) -> AgentState:
        """A new agent whose draft is the builder's proposal (skills it named that aren't
        in the library are left out)."""
        library = {n for n, _ in await self._library()}
        proposal = builder.only_offered(proposal, await self._offered_now()).model_copy(update={
            "skills": [s for s in proposal.skills if s in library]})  # fmt: skip
        async with self._pool.connection() as conn, conn.transaction():
            store = AgentStore(conn)
            name = await self._free_name(store, proposal.display_name)
            mcp = mcp_tools.risks(await mcp_tools.usable(conn))
            document = AgentDocument.model_validate(
                builder.to_document(proposal, name, self._settings, mcp)
            )
            agent, _ = await store.create(name, document.model_dump(mode="json"))
        return await self.save_draft(agent.id, document)

    async def _library(self) -> list[tuple[str, str]]:
        async with self._pool.connection() as conn:
            store = SkillStore(conn)
            skills = await store.all()
            versions = await store.versions(s.current_hash for s in skills)
        return [(s.name, versions[s.current_hash].description) for s in skills]

    async def _assist_run(self, graph: str, message: str, script: list[dict[str, Any]]) -> Run:
        if self._runs is None:
            raise RuntimeError("the Studio needs the run service to start a builder")
        inp: dict[str, Any] = {"message": message}
        if getattr(self._settings, "model_provider", "scripted") == "scripted":
            inp["script"] = script  # the offline demo: a deterministic proposal
        return await self._runs.create_run(graph, inp)

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
                available = await mcp_tools.usable(conn)
                definition, issues = self._check(
                    draft_version.document, draft_version.number, mcp_tools.risks(available)
                )
                model_issues, untested = await self._models_of(conn, draft_version.document)
                skill_issues, unread = await self._skills_of(conn, draft_version.document)
                # "Tested" means: this exact draft with the library's skills and the MCP
                # tools as they are now. A skill edited, or an MCP tool approved again,
                # since the test makes it untested (the hash moves).
                tested, current = False, None
                cases = await EvalStore(conn).cases(agent_id)
                failing = [c.case.name for c in cases]
                if definition is not None and not skill_issues:
                    mcp = mcp_tools.lock(available, mcp_tools.granted(definition))
                    current = bundle_digest(definition, await bind(conn, definition, None), mcp)
                    tested = await store.tested(agent_id, current)
                    failing = await EvalStore(conn).failing(agent_id, current)
                draft = Draft(draft_version, issues + model_issues + skill_issues, tested, untested,
                              tests=len(cases), tests_failing=failing, digest=current,
                              skills_unread=unread)  # fmt: skip
        return AgentState(agent, draft, published, versions)

    async def save_draft(
        self,
        agent_id: uuid.UUID,
        document: AgentDocument,
        *,
        audited: tuple[Action, dict[str, Any]] | None = None,
    ) -> AgentState:
        """Save the form (autosave). Valid → snapshotted, and its hash is what a test
        chat runs; invalid → saved anyway (a draft may be unfinished), issues returned.
        `audited`: a change to record with it (a restore), in the same transaction."""
        async with self._pool.connection() as conn, conn.transaction():
            store = AgentStore(conn)
            agent = await store.get(agent_id)
            if audited is not None:
                await AuditLog(conn).record(audited[0], "agent", agent.name, after=audited[1])
            document = document.model_copy(update={"name": agent.name})  # the id is fixed
            draft = await store.open_draft(agent_id, document.model_dump(mode="json"))
            available = await mcp_tools.usable(conn)
            definition, _ = self._check(
                document.model_dump(mode="json"), draft.number, mcp_tools.risks(available)
            )
            bundle = None
            if definition is not None:
                # A missing skill is an issue on the form until it exists again.
                with contextlib.suppress(MissingSkills):
                    bundle = await snapshot_bundle(
                        conn, definition, await bind(conn, definition, None),
                        mcp_tools.lock(available, mcp_tools.granted(definition)),
                    )  # fmt: skip
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
        return await self.save_draft(
            agent_id, AgentDocument.model_validate(old.document),
            audited=("agent.restored", {"version": number}),
        )  # fmt: skip

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
        version = state.draft.version
        async with self._pool.connection() as conn, conn.transaction():
            store = AgentStore(conn)
            available = await mcp_tools.usable(conn)
            definition, _ = self._check(version.document, version.number,
                                        mcp_tools.risks(available))  # fmt: skip
            assert definition is not None  # no blockers: it validated
            skills = await bind(conn, definition, None)
            mcp = mcp_tools.lock(available, mcp_tools.granted(definition))
            digest = await snapshot_bundle(conn, definition, skills, mcp)
            if state.draft.tests:  # its tests are the gate (H6), on exactly this bundle
                if failing := await EvalStore(conn).failing(agent_id, digest):
                    raise PublishBlocked([f"Its tests haven't all passed on this draft: "
                                          f"{', '.join(failing[:5])}"])  # fmt: skip
            elif not await store.tested(agent_id, digest):  # changed since get()
                raise PublishBlocked(["A skill or an MCP tool changed since the test: "
                                      "test it again"])  # fmt: skip
            note = (changelog or "").strip()[:500] or None
            await store.publish(agent_id, note, digest, lock_of(skills), mcp)
            await AuditLog(conn).record("agent.published", "agent", state.agent.name, after={
                "version": version.number, "changelog": note, "bundle": digest})  # fmt: skip
        return await self.get(agent_id)

    async def archive(self, agent_id: uuid.UUID) -> AgentState:
        async with self._pool.connection() as conn, conn.transaction():
            agent = await AgentStore(conn).get(agent_id)
            await AgentStore(conn).archive(agent_id)
            await AuditLog(conn).record("agent.archived", "agent", agent.name)
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
                locked = mcp_tools.risks(mcp_tools.unlock(version.mcp_lock))
                definition, _ = self._check(version.document, version.number, locked)
                if definition is not None:
                    out.append((definition, version.number, agent.id))
        return out

    async def all(self) -> list[AgentState]:
        async with self._pool.connection() as conn:
            agents = await AgentStore(conn).all()
        return [await self.get(a.id) for a in agents if a.archived_at is None]

    # ---------------------------------------------------------- test chats

    async def last_playground(self, agent_id: uuid.UUID) -> Session | None:
        """The test chat to show again when the Studio opens: the latest still open."""
        async with self._pool.connection() as conn:
            await AgentStore(conn).get(agent_id)  # AgentNotFound → 404
            return await SessionRepository(conn).latest_test_chat(agent_id)

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
        if version.state == "draft":
            async with self._pool.connection() as conn:
                mcp = mcp_tools.risks(await mcp_tools.usable(conn))
        else:
            mcp = mcp_tools.risks(mcp_tools.unlock(version.mcp_lock))
        definition, issues = self._check(version.document, version.number, mcp)
        if definition is None:
            raise PublishBlocked([f"{i.where}: {i.message}" for i in issues])
        skills = await self._skill_contents(definition, version)
        if definition.subagents or skills:
            return f"{agent.name}.zip", to_zip(definition, skills), "application/zip"
        (text,) = to_files(definition).values()
        return f"{agent.name}.agent.md", text.encode(), "text/markdown; charset=utf-8"

    async def import_(self, filename: str, data: bytes) -> AgentState:
        """A new agent from an uploaded agent.md or zipped folder, as a draft. The skills
        it carries enter the library unread (H10 2.2): they work as data until a person
        opens each one and approves it, and the draft names them (`skills_unread`)."""
        files = read_upload(filename, data)  # ImportRejected → 422
        main, helpers, problems = from_files(files)
        if main is None or problems:
            raise ImportRejected("; ".join(str(p) for p in problems) or "no agent found")
        definition, issues = validate_definition(
            main, helpers, self._agents.catalog, self._agents.ceilings
        )
        if definition is None:
            raise ImportRejected("; ".join(str(i) for i in issues))
        carried = self._carried_skills(filename, data)
        async with self._pool.connection() as conn, conn.transaction():
            await self._import_skills(SkillStore(conn), carried)
            store = AgentStore(conn)
            name = await self._free_name(store, definition.id)  # never replaces an agent
            document = from_definition(definition, name=name)
            agent, _ = await store.create(name, document.model_dump(mode="json"))
            await AuditLog(conn).record("agent.imported", "agent", name, after={
                "file": filename[:200], "skills": [c.name for c, _ in carried]})  # fmt: skip
        return await self.save_draft(agent.id, document)

    # --------------------------------------------------------------- skills in files

    async def _skill_contents(self, definition: Any, version: Version) -> list[SkillContent]:
        """The skills an exported version uses: its locked versions once published,
        the library's current ones for a draft."""
        lock = version.skill_lock if version.state != "draft" else None
        async with self._pool.connection() as conn:
            skills = await bind(conn, definition, lock)
            store = SkillStore(conn)
            hashes = list(dict.fromkeys(v.hash for vs in skills.values() for v in vs))
            return [await store.content(h) for h in hashes]

    @staticmethod
    def _carried_skills(filename: str, data: bytes) -> list[tuple[SkillContent, ScanReport]]:
        """The skills in an uploaded agent zip, checked and scanned like any upload."""
        out: list[tuple[SkillContent, ScanReport]] = []
        for folder, files in read_skill_folders(filename, data).items():
            content, issues = skill_spec.parse(files, folder)
            if content is None:
                problems = "; ".join(i.message for i in issues if i.blocking)
                raise ImportRejected(f"the skill “{folder}” can't be read: {problems}")
            report = scan(content)
            if report.status == "blocked":
                raise ImportRejected(f"the skill “{folder}” contains what looks like a secret: "
                                     "remove it and export again")  # fmt: skip
            out.append((content, report))
        return out

    @staticmethod
    async def _import_skills(
        store: SkillStore, carried: list[tuple[SkillContent, ScanReport]]
    ) -> None:
        """Into the library: new ones are added; the same content is reused; a different
        skill with the same name refuses the import (an agent must not silently get
        someone else's know-how)."""
        for content, report in carried:
            existing = await store.by_name(content.name, archived=True)
            if existing is None:
                digest = await store.put_version(content, report)
                await store.insert(new_id(), content.name, "private", "imported", digest)
            elif existing.current_hash != content.content_hash():
                raise ImportRejected(
                    f"your library already has a different skill called “{content.name}”: "
                    "rename one of them, then import again"
                )

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

    async def _skills_of(
        self, conn: Conn, raw: dict[str, Any]
    ) -> tuple[list[PlainIssue], list[str]]:
        """An issue for each skill the document names that isn't in the library, and the
        names of those nobody has read yet (their current version isn't approved, H10
        2.2): they work as data until then, so they're told, not blocked."""
        places = [("agent", raw.get("skills") or [])]
        places += [(f"helpers.{h.get('name')}", h.get("skills") or [])
                   for h in raw.get("helpers") or []]  # fmt: skip
        wanted = {n for _, names in places for n in names if isinstance(n, str)}
        store = SkillStore(conn)
        found = await store.by_names(wanted) if wanted else {}
        read = await store.approved(s.current_hash for s in found.values()) if found else set()
        issues = [
            PlainIssue(
                where,
                "skills",
                f"There's no skill called “{name}” in your library: "
                "add it on the Skills page, or remove it here",
            )
            for where, names in places
            for name in names
            if isinstance(name, str) and name not in found
        ]
        return issues, sorted(n for n, s in found.items() if s.current_hash not in read)

    def _check(
        self, raw: dict[str, Any], version: int, mcp: Mapping[str, RiskClass] | None = None
    ) -> tuple[Any, list[PlainIssue]]:
        try:
            document = AgentDocument.model_validate(raw)
        except ValidationError as exc:
            return None, [PlainIssue("agent", ".".join(str(p) for p in e["loc"]) or None,
                                     plain(e["msg"])) for e in exc.errors()]  # fmt: skip
        definition, issues = self._agents.validate(document, version, mcp)
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
