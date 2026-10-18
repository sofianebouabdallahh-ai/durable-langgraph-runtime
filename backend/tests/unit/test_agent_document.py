"""The Studio's agent document (L3a): one validator for the form and for files, and
lossless conversions between the document, the definition and agent.md files."""

import io
import zipfile

import pytest

from agent_runtime.agents.document import (
    MAX_UPLOAD_BYTES,
    MAX_ZIP_FILES,
    AgentDocument,
    ImportRejected,
    from_definition,
    from_files,
    read_upload,
    to_files,
    to_raw,
    to_zip,
)
from agent_runtime.agents.loader import (
    Ceilings,
    canonical_content,
    content_hash,
    validate_definition,
)
from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.catalog import default_catalog
from agent_runtime.graphs import default_registry

CATALOG = default_catalog()
CEILINGS = Ceilings(model_calls=200, tool_calls=100, tokens=1_000_000, cost_usd=10, timeout_s=3600)
_chat = default_registry().get("chat").agent
assert _chat is not None
CHAT: AgentDefinition = _chat


def validate(doc: AgentDocument, version: int = 1):  # type: ignore[no-untyped-def]
    main, helpers = to_raw(doc, version)
    return validate_definition(main, helpers, CATALOG, CEILINGS)


def unversioned(defn) -> dict[str, object]:  # type: ignore[no-untyped-def]
    content = canonical_content(defn)
    content["frontmatter"] = {k: v for k, v in content["frontmatter"].items() if k != "version"}
    return content


def hashes(defn) -> list[str]:  # type: ignore[no-untyped-def]
    return [content_hash(canonical_content(d)) for d in (defn, *defn.subagents)]


def test_a_definition_survives_document_and_files_round_trips_unchanged() -> None:
    doc = from_definition(CHAT)
    again, issues = validate(doc, CHAT.frontmatter.version)
    assert issues == [] and again is not None
    # document ⇄ definition: lossless, except that in the Studio a helper takes its
    # agent's version number (files version each helper on its own)
    assert hashes(again)[0] == hashes(CHAT)[0]
    assert [unversioned(s) for s in again.subagents] == [unversioned(s) for s in CHAT.subagents]

    main, helpers, problems = from_files(read_upload("chat.zip", to_zip(CHAT)))
    assert problems == [] and main is not None
    imported, issues = validate_definition(main, helpers, CATALOG, CEILINGS)
    assert issues == [] and imported is not None
    assert hashes(imported) == hashes(CHAT)  # export ⇄ import: lossless
    assert set(to_files(CHAT)) == {
        "chat/agent.md",
        "chat/researcher/agent.md",
        "chat/data-analyst/agent.md",
    }


def blank(**changes: object) -> AgentDocument:
    base = {
        "name": "trip-planner",
        "display_name": "Trip planner",
        "description": "Plans trips.",
        "instructions": "Plan trips. Today is {{date}}.",
        "tools": [{"name": "search"}],
    }
    return AgentDocument.model_validate({**base, **changes})


def issues_of(doc: AgentDocument) -> list[tuple[str, str | None, str]]:
    defn, issues = validate(doc)
    assert defn is None
    return [(i.path, i.field, i.message) for i in issues]


def test_a_new_agent_with_a_helper_is_valid() -> None:
    doc = blank(
        helpers=[
            {
                "name": "scout",
                "description": "Finds places.",
                "instructions": "Find places.",
                "tools": [{"name": "search"}],
            }
        ]
    )
    defn, issues = validate(doc)
    assert issues == [] and defn is not None
    assert defn.frontmatter.display_name == "Trip planner"
    assert [s.id for s in defn.subagents] == ["trip-planner/scout"]


@pytest.mark.parametrize(
    ("changes", "where", "field", "says"),
    [
        ({"tools": [{"name": "teleport"}]}, "agent", "tools", "unknown tool"),
        ({"instructions": ""}, "agent", "prompt", "empty"),
        ({"instructions": "Hi {{secret}}"}, "agent", "prompt", "unknown placeholder"),
        ({"max_turns": 10_000}, "agent", "max_turns", "exceeds the server ceiling"),
        ({"name": "Trip Planner"}, "agent", "name", "pattern"),
        (
            {
                "helpers": [
                    {
                        "name": "pinger",
                        "description": "d",
                        "instructions": "x",
                        "tools": [{"name": "notify"}],
                    }
                ]
            },
            "helpers.pinger",
            "tools",
            "human approval",
        ),
        (
            {
                "helpers": [
                    {"name": "a", "description": "d", "instructions": "x"},
                    {"name": "a", "description": "d", "instructions": "y"},
                ]
            },
            "helpers.a",
            "name",
            "two helpers",
        ),
    ],
)
def test_issues_point_at_the_form_section_and_field(
    changes: dict[str, object], where: str, field: str, says: str
) -> None:
    found = issues_of(blank(**changes))
    assert any(p == where and f == field and says in m for p, f, m in found), found


def zipped(entries: dict[str, bytes], compression: int = zipfile.ZIP_STORED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "says"),
    [
        ("evil.zip", zipped({"../etc/agent.md": b"x"}), "unsafe path"),
        ("evil.zip", zipped({"/abs/agent.md": b"x"}), "unsafe path"),
        (
            "many.zip",
            zipped({f"a/{i}/agent.md": b"x" for i in range(MAX_ZIP_FILES + 1)}),
            "more than",
        ),
        ("big.md", b"x" * (MAX_UPLOAD_BYTES + 1), "larger than"),
        (
            "bomb.zip",
            zipped(  # small on the wire, 31 MB once unzipped
                {"a/agent.md": b"x", **{f"a/skills/s/{i}": b"0" * 1_000_000 for i in range(31)}},
                zipfile.ZIP_DEFLATED,
            ),
            "once unzipped",
        ),
        ("none.zip", zipped({"a/readme.txt": b"hello"}), "no agent.md"),
        ("bad.zip", b"not a zip", "not a valid zip"),
        ("bin.md", b"\xff\xfe\x00", "UTF-8"),
    ],
)
def test_unsafe_uploads_are_rejected(name: str, data: bytes, says: str) -> None:
    with pytest.raises(ImportRejected, match=says):
        read_upload(name, data)


def test_only_agent_files_are_read_and_nesting_is_checked() -> None:
    files = read_upload(
        "a.zip",
        zipped(
            {
                "a/agent.md": to_files(CHAT)["chat/agent.md"].encode(),
                "a/notes.txt": b"ignored",
                "a/x/y/agent.md": b"---\nname: y\n---\nhi",
            }
        ),
    )
    assert set(files) == {"a/agent.md", "a/x/y/agent.md"}
    _, _, issues = from_files(files)
    assert any("one folder below" in i.message for i in issues)
