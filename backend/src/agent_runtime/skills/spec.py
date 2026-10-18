"""The Agent Skills format, checked (CR-006 R17.4; https://agentskills.io/specification).

Pattern: Specification. A skill is a folder: `SKILL.md` (YAML frontmatter + the
instructions) and optional `references/`, `assets/`, `scripts/`. One function turns
an upload, or the Studio's form, into an immutable `SkillContent`, or explains in
plain words why it can't:

- **the standard:** `name` 1 to 64 characters, lowercase letters, digits and single
  hyphens, the folder's name; `description` 1 to 1024 characters; optional `license`,
  `compatibility` (≤ 500), `metadata` (text → text), `allowed-tools`;
- **our limits:** instructions ≤ 10 000 tokens (a warning above 5 000, the
  standard's guideline), ≤ 100 files, ≤ 10 MB in all, safe relative paths.

The same content always gives the same hash, wherever it came from (a form, a zip,
an export), so a round trip is provably lossless.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

import frontmatter
import yaml

SKILL_FILE = "SKILL.md"
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME, MAX_DESCRIPTION, MAX_COMPATIBILITY = 64, 1024, 500
WARN_TOKENS, MAX_TOKENS = 5_000, 10_000
MAX_FILES, MAX_BYTES = 100, 10_000_000
KNOWN_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)
FileKind = Literal["reference", "asset", "script", "other"]


class SkillRejected(ValueError):
    """The upload can't be read at all (not a zip, unsafe paths, too big)."""


@dataclass(frozen=True, slots=True)
class SkillIssue:
    field: str  # "name", "description", "instructions", "files", "<path>"…
    message: str  # plain words, for people
    blocking: bool = True

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class SkillFile:
    path: str  # relative to the skill folder, e.g. "references/checklist.md"
    data: bytes

    @property
    def kind(self) -> FileKind:
        top = PurePosixPath(self.path).parts[0]
        return {"references": "reference", "assets": "asset", "scripts": "script"}.get(top, "other")  # type: ignore[return-value]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def text(self) -> str | None:
        """The file as text, or None for binary files."""
        try:
            text = self.data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return None if "\x00" in text else text


@dataclass(frozen=True, slots=True)
class SkillContent:
    name: str
    description: str
    instructions: str
    meta: Mapping[str, Any]  # license, compatibility, metadata, allowed-tools (as written)
    files: tuple[SkillFile, ...] = ()

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        """What the skill asks for. Shown only: it never grants anything (R17.4)."""
        return tuple(str(self.meta.get("allowed-tools") or "").split())

    def manifest(self) -> list[dict[str, Any]]:
        return [
            {"path": f.path, "sha256": f.sha256, "size": len(f.data), "kind": f.kind}
            for f in self.files
        ]

    def content_hash(self) -> str:
        """sha256 over the canonical content: the same skill → the same hash."""
        canonical = {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "meta": dict(sorted(self.meta.items())),
            "files": self.manifest(),
        }
        text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def skill_md(self) -> str:
        """`SKILL.md` as the standard writes it: frontmatter, then the instructions."""
        head = {"name": self.name, "description": self.description, **self.meta}
        front = yaml.safe_dump(head, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.instructions.strip()}\n"


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def build(
    *,
    name: str,
    description: str,
    instructions: str,
    meta: Mapping[str, Any] | None = None,
    files: Mapping[str, bytes] | None = None,
    folder: str | None = None,
) -> tuple[SkillContent | None, list[SkillIssue]]:
    """A skill from its parts (the form, or a parsed upload), checked against the
    standard and our limits. Non-blocking issues are warnings; any blocking issue
    means no content."""
    issues: list[SkillIssue] = []
    name, description = name.strip(), " ".join(description.split())
    instructions = instructions.strip()
    meta = dict(meta or {})
    issues += _check_name(name, folder)
    if not description:
        issues.append(SkillIssue("description", "Say what it does and when to use it."))
    elif len(description) > MAX_DESCRIPTION:
        issues.append(
            SkillIssue(
                "description",
                f"Keep the description under "
                f"{MAX_DESCRIPTION} characters ({len(description)} now).",
            )
        )
    if not instructions:
        issues.append(SkillIssue("instructions", "Write what the agent should know or do."))
    tokens = estimate_tokens(instructions)
    if tokens > MAX_TOKENS:
        issues.append(
            SkillIssue(
                "instructions",
                f"The instructions are too long (about "
                f"{tokens:,} tokens; the limit is {MAX_TOKENS:,}). Move "
                "details into reference files.",
            )
        )
    elif tokens > WARN_TOKENS:
        issues.append(
            SkillIssue(
                "instructions",
                f"Long instructions (about {tokens:,} tokens): "
                f"under {WARN_TOKENS:,} works best. Agents read all of it "
                "when they load the skill.",
                blocking=False,
            )
        )
    issues += _check_meta(meta)
    checked = _check_files(files or {}, issues)
    if any(i.blocking for i in issues):
        return None, issues
    return SkillContent(name, description, instructions, meta, checked), issues


