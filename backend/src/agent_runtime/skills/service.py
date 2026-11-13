"""The skill library (CR-006 R17.4): create, edit, upload, download, archive.

Every save goes through the same two gates, whatever its source (the form, a zip,
an agent import, a built-in folder):

    parts ──spec.build / spec.parse──► SkillContent ──scan──► report
          blocking issue → SkillInvalid    secret → SkillBlocked    else → a version

A skill's `name` is its identity: agents refer to skills by name, so it is fixed
once created (like an agent's id). Editing makes a new version and points the skill
at it; old versions stay, because published agents may have locked them.

A third gate decides what a version may be in a prompt (H10 2.2, R14.15): **a person has
read it**. Text typed in the Studio (`create`, `edit`) and the built-ins are approved at
save; an upload, a replaced version or an agent import is not, until the person opens
the skill, sees its text and the scan's findings, and says so (`approve`). The scan can't
stand in for that: a skill is instructions, so a trap written as plain advice (in English
or in French) scores clean. Pattern: promotion gate, as H6's publish gate for agents.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime.audit import AuditLog
from agent_runtime.db import Pool
from agent_runtime.ids import new_id
from agent_runtime.skills import spec
from agent_runtime.skills.scan import RULES, ScanReport, scan
from agent_runtime.skills.spec import SkillContent, SkillIssue
from agent_runtime.skills.store import Origin, Skill, SkillNotFound, SkillStore, SkillVersion

log = logging.getLogger(__name__)


class SkillInvalid(ValueError):
    """The skill doesn't follow the standard or our limits; `issues` say why."""

    def __init__(self, issues: list[SkillIssue]) -> None:
        super().__init__("; ".join(i.message for i in issues if i.blocking))
        self.issues = issues


class SkillBlocked(ValueError):
    """The scan found something that can't be saved (a secret)."""

    def __init__(self, report: ScanReport) -> None:
        super().__init__("the scan blocked this skill")
        self.report = report


class SkillExists(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"There's already a skill called “{name}”.")
        self.name = name


class BuiltInSkill(ValueError):
    """Built-in skills ship with Nuria (reviewed in git): copy one to change it."""


@dataclass(frozen=True, slots=True)
class Saved:
    skill: Skill
    version: SkillVersion
    warnings: list[SkillIssue] = field(default_factory=list)


def read_builtins(folder: Path) -> list[tuple[SkillContent, ScanReport]]:
    """The built-in skill folders under `folder`, checked and scanned (blocking I/O)."""
    checked: list[tuple[SkillContent, ScanReport]] = []
    if not folder.is_dir():
        return checked
    for path in sorted(p for p in folder.iterdir() if (p / spec.SKILL_FILE).is_file()):
        files = {
            str(f.relative_to(path)): f.read_bytes() for f in sorted(path.rglob("*")) if f.is_file()
        }
        content, issues = spec.parse(files, path.name)
        report = scan(content) if content is not None else None
        if content is None or report is None or report.status == "blocked":
            log.warning("built-in skill %s skipped: %s", path.name, issues or report)
            continue
        checked.append((content, report))
    return checked


