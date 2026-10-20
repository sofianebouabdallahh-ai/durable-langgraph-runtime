"""The Studio's agent document (CR-006 R17.1, R17.2).

What the form edits, stored as JSON in `agent_versions.document`: the same fields as
an `agent.md` frontmatter, with the instructions inline and the helpers (sub-agents)
nested. It is only a *shape*. Whether it's valid is decided by the one validator,
`validate_definition`, exactly as for files. Conversions:

    document ──to_raw──► RawDefinitions ──validate_definition──► AgentDefinition
    AgentDefinition ──from_definition──► document          (copy, restore, import)
    AgentDefinition ──to_files──► {path: agent.md text}     (export)
    {path: agent.md text} ──from_files──► RawDefinitions    (import)
    zip ──read_skill_folders──► {name: files}               (its skills, L3c)

A zipped agent carries the skills it uses in the Agent Skills format, next to it:
`<agent>/skills/<skill>/SKILL.md` (+ references/, assets/).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Annotated, Any

import frontmatter
import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.agents.loader import DEFINITION_FILE, Issue, RawDefinition
from agent_runtime.agents.schema import AgentDefinition, SubAgentDefinition
from agent_runtime.skills.spec import SkillContent

MAX_INSTRUCTIONS = 20_000  # characters, per agent or helper (G3: bounded input)
MAX_HELPERS = 10  # the orchestrator's limit on sub-agents per run (CR-005)
MAX_SKILLS = 20  # per agent or helper: each adds a line to its prompt


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolChoice(_Doc):
    name: str
    max_calls: Annotated[int, Field(gt=0)] | None = None


class HelperDocument(_Doc):
    name: str
    display_name: str | None = None
    description: str = ""
    instructions: Annotated[str, Field(max_length=MAX_INSTRUCTIONS)] = ""
    model: str = "chat"
    temperature: float = 0.2
    max_turns: int = 6
    limits: dict[str, Any] = Field(default_factory=dict)
    tools: list[ToolChoice] = Field(default_factory=list)
    skills: Annotated[list[str], Field(max_length=MAX_SKILLS)] = Field(default_factory=list)
    hooks: dict[str, list[str]] = Field(default_factory=dict)


class AgentDocument(_Doc):
    name: str
    display_name: str | None = None
    description: str = ""
    instructions: Annotated[str, Field(max_length=MAX_INSTRUCTIONS)] = ""
    model: str = "chat"
    temperature: float = 0.2
    max_turns: int = 20
    limits: dict[str, Any] = Field(default_factory=dict)
    tools: list[ToolChoice] = Field(default_factory=list)
    skills: Annotated[list[str], Field(max_length=MAX_SKILLS)] = Field(default_factory=list)
    hooks: dict[str, list[str]] = Field(default_factory=dict)
    # The most messages one chat with it may have (none: no limit beyond the server's).
    max_session_turns: Annotated[int, Field(gt=0)] | None = None
    helpers: Annotated[list[HelperDocument], Field(max_length=MAX_HELPERS)] = Field(
        default_factory=list
    )


def _metadata(doc: AgentDocument | HelperDocument, version: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": doc.name,
        "description": doc.description,
        "version": version,
        "model": doc.model,
        "temperature": doc.temperature,
        "max_turns": doc.max_turns,
        "limits": doc.limits,
        "tools": [t.model_dump(exclude_none=True) for t in doc.tools],
        "hooks": {k: v for k, v in doc.hooks.items() if v},
    }
    if doc.display_name:
        out["display_name"] = doc.display_name
    if doc.skills:
        out["skills"] = list(doc.skills)
    if isinstance(doc, AgentDocument) and doc.max_session_turns:
        out["max_session_turns"] = doc.max_session_turns
    return out


def to_raw(doc: AgentDocument, version: int) -> tuple[RawDefinition, list[RawDefinition]]:
    """The document as the validator's input. Issues are labelled by form section."""
    main = RawDefinition(
        doc.name,
        _metadata(doc, version),
        doc.instructions.strip(),
        "agent",
        name_of="the agent's id",
    )
    helpers = [
        RawDefinition(
            h.name,
            _metadata(h, version),
            h.instructions.strip(),
            f"helpers.{h.name}",
            name_of="the helper's id",
        )
        for h in doc.helpers
    ]
    return main, helpers


