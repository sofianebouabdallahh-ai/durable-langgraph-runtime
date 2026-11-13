"""Secrets: masked before they are stored, shown or written out.

One function, `redact()`, and two lists behind it (phase H10 made it so):

- `SECRET_PATTERNS`: what a key *looks like*. One regex per vendor, shaped after gitleaks'
  rules (our CI scans commits with them), each with a boundary so prose doesn't match
  ("risk-management", "the bearer of good news", a channel called "xoxo-team"). Best
  effort by nature: a pattern knows nothing of the vendors it hasn't heard of.
- `known_secrets`: the exact values Nuria *holds*. A saved model, search or MCP key is
  registered when it is opened (`keys.open_secret`), the settings' own secrets when they
  are read (`config.Settings`). Pattern: an allow-list of known values next to the pattern
  list. No regex can miss a value it was given.

Who calls `redact()`: the tool hooks (`redact_secrets_in_args`, `redact_secrets_in_result`,
`redact_secrets_in_reply`), the approval card's arguments, the skill scanner, run errors
and every log line (L7a). Since H10 the `post_tool` hooks run before the ledger write, so
`tool_invocations` keeps what the model was shown, never the raw result. One function, so
a key that's caught in one place is caught in all of them.

A redaction is idempotent (`redact(redact(x)) == redact(x)`): the pipeline relies on it to
run the hooks again on a cached result, and `redact_counted` on it to count only what a
card hides from the person.
"""

from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = [
    # OpenAI-style API keys; not the end of a word ("risk-management-guidelines-2026")
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key ids
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),  # GitHub tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.=]{16,}"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),  # user:password in URLs
    # H10, after gitleaks' defaults. Brave Search keys have no documented shape (checked
    # 2026-11-12): the one Nuria holds is covered by `known_secrets`.
    re.compile(r"\bAIza[\w-]{35}\b"),  # Google API keys
    re.compile(r"\bxoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*"),  # Slack bot tokens
    re.compile(r"\bxox[pe](?:-[0-9]{10,13}){3}-[a-zA-Z0-9-]{28,34}"),  # Slack user tokens
    re.compile(r"(?i)\bxapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+"),  # Slack app tokens
    re.compile(r"hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9+/]{43,56}"),
    # JWTs: two base64url JSON segments and a signature
    re.compile(r"\bey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9/_-]{17,}\.(?:[a-zA-Z0-9/_-]{10,}={0,2})?"),
    re.compile(r"\bhf_[A-Za-z]{34}\b"),  # Hugging Face tokens
    re.compile(r"\bglpat-[\w-]{20}\b"),  # GitLab personal access tokens
    re.compile(r"(?i)\bnpm_[a-z0-9]{36}\b"),  # npm tokens
    re.compile(r"\b(?:sk|rk)_(?:test|live|prod)_[a-zA-Z0-9]{10,99}\b"),  # Stripe keys
    # Azure AD client secrets (`…Q~…`), never a slice of a longer token
    re.compile(
        r"(?<![A-Za-z0-9_~.])[a-zA-Z0-9_~.]{3}\dQ~[a-zA-Z0-9_~.-]{31,34}(?![A-Za-z0-9_~.-])"
    ),
    re.compile(r"\btvly-[\w-]{20,}\b"),  # Tavily keys
]
REDACTED = "[REDACTED]"
MIN_KNOWN_CHARS = 8  # a shorter value is never registered: it would mask ordinary words


class KnownSecrets:
    """The exact values this process holds, masked wherever `redact()` runs.

    Pattern: allow-list of known values, next to the pattern list. Registered where a saved
    key is opened (`keys.open_secret`) and when the settings are read (every `SecretStr`
    they carry), so a value Nuria was given can't be missed for want of a pattern. Values
    shorter than `MIN_KNOWN_CHARS` are ignored. Nothing is forgotten: after a rotation the
    old key stays masked, which a log line written in its day still needs. The values live
    in this process's memory, as the settings' `SecretStr`s already do.

    Safe for asyncio and for the odd other thread (the log formatter) without a lock: an
    add replaces an immutable snapshot (copy on write), so a reader never iterates a set
    that changes under it. Longest first, so a value that contains another is masked whole.
    """

    def __init__(self) -> None:
        self._values: tuple[str, ...] = ()

    def add(self, *values: str | None) -> None:
        new = {v for v in values if v and len(v) >= MIN_KNOWN_CHARS} - set(self._values)
        if new:
            self._values = tuple(sorted({*self._values, *new}, key=len, reverse=True))

    def __contains__(self, value: object) -> bool:
        return value in self._values

    def __len__(self) -> int:
        return len(self._values)

    def mask(self, text: str) -> tuple[str, int]:
        """`text` with every known value replaced, and how many were."""
        hidden = 0
        for value in self._values:
            if value in text:
                hidden += text.count(value)
                text = text.replace(value, REDACTED)
        return text, hidden


known_secrets = KnownSecrets()


def redact(value: Any) -> Any:
    """Recursively replace the values Nuria holds and secret-looking substrings."""
    return redact_counted(value)[0]


def redact_counted(value: Any) -> tuple[Any, int]:
    """`redact`, and how many values it masked: what an approval card tells the person is
    hidden from it (H10). A value masked earlier counts for nothing, so with the pre_tool
    redaction on (the default) the card hides nothing: what it shows is what is sent."""
    count = [0]
    return _redact(value, count), count[0]


def _redact(value: Any, count: list[int]) -> Any:
    if isinstance(value, str):
        value, hidden = known_secrets.mask(value)  # exact values first: whole, counted once
        count[0] += hidden
        for pattern in SECRET_PATTERNS:
            value, n = pattern.subn(REDACTED, value)
            count[0] += n
        return value
    if isinstance(value, dict):
        return {k: _redact(v, count) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, count) for v in value]
    return value
