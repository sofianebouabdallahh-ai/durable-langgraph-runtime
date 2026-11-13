#!/usr/bin/env python3
"""The docs tell the truth about the release and the plans, or CI fails (phase H10).

Pattern: executable documentation. A claim a reader acts on is checked, not trusted. The
external review of 2026-11-12 found the README installing a tag 45 commits behind, and a
roadmap that stopped at the first release: pages nobody checks drift. Run from anywhere
(`python3 scripts/check_docs.py`, `make check-docs`); the standard library is enough.

- `README.md` clones `--branch v<VERSION>`: a newcomer installs the release `VERSION` names.
- `docs/roadmap.md` names every plan in `docs/plans/phase-*.md`: no phase is done and
  missing from "where we are". A plan `phase-<id>.md` is named when the roadmap has `<id>`
  as a word (`H8`, `L3b`) or `phase-<id>` (a link to the plan or its summary); an all-digit
  id (`02`) counts only as `phase-<id>`, since a bare number means nothing.
- `CHANGELOG.md` has a `## [<VERSION>]` section and `backend/pyproject.toml` is at
  `<VERSION>`: the release workflow checks the same when a tag is pushed; this catches it
  on every push, before the tag.

Exit 0 with one line, or 1 with each failure in plain words.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def plans() -> list[Path]:
    return sorted(ROOT.glob("docs/plans/phase-*.md"))


def plan_id(plan: Path) -> str:
    """`docs/plans/phase-H8.md` -> `H8`."""
    return plan.stem.removeprefix("phase-")


def named_in(roadmap: str, phase: str) -> bool:
    if f"phase-{phase}" in roadmap:
        return True
    return not phase.isdigit() and re.search(rf"\b{re.escape(phase)}\b", roadmap) is not None


def check_readme(version: str) -> list[str]:
    tags = re.findall(r"git clone --branch (\S+)", read("README.md"))
    if not tags:
        return ["README.md has no `git clone --branch` line to check"]
    return [
        f"README.md clones `--branch {tag}` but VERSION says {version}: a newcomer would "
        f"install another release (expected `--branch v{version}`)"
        for tag in tags
        if tag != f"v{version}"
    ]


def check_roadmap() -> list[str]:
    roadmap = read("docs/roadmap.md")
    if not plans():
        return ["docs/plans/ has no phase-*.md plan to check"]
    return [
        f"docs/roadmap.md doesn't name phase {plan_id(plan)} ({plan.relative_to(ROOT)}): "
        'add it to the status table and to "Where we are"'
        for plan in plans()
        if not named_in(roadmap, plan_id(plan))
    ]


def check_changelog(version: str) -> list[str]:
    if re.search(rf"^## \[{re.escape(version)}\]", read("CHANGELOG.md"), re.MULTILINE):
        return []
    return [f"CHANGELOG.md has no `## [{version}]` section for the release VERSION names"]


def check_pyproject(version: str) -> list[str]:
    pattern = rf'^version = "{re.escape(version)}"$'
    if re.search(pattern, read("backend/pyproject.toml"), re.MULTILINE):
        return []
    return [f'backend/pyproject.toml isn\'t at `version = "{version}"` (VERSION says {version})']


def main() -> int:
    version = read("VERSION").strip()
    if not version:
        print("VERSION is empty")
        return 1
    failures = [
        *check_readme(version),
        *check_roadmap(),
        *check_changelog(version),
        *check_pyproject(version),
    ]
    if failures:
        # GitHub shows `::error::` lines in the job summary; elsewhere it's plain text.
        prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") else ""
        print(f"{prefix}The docs have drifted from the release or the plans:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"docs ok: README, CHANGELOG and pyproject at v{version}; "
        f"the roadmap names all {len(plans())} plans"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
