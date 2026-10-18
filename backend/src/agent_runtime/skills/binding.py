"""Which skill versions a turn runs (CR-006 R17.4 with R15.4 pinning).

A definition names skills; a turn needs exact versions. Binding resolves names to
version hashes once, when the turn is created, and the bundle pins them:

- a **draft** (and a built-in agent) follows each skill's current version, so a test
  chat always tries what's in the library now;
- a **published** version uses the `skill_lock` taken when it was published, so
  editing (or archiving) a skill never changes a published agent.

A `SkillSet` maps each owner to its skills, in the order the definition lists them:
`""` is the main agent, a helper's name is that helper. An agent sees only its own
entry (R16.7).
"""

from __future__ import annotations

from collections.abc import Mapping

from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.db import Conn
from agent_runtime.skills.store import SkillStore, SkillVersion

MAIN = ""
SkillSet = Mapping[str, tuple[SkillVersion, ...]]


class MissingSkills(LookupError):
    def __init__(self, names: list[str]) -> None:
        listed = ", ".join(f"“{n}”" for n in names)
        super().__init__(f"These skills aren't in the library: {listed}. Add them on the "
                         "Skills page, or remove them from the agent.")  # fmt: skip
        self.names = names


def names_of(defn: AgentDefinition) -> dict[str, list[str]]:
    """Owner → the skill names it lists (only owners that list any)."""
    owners = {MAIN: list(defn.frontmatter.skills)}
    owners |= {s.frontmatter.name: list(s.frontmatter.skills) for s in defn.subagents}
    return {owner: names for owner, names in owners.items() if names}


async def bind(conn: Conn, defn: AgentDefinition, lock: Mapping[str, str] | None) -> SkillSet:
    """The versions `defn`'s skills resolve to: from `lock` (a published version), else
    the library's current ones. Raises MissingSkills."""
    owners = names_of(defn)
    wanted = sorted({n for names in owners.values() for n in names})
    if not wanted:
        return {}
    store = SkillStore(conn)
    if lock is not None:
        hashes = {n: lock[n] for n in wanted if n in lock}
    else:
        hashes = {n: s.current_hash for n, s in (await store.by_names(wanted)).items()}
    if missing := [n for n in wanted if n not in hashes]:
        raise MissingSkills(missing)
    versions = await store.versions(hashes.values())
    return {owner: tuple(versions[hashes[n]] for n in names) for owner, names in owners.items()}


def lock_of(skills: SkillSet) -> dict[str, str]:
    """What publishing freezes: skill name → version hash."""
    return {v.name: v.hash for versions in skills.values() for v in versions}


def manifest(skills: SkillSet) -> list[list[str]]:
    """The bundle's `skills` entry: [[owner, name, version hash], …] in definition order."""
    return [[owner, v.name, v.hash] for owner, versions in skills.items() for v in versions]
