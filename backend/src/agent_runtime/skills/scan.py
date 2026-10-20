"""The scan every skill goes through before it's saved (CR-006 R17.4, AC46; OWASP AST01).

Pattern: Chain of Responsibility. Each check looks at one concern and returns
findings; the report is the sum. Severities:

- `block`: the skill can't be saved (a secret: skills are shared text);
- `review`: saved, flagged for a person to look at (injection phrasing, links,
  encoded blobs, scripts, invisible characters, length).

Findings say where (file, line) and what, in plain words, and **never echo a
secret**. A scan informs people; it's not what keeps agents safe. That's the
harness: skill text arrives as data (R14.15), skills never grant tools, and scripts
never run (no sandbox yet).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from agent_runtime.skills.spec import SKILL_FILE, WARN_TOKENS, SkillContent, estimate_tokens
from agent_runtime.tools.hooks import SECRET_PATTERNS

Severity = Literal["block", "review"]
Status = Literal["clean", "review", "blocked"]


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    severity: Severity
    message: str
    where: str | None = None  # "SKILL.md, line 4"


# The checks' version: bump it whenever they change, and every stored skill is checked
# again once at the API's start (SkillService.rescan). 1: L3c; 2: handing over
# credentials, "do not mention this", sentences that name files (L6).
RULES = 2


@dataclass(frozen=True, slots=True)
class ScanReport:
    findings: tuple[Finding, ...]

    @property
    def status(self) -> Status:
        if any(f.severity == "block" for f in self.findings):
            return "blocked"
        return "review" if self.findings else "clean"

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [asdict(f) for f in self.findings],
            "rules": RULES,
        }


@dataclass(frozen=True, slots=True)
class _Text:
    where: str  # the file
    text: str


Check = Callable[[SkillContent, list[_Text]], Iterator[Finding]]

INJECTION = [
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|"
        r"all|your|system)\b[^.\n]{0,20}\b(instructions?|rules?|prompts?|guidelines?)",
        r"\byou are now\b",
        r"\b(developer|god|jailbreak|dan) mode\b",
        r"\b(do not|don't|never)\s+(tell|inform|show|mention|reveal)\b[^.\n]{0,30}"
        r"\b(the user|anyone|them)\b",
        # Sending something out: a sentence may name files (".env") on the way.
        r"\b(send|post|upload|forward|email|exfiltrate)\b[^\n]{0,80}?\b(to|at)\b[^\n]{0,20}"
        r"(https?://|[\w.+-]+@[\w-]+\.)",
        # Handing over credentials, wherever to (not advice: "never share your API key").
        r"(?<!never )(?<!not )(?<!n't )"
        r"\b(send|share|include|collect|copy|give|leak|paste|post|upload|forward|email)\b"
        r"[^\n]{0,60}?\b(api[ _-]?keys?|access tokens?|passwords?|credentials|private keys?|"
        r"ssh keys?|session cookies?)\b",
        r"^\s*(system|assistant|developer)\s*:",
        r"</?(system|data|instructions?)\b[^>]*>",
        r"\b(reveal|print|show|output)\b[^.\n]{0,30}\b(system prompt|api keys?|secrets?|"
        r"environment variables|env vars?)\b",
    )
]
URL = re.compile(r"https?://[^\s)<>\"'\]]+", re.IGNORECASE)
ENCODED = re.compile(r"(?:[A-Za-z0-9+/]{200,}={0,2})|(?:\b[0-9a-fA-F]{200,}\b)")
INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
EXECUTABLE_SUFFIXES = (
    ".sh",
    ".bash",
    ".zsh",
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".rb",
    ".pl",
    ".ps1",
    ".bat",
    ".cmd",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".jar",
)
EXECUTABLE_MAGIC = (b"\x7fELF", b"MZ", b"#!", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def scan(content: SkillContent) -> ScanReport:
    texts = [_Text(SKILL_FILE, content.skill_md())]
    texts += [_Text(f.path, t) for f in content.files if (t := f.text) is not None]
    findings = [finding for check in CHECKS for finding in check(content, texts)]
    return ScanReport(tuple(findings))


def _line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def secrets(content: SkillContent, texts: list[_Text]) -> Iterator[Finding]:
    for t in texts:
        for pattern in SECRET_PATTERNS:
            for m in pattern.finditer(t.text):
                yield Finding(
                    "secrets",
                    "block",
                    "This looks like a secret (a key, token or "
                    "password). Remove it: skills are text that agents and people "
                    "read.",
                    f"{t.where}, line {_line(t.text, m.start())}",
                )


def injection(content: SkillContent, texts: list[_Text]) -> Iterator[Finding]:
    for t in texts:
        for pattern in INJECTION:
            for m in pattern.finditer(t.text):
                phrase = " ".join(m.group(0).split())[:80]
                yield Finding(
                    "injection",
                    "review",
                    f"Tries to steer the agent beyond its "
                    f"task: “{phrase}”. Agents treat skill text as information, "
                    "never as rules, but check this is meant.",
                    f"{t.where}, line {_line(t.text, m.start())}",
                )


def links(content: SkillContent, texts: list[_Text]) -> Iterator[Finding]:
    hosts = sorted(
        {urlparse(m.group(0)).hostname or "?" for t in texts for m in URL.finditer(t.text)}
    )
    if hosts:
        listed = ", ".join(hosts[:5]) + (f" and {len(hosts) - 5} more" if len(hosts) > 5 else "")
        yield Finding(
            "links",
            "review",
            f"Mentions web addresses: {listed}. Check they're the ones you expect.",
        )


def encoded(content: SkillContent, texts: list[_Text]) -> Iterator[Finding]:
    for t in texts:
        if m := ENCODED.search(t.text):
            yield Finding(
                "encoded",
                "review",
                "Contains a long encoded block (it could hide text people can't read).",
                f"{t.where}, line {_line(t.text, m.start())}",
            )


def invisible(content: SkillContent, texts: list[_Text]) -> Iterator[Finding]:
    for t in texts:
        if m := INVISIBLE.search(t.text):
            yield Finding(
                "invisible",
                "review",
                "Contains invisible characters (they can hide instructions from people).",
                f"{t.where}, line {_line(t.text, m.start())}",
            )


def code(content: SkillContent, texts: list[_Text]) -> Iterator[Finding]:
    found = [
        f.path
        for f in content.files
        if f.kind == "script"
        or f.path.lower().endswith(EXECUTABLE_SUFFIXES)
        or f.data.startswith(EXECUTABLE_MAGIC)
    ]
    if found:
        listed = ", ".join(found[:5]) + (f" and {len(found) - 5} more" if len(found) > 5 else "")
        yield Finding(
            "code",
            "review",
            f"Has code: {listed}. It's kept, but never run, and "
            "agents can't read it: Nuria can't run skill code yet.",
        )


def size(content: SkillContent, texts: list[_Text]) -> Iterator[Finding]:
    tokens = estimate_tokens(content.instructions)
    if tokens > WARN_TOKENS:
        yield Finding(
            "size",
            "review",
            f"Long instructions (about {tokens:,} tokens): agents "
            "read all of it when they load the skill.",
            SKILL_FILE,
        )


CHECKS: tuple[Check, ...] = (secrets, injection, links, encoded, invisible, code, size)
