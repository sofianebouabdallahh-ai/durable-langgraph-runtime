"""Secret-looking substrings, replaced before anything is stored or written out.

Used by the tool hooks (arguments and results), the skill scanner, run errors and every
log line (phase L7a): one list of patterns, so a key that's caught in one place is caught
in all of them.
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
]
REDACTED = "[REDACTED]"


def redact(value: Any) -> Any:
    """Recursively replace secret-looking substrings."""
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub(REDACTED, value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