def parse(
    files: Mapping[str, bytes], folder: str | None = None
) -> tuple[SkillContent | None, list[SkillIssue]]:
    """An uploaded folder ({relative path: bytes}, `SKILL.md` at its root) → content."""
    raw = files.get(SKILL_FILE)
    if raw is None:
        return None, [SkillIssue("files", f"There's no {SKILL_FILE} in it.")]
    try:
        post = frontmatter.loads(raw.decode("utf-8"))  # yaml.SafeLoader
    except UnicodeDecodeError:
        return None, [SkillIssue(SKILL_FILE, f"{SKILL_FILE} isn't UTF-8 text.")]
    except yaml.YAMLError as exc:
        return None, [SkillIssue(SKILL_FILE, f"{SKILL_FILE}'s header isn't valid YAML: {exc}")]
    head = post.metadata if isinstance(post.metadata, dict) else {}
    extra = sorted(set(head) - KNOWN_FIELDS)
    warnings = (
        [
            SkillIssue(
                SKILL_FILE,
                f"Not part of the Agent Skills standard, kept as is: {', '.join(extra)}.",
                blocking=False,
            )
        ]
        if extra
        else []
    )
    meta = {k: v for k, v in head.items() if k not in ("name", "description")}
    content, issues = build(
        name=str(head.get("name") or ""),
        description=str(head.get("description") or ""),
        instructions=post.content,
        meta=meta,
        files={p: d for p, d in files.items() if p != SKILL_FILE},
        folder=folder,
    )
    return content, warnings + issues


def read_upload(filename: str, data: bytes) -> tuple[dict[str, bytes], str | None]:
    """An uploaded `SKILL.md` or zip → ({path inside the skill folder: bytes}, the
    folder's name). Safe: bounded sizes and counts, no absolute paths or `..`."""
    if len(data) > MAX_BYTES:
        raise SkillRejected(f"The file is larger than {MAX_BYTES // 1_000_000} MB.")
    if not filename.lower().endswith(".zip"):
        return {SKILL_FILE: data}, None
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SkillRejected("That isn't a valid zip file.") from exc
    entries = [i for i in archive.infolist() if not i.is_dir()]
    if len(entries) > MAX_FILES + 1:
        raise SkillRejected(f"More than {MAX_FILES} files in the zip.")
    if sum(i.file_size for i in entries) > MAX_BYTES:
        raise SkillRejected(f"More than {MAX_BYTES // 1_000_000} MB once unzipped.")
    paths: dict[PurePosixPath, zipfile.ZipInfo] = {}
    for info in entries:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise SkillRejected(f"Unsafe path in the zip: {info.filename!r}.")
        if path.name in (".DS_Store",) or path.parts[0] == "__MACOSX":
            continue
        paths[path] = info
    roots = [p for p in paths if p.name == SKILL_FILE]
    if not roots:
        raise SkillRejected(f"There's no {SKILL_FILE} in the zip.")
    root = min(roots, key=lambda p: len(p.parts)).parent  # the shallowest SKILL.md
    files = {
        str(p.relative_to(root)): archive.read(info)
        for p, info in paths.items()
        if not root.parts or p.parts[: len(root.parts)] == root.parts
    }
    return files, (root.name or None)


def to_zip(content: SkillContent) -> bytes:
    """The skill as the standard's folder, zipped (what Download gives)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{content.name}/{SKILL_FILE}", content.skill_md())
        for f in content.files:
            archive.writestr(f"{content.name}/{f.path}", f.data)
    return buffer.getvalue()


# ------------------------------------------------------------------ checks


def _check_name(name: str, folder: str | None) -> list[SkillIssue]:
    if not name:
        return [SkillIssue("name", "Give it a name, e.g. trip-checklist.")]
    if len(name) > MAX_NAME:
        return [SkillIssue("name", f"Keep the name under {MAX_NAME} characters.")]
    if not NAME.match(name):
        return [
            SkillIssue(
                "name",
                "Use lowercase letters, digits and single hyphens, e.g. "
                "trip-checklist (no spaces, no hyphen at either end).",
            )
        ]
    if folder is not None and folder != name:
        return [
            SkillIssue(
                "name",
                f"The folder is called “{folder}” but the skill says "
                f"“{name}”: the standard needs them to match.",
            )
        ]
    return []


def _check_meta(meta: Mapping[str, Any]) -> list[SkillIssue]:
    issues: list[SkillIssue] = []
    if "license" in meta and not isinstance(meta["license"], str):
        issues.append(SkillIssue("license", "The license should be text."))
    compat = meta.get("compatibility")
    if compat is not None and not (
        isinstance(compat, str) and 0 < len(compat) <= MAX_COMPATIBILITY
    ):
        issues.append(
            SkillIssue(
                "compatibility",
                f"compatibility should be text of 1 to {MAX_COMPATIBILITY} characters.",
            )
        )
    data = meta.get("metadata")
    if data is not None and not (
        isinstance(data, dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())
    ):
        issues.append(SkillIssue("metadata", "metadata should map text to text."))
    tools = meta.get("allowed-tools")
    if tools is not None and not isinstance(tools, str):
        issues.append(
            SkillIssue(
                "allowed-tools",
                "allowed-tools should be a space-separated list, e.g. “search calculator”.",
            )
        )
    return issues


def _check_files(files: Mapping[str, bytes], issues: list[SkillIssue]) -> tuple[SkillFile, ...]:
    if len(files) > MAX_FILES:
        issues.append(SkillIssue("files", f"More than {MAX_FILES} files."))
        return ()
    if sum(len(d) for d in files.values()) > MAX_BYTES:
        issues.append(SkillIssue("files", f"More than {MAX_BYTES // 1_000_000} MB of files."))
        return ()
    out: list[SkillFile] = []
    for raw_path, data in sorted(files.items()):
        path = PurePosixPath(raw_path)
        if path.is_absolute() or ".." in path.parts or "\\" in raw_path or not path.parts:
            issues.append(SkillIssue("files", f"Unsafe file path: {raw_path!r}."))
            continue
        out.append(SkillFile(str(path), data))
    return tuple(out)
