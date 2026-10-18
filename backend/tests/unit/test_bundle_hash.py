"""Adding skills (L3c) left every earlier hash unchanged (R15.4: published versions,
test results and running turns stay matched to their bundles)."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_runtime.agents.loader import canonical_content, content_hash
from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.agents.store import bundle_content, bundle_digest
from agent_runtime.graphs import default_registry
from agent_runtime.skills.store import SkillVersion

CHAT = default_registry().get("chat").agent


def _before_l3c(defn: AgentDefinition) -> str:
    """How bundle hashes were computed in L3a and L3b."""
    return content_hash({
        "main": content_hash(canonical_content(defn)),
        "helpers": [[s.frontmatter.name, content_hash(canonical_content(s))]
                    for s in defn.subagents],
    })  # fmt: skip


def test_an_agent_without_skills_keeps_its_hash() -> None:
    assert isinstance(CHAT, AgentDefinition)
    assert "skills" not in canonical_content(CHAT)["frontmatter"]
    assert bundle_digest(CHAT) == bundle_digest(CHAT, {}) == _before_l3c(CHAT)


def test_skill_versions_are_part_of_the_hash_in_order() -> None:
    assert isinstance(CHAT, AgentDefinition)

    def version(h: str) -> SkillVersion:
        return SkillVersion(h, "tips", "d", "i", {}, [], {}, datetime.now(UTC))

    one = bundle_digest(CHAT, {"": (version("a" * 64),)})
    two = bundle_digest(CHAT, {"": (version("b" * 64),)})
    assert len({one, two, _before_l3c(CHAT)}) == 3
    assert bundle_content(CHAT, {"researcher": (version("a" * 64),)})["skills"] == [
        ["researcher", "tips", "a" * 64]
    ]
