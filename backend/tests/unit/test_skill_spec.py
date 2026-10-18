"""Skills follow the Agent Skills standard (R17.4): the rules, our limits, safe uploads."""

from __future__ import annotations

import io
import zipfile

import pytest

from agent_runtime.skills import spec
from agent_runtime.skills.spec import SkillRejected, build, parse, read_upload, to_zip

GOOD = (
    "---\nname: trip-checklist\ndescription: What to pack. Use when planning a trip.\n"
    "---\n\nPack light.\n"
)


def _zip(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return buffer.getvalue()


def _blocking(issues: list[spec.SkillIssue]) -> list[str]:
    return [i.field for i in issues if i.blocking]


@pytest.mark.parametrize(
    "name",
    ["Trip", "trip checklist", "-trip", "trip-", "trip--list", "x" * 65, "", "trip_list"],
)
def test_names_follow_the_standard(name: str) -> None:
    content, issues = build(name=name, description="d", instructions="i")
    assert content is None and _blocking(issues) == ["name"]


def test_a_good_skill_builds_and_its_markdown_parses_back_to_the_same_hash() -> None:
    content, issues = build(
        name="trip-checklist",
        description="What to pack.  Use when\nplanning a trip.",
        instructions="Pack light.",
        meta={"license": "MIT", "allowed-tools": "search calculator"},
        files={"references/list.md": b"- socks"},
    )
    assert content is not None and issues == []
    assert content.description == "What to pack. Use when planning a trip."  # whitespace folded
    assert content.allowed_tools == ("search", "calculator")
    again, _ = parse({"SKILL.md": content.skill_md().encode(), "references/list.md": b"- socks"})
    assert again is not None and again.content_hash() == content.content_hash()


def test_the_description_and_instructions_have_limits() -> None:
    _, issues = build(name="a", description="x" * 1025, instructions="")
    assert _blocking(issues) == ["description", "instructions"]
    long, issues = build(name="a", description="d", instructions="word " * 5_000)
    assert long is not None and [i.field for i in issues] == ["instructions"]  # a warning
    _, issues = build(name="a", description="d", instructions="word " * 9_000)
    assert _blocking(issues) == ["instructions"]


def test_the_folder_must_match_the_name() -> None:
    files, folder = read_upload("x.zip", _zip({"packing/SKILL.md": GOOD}))
    content, issues = parse(files, folder)
    assert content is None and "folder is called “packing”" in issues[0].message


def test_unknown_header_fields_are_kept_with_a_warning() -> None:
    text = GOOD.replace("description:", "author: me\ndescription:")
    content, issues = parse({"SKILL.md": text.encode()})
    assert content is not None and content.meta == {"author": "me"}
    assert [i.blocking for i in issues] == [False]


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"../evil/SKILL.md": GOOD}, "Unsafe path"),
        ({"/abs/SKILL.md": GOOD}, "Unsafe path"),
        ({"notes.txt": "hi"}, "no SKILL.md"),
    ],
)
def test_unsafe_or_empty_zips_are_refused(files: dict[str, str], message: str) -> None:
    with pytest.raises(SkillRejected, match=message):
        read_upload("skill.zip", _zip(files))  # type: ignore[arg-type]


def test_not_a_zip_and_too_big_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SkillRejected, match="valid zip"):
        read_upload("skill.zip", b"not a zip")
    monkeypatch.setattr(spec, "MAX_BYTES", 10)
    with pytest.raises(SkillRejected, match="larger than"):
        read_upload("SKILL.md", b"x" * 11)


def test_the_header_must_be_yaml_and_the_file_utf8() -> None:
    assert parse({"SKILL.md": b"---\nname: [\n---\nx"})[0] is None
    assert parse({"SKILL.md": b"\xff\xfe"})[1][0].message == "SKILL.md isn't UTF-8 text."


def test_export_then_upload_is_lossless() -> None:
    content, _ = build(
        name="trip-checklist",
        description="What to pack.",
        instructions="Pack light.",
        files={"references/list.md": b"- socks", "assets/logo.png": b"\x89PNG\x00\x01"},
    )
    assert content is not None
    files, folder = read_upload("trip-checklist.zip", to_zip(content))
    again, issues = parse(files, folder)
    assert issues == [] and again is not None
    assert again.content_hash() == content.content_hash()
    assert {f.path: f.kind for f in again.files} == {
        "assets/logo.png": "asset",
        "references/list.md": "reference",
    }
    assert [f.text is None for f in again.files] == [True, False]  # binary vs text