def _fields(defn: AgentDefinition | SubAgentDefinition) -> dict[str, Any]:
    fm = defn.frontmatter
    return {
        "name": fm.name,
        "display_name": fm.display_name,
        "description": fm.description,
        "instructions": defn.prompt,
        "model": fm.model,
        "temperature": fm.temperature,
        "max_turns": fm.max_turns,
        "limits": fm.limits.model_dump(exclude_none=True),
        "tools": [t.model_dump(exclude_none=True) for t in fm.tools],
        "skills": list(fm.skills),
        "hooks": {k: v for k, v in fm.hooks.model_dump().items() if v},
    }


def from_definition(defn: AgentDefinition, *, name: str | None = None) -> AgentDocument:
    """A validated definition as an editable document (optionally under a new id)."""
    fields = _fields(defn)
    if name is not None:
        fields["name"] = name
    helpers = [HelperDocument.model_validate(_fields(s)) for s in defn.subagents]
    return AgentDocument.model_validate(
        {**fields, "helpers": helpers, "max_session_turns": defn.frontmatter.max_session_turns}
    )


# ------------------------------------------------------------------ files


def _agent_md(defn: AgentDefinition | SubAgentDefinition) -> str:
    fm = defn.frontmatter.model_dump(mode="json", exclude_none=True, exclude_defaults=False)
    fm["hooks"] = {k: v for k, v in fm.get("hooks", {}).items() if v}
    if not fm["hooks"]:
        fm.pop("hooks")
    if not fm.get("limits"):
        fm.pop("limits", None)
    if not fm.get("tools"):
        fm.pop("tools", None)
    if not fm.get("skills"):
        fm.pop("skills", None)
    head = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{head}\n---\n{defn.prompt}\n"


def to_files(defn: AgentDefinition) -> dict[str, str]:
    """The agent as its folder: `<name>/agent.md`, `<name>/<helper>/agent.md`."""
    files = {f"{defn.id}/{DEFINITION_FILE}": _agent_md(defn)}
    for sub in defn.subagents:
        files[f"{defn.id}/{sub.frontmatter.name}/{DEFINITION_FILE}"] = _agent_md(sub)
    return files