class SkillService:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def all(self) -> list[tuple[Skill, SkillVersion]]:
        async with self._pool.connection() as conn:
            store = SkillStore(conn)
            skills = await store.all()
            versions = await store.versions(s.current_hash for s in skills)
        return [(s, versions[s.current_hash]) for s in skills]

    async def get(self, skill_id: uuid.UUID) -> tuple[Skill, SkillVersion]:
        async with self._pool.connection() as conn:
            store = SkillStore(conn)
            skill = await store.get(skill_id)
            return skill, await store.version(skill.current_hash)

    async def used_by(self) -> dict[str, list[str]]:
        async with self._pool.connection() as conn:
            return await SkillStore(conn).used_by()

    async def create(
        self,
        *,
        name: str,
        description: str,
        instructions: str,
        files: Mapping[str, bytes] | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> Saved:
        content, issues = spec.build(
            name=name, description=description, instructions=instructions, meta=meta, files=files
        )
        # The person typed this text: they have read it.
        return await self._add(content, issues, "created", approved=True)

    async def upload(self, filename: str, data: bytes, *, origin: Origin = "uploaded") -> Saved:
        """A new skill from a zip or a `SKILL.md`. SkillRejected if it can't be read. Not
        approved: nothing says the person read what the file contains."""
        files, folder = spec.read_upload(filename, data)
        content, issues = spec.parse(files, folder)
        return await self._add(content, issues, origin, approved=False)

    async def edit(
        self,
        skill_id: uuid.UUID,
        *,
        description: str | None = None,
        instructions: str | None = None,
        files: Mapping[str, bytes | None] | None = None,
    ) -> Saved:
        """A new version from the current one with these changes (files: path → new
        bytes, or None to remove). The name never changes. Approved at save: the form
        showed the whole text, and the person wrote what changed."""
        async with self._pool.connection() as conn:
            store = SkillStore(conn)
            skill = await self._editable(store, skill_id)
            current = await store.content(skill.current_hash)
        kept = {f.path: f.data for f in current.files}
        for path, data in (files or {}).items():
            if data is None:
                kept.pop(path, None)
            else:
                kept[path] = data
        content, issues = spec.build(
            name=current.name,
            description=current.description if description is None else description,
            instructions=current.instructions if instructions is None else instructions,
            meta=current.meta,
            files=kept,
        )
        return await self._replace(skill_id, content, issues, approved=True)

    async def replace(self, skill_id: uuid.UUID, filename: str, data: bytes) -> Saved:
        """A new version of this skill from an upload (its name must match). Not approved:
        the new text hasn't been read here, whatever the old one was."""
        files, folder = spec.read_upload(filename, data)
        content, issues = spec.parse(files, folder)
        async with self._pool.connection() as conn:
            skill = await self._editable(SkillStore(conn), skill_id)
        if content is not None and content.name != skill.name:
            raise SkillInvalid(
                [
                    SkillIssue(
                        "name",
                        f"This upload is “{content.name}”, not "
                        f"“{skill.name}”: upload it as a new skill.",
                    )
                ]
            )
        return await self._replace(skill_id, content, issues, approved=False)

    async def approve(self, skill_id: uuid.UUID) -> tuple[Skill, SkillVersion]:
        """The person says "I've read this": they saw the current version's text and the
        scan's findings. From now on that exact version may be plain text in a prompt (if
        its scan is clean too); an edit makes a new hash and starts over. Idempotent: the
        audit row (`skill.approved`, with the hash) is written once per version."""
        async with self._pool.connection() as conn, conn.transaction():
            store = SkillStore(conn)
            skill = await store.get(skill_id)
            if skill.archived_at is not None:
                raise SkillNotFound(str(skill_id))
            if await store.approve(skill.current_hash, "read on the Skills page"):
                await AuditLog(conn).record("skill.approved", "skill", skill.name,
                                            after={"version": skill.current_hash})  # fmt: skip
            return skill, await store.version(skill.current_hash)

    async def archive(self, skill_id: uuid.UUID) -> None:
        """Out of the library. Published agents keep the version they locked."""
        async with self._pool.connection() as conn, conn.transaction():
            store = SkillStore(conn)
            skill = await self._editable(store, skill_id)
            await store.archive(skill_id)
            await AuditLog(conn).record("skill.archived", "skill", skill.name)

    async def export(self, skill_id: uuid.UUID) -> tuple[str, bytes]:
        async with self._pool.connection() as conn:
            store = SkillStore(conn)
            skill = await store.get(skill_id)
            content = await store.content(skill.current_hash)
        return f"{skill.name}.zip", spec.to_zip(content)

    async def file(self, skill_id: uuid.UUID, path: str) -> tuple[dict[str, Any], bytes]:
        async with self._pool.connection() as conn:
            store = SkillStore(conn)
            skill = await store.get(skill_id)
            entry = (await store.version(skill.current_hash)).entry(path)
            if entry is None:
                raise SkillNotFound(path)
            return entry, await store.file(entry["sha256"])

    # ------------------------------------------------------------- built-ins

    async def rescan(self) -> int:
        """Check every stored version again with the current rules, once (RULES went up).
        Their stored scans stay; the new results are added (skill_scans). Returns how
        many were checked."""
        async with self._pool.connection() as conn:
            store = SkillStore(conn)
            stale = await store.checked_before(RULES)
            for digest in stale:
                content = await store.content(digest)
                report = await asyncio.to_thread(scan, content)
                await store.add_scan(digest, report)
        if stale:
            log.info("checked %d stored skill versions with the current rules", len(stale))
        return len(stale)

    async def sync_builtins(self, folder: Path) -> list[str]:
        """Load `backend/skills/<name>/` into the library as built-in skills, and point
        each at its current content. Idempotent; run at API startup. A folder that
        fails the spec or the scan is skipped with a warning (it's our bug). What ships
        with Nuria was reviewed in git, so each version is approved as it is synced."""
        names: list[str] = []
        checked = await asyncio.to_thread(read_builtins, folder)
        async with self._pool.connection() as conn, conn.transaction():
            # API replicas start together: one syncs at a time.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('skills:built-ins'))")
            store = SkillStore(conn)
            for content, report in checked:
                digest = await store.put_version(content, report)
                await store.approve(digest, "built in")
                existing = await store.by_name(content.name, archived=True)
                if existing is None:
                    await store.insert(new_id(), content.name, "built_in", "built_in", digest)
                elif existing.trust != "built_in":
                    log.warning("built-in skill %s: a user skill has that name", content.name)
                    continue
                elif existing.current_hash != digest:
                    await store.point(existing.id, digest)
                names.append(content.name)
        return names

    # ------------------------------------------------------------- internals

    async def _editable(self, store: SkillStore, skill_id: uuid.UUID) -> Skill:
        skill = await store.get(skill_id)
        if skill.archived_at is not None:
            raise SkillNotFound(str(skill_id))
        if skill.trust == "built_in":
            raise BuiltInSkill(
                f"“{skill.name}” is built in: download it and upload a copy "
                "under another name to change it."
            )
        return skill

    @staticmethod
    def _gate(
        content: SkillContent | None, issues: list[SkillIssue]
    ) -> tuple[SkillContent, ScanReport]:
        if content is None:
            raise SkillInvalid(issues)
        report = scan(content)
        if report.status == "blocked":
            raise SkillBlocked(report)
        return content, report

    async def _add(
        self,
        content: SkillContent | None,
        issues: list[SkillIssue],
        origin: Origin,
        *,
        approved: bool,
    ) -> Saved:
        """`approved`: the person has read this text (they typed it), so the version is
        approved as it is saved; an upload waits for its reader."""
        checked, report = self._gate(content, issues)
        async with self._pool.connection() as conn, conn.transaction():
            store = SkillStore(conn)
            if await store.by_name(checked.name, archived=True) is not None:
                raise SkillExists(checked.name)
            digest = await store.put_version(checked, report)
            if approved:
                await store.approve(digest, "written in the Studio")
            skill = await store.insert(new_id(), checked.name, "private", origin, digest)
            version = await store.version(digest)
            await AuditLog(conn).record("skill.created", "skill", skill.name,
                                        after={"origin": origin, "version": digest,
                                               "approved": version.approved})  # fmt: skip
        return Saved(skill, version, [i for i in issues if not i.blocking])

    async def _replace(
        self,
        skill_id: uuid.UUID,
        content: SkillContent | None,
        issues: list[SkillIssue],
        *,
        approved: bool,
    ) -> Saved:
        checked, report = self._gate(content, issues)
        async with self._pool.connection() as conn, conn.transaction():
            store = SkillStore(conn)
            before = await store.get(skill_id)
            digest = await store.put_version(checked, report)
            if approved:
                await store.approve(digest, "written in the Studio")
            skill = await store.point(skill_id, digest)
            version = await store.version(digest)
            await AuditLog(conn).record("skill.updated", "skill", skill.name,
                                        before={"version": before.current_hash},
                                        after={"version": digest,
                                               "approved": version.approved})  # fmt: skip
        return Saved(skill, version, [i for i in issues if not i.blocking])
