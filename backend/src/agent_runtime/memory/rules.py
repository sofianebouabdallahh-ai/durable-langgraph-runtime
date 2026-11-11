"""What may be remembered (phase H8). Pattern: Specification.

A note goes into every later chat's prompt, and so to the model's provider with every
turn: a secret saved once would leave with each of them. Refused, with the reason the
model passes on: keys and tokens (the patterns every log line is masked with), private
keys, card numbers (13 to 19 digits starting 2 to 6, as cards do, that pass the Luhn check),
and text a hook already masked (`[REDACTED]`: what's left isn't worth keeping).
"""

from __future__ import annotations

import re

from agent_runtime.redaction import REDACTED, SECRET_PATTERNS

_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_DIGITS = re.compile(r"(?<![\d-])[2-6](?:[ -]?\d){12,18}(?![\d-])")


class NotRemembered(ValueError):
    """The note can't be kept; the message says why, for the model to tell the person."""


def check(text: str) -> None:
    """Raise NotRemembered when `text` holds something that mustn't be stored."""
    if (
        REDACTED in text
        or any(p.search(text) for p in SECRET_PATTERNS)
        or _PRIVATE_KEY.search(text)
    ):
        raise NotRemembered(
            "Not saved: it looks like a key, token or password. Notes go to the model with "
            "every later chat, so secrets aren't kept: tell the person to keep it somewhere safe."
        )
    if any(_luhn(re.sub(r"\D", "", m.group())) for m in _DIGITS.finditer(text)):
        raise NotRemembered(
            "Not saved: it looks like a card number. Notes go to the model with every later "
            "chat, so card numbers aren't kept."
        )


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0
