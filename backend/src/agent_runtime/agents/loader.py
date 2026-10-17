"""Load and validate agent folders into an `AgentRegistry` (R15.2, R16.1, R16.2).

Layout (CR-005):

    agents/
      <main>/agent.md            a main agent
      <main>/<sub>/agent.md      a sub-agent of <main>: a leaf, no folders below

Every problem is collected, not just the first, so one `runtime agents validate`
run shows everything to fix. Loading succeeds only with zero issues: services
refuse to start on a broken definition (fail fast).

Patterns:
- Registry: `AgentRegistry` is the single lookup point for definitions.
- Dependency inversion: what counts as a known tool, hook, schema or model is
  supplied as a `Catalog`. Later phases register tools and hooks without the
  loader changing.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import frontmatter
import yaml
from pydantic import ValidationError

from agent_runtime.agents.schema import (
    MAIN_PLACEHOLDERS,
    PLACEHOLDER,
    SUB_PLACEHOLDERS,
    AgentDefinition,
    MainAgentFrontmatter,
    SubAgentDefinition,
    SubAgentFrontmatter,
)
from agent_runtime.config import AgentSettings

DEFINITION_FILE = "agent.md"
EXPLICIT_MODEL = re.compile(r"^[a-z0-9_-]+:[\w.\-/:]+$")  # "provider:model-id"

RiskClass = Literal["read", "write_internal", "execute", "external_side_effect"]
HookPoint = Literal[
    "session_start", "turn_start", "pre_model", "post_model",
    "pre_tool", "post_tool", "turn_end", "session_end", "on_error",
]  # fmt: skip


@dataclass(frozen=True)
class Catalog:
    """What definitions may reference. Grows as phases register tools and hooks."""

    tools: Mapping[str, RiskClass] = field(default_factory=dict)
    hooks: Mapping[str, HookPoint] = field(default_factory=dict)
    output_schemas: frozenset[str] = frozenset()
    model_aliases: frozenset[str] = frozenset(
        {"chat", "planner", "researcher", "critic", "synthesizer"}
    )


@dataclass(frozen=True)
class Ceilings:
    """Server-side maxima (R14.3). Definitions may only go below them."""

    model_calls: int
    tool_calls: int
    tokens: int
    cost_usd: float
    timeout_s: int

    @classmethod
    def from_settings(cls, settings: AgentSettings) -> Ceilings:
        return cls(
            model_calls=settings.ceiling_model_calls,
            tool_calls=settings.ceiling_tool_calls,
            tokens=settings.ceiling_tokens,
            cost_usd=settings.ceiling_cost_usd,
            timeout_s=settings.run_timeout_s,
        )


@dataclass(frozen=True)
class Issue:
    path: str
    field: str | None
    message: str

    def __str__(self) -> str:
        where = f"{self.path}: {self.field}" if self.field else self.path
        return f"{where}: {self.message}"


class AgentValidationError(Exception):
    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        lines = "\n".join(f"  - {i}" for i in issues)
        super().__init__(f"{len(issues)} agent definition problem(s):\n{lines}")


class UnknownAgent(LookupError):
    pass


class AgentRegistry:
    """Immutable set of validated main agents, keyed by name."""

    def __init__(self, agents: Mapping[str, AgentDefinition]) -> None:
        self._agents = dict(agents)

    def get(self, name: str) -> AgentDefinition:
        try:
            return self._agents[name]
        except KeyError:
            raise UnknownAgent(f"unknown agent {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._agents)

    def __iter__(self) -> Iterator[AgentDefinition]:
        return iter(self._agents[n] for n in self.names())

    def __len__(self) -> int:
        return len(self._agents)


# ------------------------------------------------------------------- loading


def load_agents(root: Path, catalog: Catalog, ceilings: Ceilings) -> AgentRegistry:
    issues: list[Issue] = []
    agents: dict[str, AgentDefinition] = {}
    if not root.is_dir():
        raise AgentValidationError([Issue(str(root), None, "agents directory not found")])

    for main_dir in _agent_dirs(root):
        main = _load_main(root, main_dir, catalog, ceilings, issues)
        if main is not None:
            agents[main.id] = main

    if issues:
        raise AgentValidationError(issues)
    return AgentRegistry(agents)


def _agent_dirs(parent: Path) -> list[Path]:
    return sorted(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


@dataclass(frozen=True)
class RawDefinition:
    """One agent or helper before validation, from any source (a folder, the Studio).

    `name` is what the definition must be called (its folder, or the Studio's id);
    `where` labels its issues ("chat/agent.md", or "helpers.researcher")."""

    name: str
    metadata: Mapping[str, Any]
    prompt: str
    where: str
    name_of: str = "the folder name"  # what `name` is, in messages


def validate_definition(
    main: RawDefinition,
    helpers: list[RawDefinition],
    catalog: Catalog,
    ceilings: Ceilings,
) -> tuple[AgentDefinition | None, list[Issue]]:
    """The one definition of "valid" (CR-006 R17.1): files and the Studio both come
    through here. Pattern: Specification. Returns the definition, or every issue."""
    issues: list[Issue] = []
    subagents: list[SubAgentDefinition] = []
    seen: set[str] = set()
    for raw in helpers:
        if raw.name in seen:
            issues.append(Issue(raw.where, "name", f"two helpers are called {raw.name!r}"))
            continue
        seen.add(raw.name)
        fm = _frontmatter(raw, SubAgentFrontmatter, issues)
        if fm is None:
            continue
        _check_common(raw.where, fm, raw.prompt, SUB_PLACEHOLDERS, catalog, ceilings, issues)
        for grant in fm.tools:
            if catalog.tools.get(grant.name) == "external_side_effect":
                message = f"{grant.name!r} needs human approval; sub-agents can't use it"
                issues.append(Issue(raw.where, "tools", message))
        subagents.append(SubAgentDefinition(id=f"{main.name}/{raw.name}", frontmatter=fm,
                                            prompt=raw.prompt))  # fmt: skip
    fm_main = _frontmatter(main, MainAgentFrontmatter, issues)
    if fm_main is not None:
        _check_common(main.where, fm_main, main.prompt, MAIN_PLACEHOLDERS, catalog, ceilings,
                      issues)  # fmt: skip
    if issues or fm_main is None:
        return None, issues
    return AgentDefinition(id=main.name, frontmatter=fm_main, prompt=main.prompt,
                           subagents=tuple(subagents)), []  # fmt: skip


def _frontmatter[F: (MainAgentFrontmatter, SubAgentFrontmatter)](
    raw: RawDefinition, model: type[F], issues: list[Issue]
) -> F | None:
    try:
        fm = model.model_validate(dict(raw.metadata))
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or None
            issues.append(Issue(raw.where, loc, err["msg"]))
        return None
    if fm.name != raw.name:
        issues.append(Issue(raw.where, "name", f"must match {raw.name_of} {raw.name!r}"))
    return fm


def _load_main(
    root: Path, main_dir: Path, catalog: Catalog, ceilings: Ceilings, issues: list[Issue]
) -> AgentDefinition | None:
    helpers: list[RawDefinition] = []
    for sub_dir in _agent_dirs(main_dir):
        for nested in sub_dir.rglob(DEFINITION_FILE):
            if nested.parent == sub_dir:
                continue  # the sub-agent's own definition
            issues.append(
                Issue(_rel(root, nested), None, "sub-agents are leaf agents: no nested agents")
            )
        if (raw := _read(root, sub_dir, issues)) is not None:
            helpers.append(raw)
    main = _read(root, main_dir, issues)
    if main is None:
        return None
    defn, problems = validate_definition(main, helpers, catalog, ceilings)
    issues.extend(problems)
    return defn


def _read(root: Path, folder: Path, issues: list[Issue]) -> RawDefinition | None:
    """A folder's agent.md as a RawDefinition (file problems are reported here)."""
    path = folder / DEFINITION_FILE
    rel = _rel(root, path)
    if not path.is_file():
        issues.append(Issue(_rel(root, folder), None, f"agent folder has no {DEFINITION_FILE}"))
        return None
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))  # yaml.SafeLoader
    except yaml.YAMLError as exc:
        issues.append(Issue(rel, None, f"invalid YAML frontmatter: {exc}"))
        return None
    if not isinstance(post.metadata, dict):
        issues.append(Issue(rel, None, "the frontmatter must be a mapping"))
        return None
    return RawDefinition(folder.name, post.metadata, post.content.strip(), rel)