def to_zip(defn: AgentDefinition, skills: Sequence[SkillContent] = ()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, text in sorted(to_files(defn).items()):
            zf.writestr(path, text)
        for skill in skills:
            zf.writestr(f"{defn.id}/skills/{skill.name}/SKILL.md", skill.skill_md())
            for f in skill.files:
                zf.writestr(f"{defn.id}/skills/{skill.name}/{f.path}", f.data)
    return buffer.getvalue()


def read_skill_folders(filename: str, data: bytes) -> dict[str, dict[str, bytes]]:
    """The skills a zipped agent carries: {folder name: {path inside it: bytes}}, from
    `<agent>/skills/<name>/`. Sizes and paths were checked by `read_upload`."""
    if not filename.lower().endswith(".zip"):
        return {}
    archive = zipfile.ZipFile(io.BytesIO(data))
    entries = [i for i in archive.infolist() if not i.is_dir()]
    agents = sorted(
        (
            PurePosixPath(i.filename)
            for i in entries
            if PurePosixPath(i.filename).name == DEFINITION_FILE
        ),
        key=lambda p: len(p.parts),
    )
    if not agents:
        return {}
    base = agents[0].parent / "skills"
    out: dict[str, dict[str, bytes]] = {}
    for info in entries:
        path = PurePosixPath(info.filename)
        if path.parts[: len(base.parts)] != base.parts or len(path.parts) < len(base.parts) + 2:
            continue
        rel = path.relative_to(base)
        out.setdefault(rel.parts[0], {})[str(PurePosixPath(*rel.parts[1:]))] = archive.read(info)
    return out


class ImportRejected(ValueError):
    """An upload that isn't a safe agent folder (or file)."""


MAX_UPLOAD_BYTES = 10_000_000  # an agent with its skills (a skill is ≤ 10 MB on its own)
MAX_ZIP_FILES = 300
MAX_UNZIPPED_BYTES = 30_000_000
MAX_FILE_BYTES = 200_000


def read_upload(filename: str, data: bytes) -> dict[str, str]:
    """An uploaded `.agent.md` or zipped folder as {relative path: text}, safely:
    bounded sizes and counts, no absolute paths or `..`, only agent.md files kept."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImportRejected(f"the file is larger than {MAX_UPLOAD_BYTES // 1_000_000} MB")
    if not filename.lower().endswith(".zip"):
        return {DEFINITION_FILE: _text(data)}
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportRejected("not a valid zip file") from exc
    entries = [i for i in archive.infolist() if not i.is_dir()]
    if len(entries) > MAX_ZIP_FILES:
        raise ImportRejected(f"more than {MAX_ZIP_FILES} files in the zip")
    if sum(i.file_size for i in entries) > MAX_UNZIPPED_BYTES:  # a zip bomb
        raise ImportRejected(f"more than {MAX_UNZIPPED_BYTES // 1_000_000} MB once unzipped")
    files: dict[str, str] = {}
    for info in entries:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise ImportRejected(f"unsafe path in the zip: {info.filename!r}")
        if path.name != DEFINITION_FILE:
            continue  # instruction-only: nothing else is read (skills come in L3c)
        if info.file_size > MAX_FILE_BYTES:
            raise ImportRejected(f"{info.filename} is too large")
        files[str(path)] = _text(archive.read(info))
    if not files:
        raise ImportRejected(f"no {DEFINITION_FILE} in the zip")
    return files


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImportRejected("the file isn't UTF-8 text") from exc


def from_files(
    files: Mapping[str, str],
) -> tuple[RawDefinition | None, list[RawDefinition], list[Issue]]:
    """An agent folder (as read by `read_upload`) → the validator's input. The main
    agent is the shallowest agent.md; helpers are one level below it."""
    paths = sorted(files, key=lambda p: (len(PurePosixPath(p).parts), p))
    issues: list[Issue] = []
    if not paths:
        return None, [], [Issue("upload", None, f"no {DEFINITION_FILE}")]
    root = PurePosixPath(paths[0]).parent
    main = _parse(files[paths[0]], paths[0], issues)
    helpers: list[RawDefinition] = []
    for p in paths[1:]:
        rel = PurePosixPath(p).relative_to(root) if root.parts else PurePosixPath(p)
        if len(rel.parts) != 2:
            issues.append(Issue(p, None, "helpers are one folder below the agent, no deeper"))
            continue
        parsed = _parse(files[p], p, issues)
        if parsed is not None:
            name, metadata, prompt = parsed
            helpers.append(
                RawDefinition(name, metadata, prompt, f"helpers.{name}", name_of="the helper's id")
            )
    if main is None:
        return None, helpers, issues
    name, metadata, prompt = main
    return RawDefinition(name, metadata, prompt, "agent", name_of="the agent's id"), helpers, issues


def _parse(text: str, path: str, issues: list[Issue]) -> tuple[str, dict[str, Any], str] | None:
    try:
        post = frontmatter.loads(text)  # yaml.SafeLoader
    except yaml.YAMLError as exc:
        issues.append(Issue(path, None, f"invalid YAML frontmatter: {exc}"))
        return None
    if not isinstance(post.metadata, dict) or not isinstance(post.metadata.get("name"), str):
        issues.append(Issue(path, "name", "the frontmatter needs a name"))
        return None
    return str(post.metadata["name"]), dict(post.metadata), post.content.strip()