def _check_common(
    rel: str,
    fm: MainAgentFrontmatter | SubAgentFrontmatter,
    prompt: str,
    placeholders: frozenset[str],
    catalog: Catalog,
    ceilings: Ceilings,
    issues: list[Issue],
) -> None:

    def bad(field_: str, message: str) -> None:
        issues.append(Issue(rel, field_, message))

    if fm.model not in catalog.model_aliases and not EXPLICIT_MODEL.match(fm.model):
        bad("model", f"unknown model alias {fm.model!r} (use an alias or 'provider:model-id')")
    for grant in fm.tools:
        if grant.name not in catalog.tools:
            bad("tools", f"unknown tool {grant.name!r}")
    for point, names in fm.hooks.model_dump().items():
        for name in names:
            registered = catalog.hooks.get(name)
            if registered is None:
                bad(f"hooks.{point}", f"unknown hook {name!r}")
            elif registered != point:
                bad(f"hooks.{point}", f"hook {name!r} is registered for {registered!r}")
    if fm.output_schema is not None and fm.output_schema not in catalog.output_schemas:
        bad("output_schema", f"unknown output schema {fm.output_schema!r}")

    # R14.3: a definition may tighten, never exceed, the server ceilings.
    lim = fm.limits
    for field_, value, ceiling in (
        ("max_turns", fm.max_turns, ceilings.model_calls),
        ("limits.max_tool_calls", lim.max_tool_calls, ceilings.tool_calls),
        ("limits.max_tokens", lim.max_tokens, ceilings.tokens),
        ("limits.max_cost_usd", lim.max_cost_usd, ceilings.cost_usd),
        ("limits.timeout_s", lim.timeout_s, ceilings.timeout_s),
    ):
        if value is not None and value > ceiling:
            bad(field_, f"{value} exceeds the server ceiling {ceiling}")

    if not prompt:
        bad("prompt", "the body (system prompt) is empty")
    for name in PLACEHOLDER.findall(prompt):
        if name not in placeholders:
            bad("prompt", f"unknown placeholder {{{{{name}}}}} (allowed: {sorted(placeholders)})")


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root.parent))


# ------------------------------------------------------------ content hashing


def canonical_content(defn: AgentDefinition | SubAgentDefinition) -> dict[str, Any]:
    """The resolved definition (defaults applied) as plain JSON data.

    Sub-agents of a main agent are snapshotted separately, so they are left out
    of the main agent's content: editing a sub-agent doesn't change the main hash.
    """
    return {
        "kind": defn.kind,
        "id": defn.id,
        "frontmatter": defn.frontmatter.model_dump(mode="json"),
        "prompt": defn.prompt,
    }


def content_hash(content: Mapping[str, Any]) -> str:
    """sha256 over canonical JSON: same definition → same hash, on any machine."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
