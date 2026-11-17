"""Writes `nuria/_sync.py` from `nuria/_async.py` (`make sdk-python`; CI fails if they differ).

The sync client is the async one without `await`: one source, so the two can't drift. The
rules are textual and few; `_async.py` is written to keep them true (no `asyncio` but
`asyncio.sleep`, no async-only names in strings).

    uv run python scripts/unasync.py           write it
    uv run python scripts/unasync.py --check   exit 1 if it's not what this would write
"""

import re
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "nuria"
RULES = [
    (
        r'"""The async client\. `_sync\.py` is the same code without `await`\.',
        '"""The sync client: written from `_async.py` by `scripts/unasync.py`. Don\'t edit it.',
    ),
    (r"\bAsyncIterator\b", "Iterator"),
    (r"\basync def\b", "def"),
    (r"\basync for\b", "for"),
    (r"\basync with\b", "with"),
    (r"\bawait ", ""),
    (r"\basyncio\.sleep\b", "time.sleep"),
    (r"^import asyncio\n", ""),
    (r"\bhttpx\.AsyncClient\b", "httpx.Client"),
    (r"\bhttpx\.AsyncBaseTransport\b", "httpx.BaseTransport"),
    (r"\.aiter_text\(", ".iter_text("),
    (r"\.aread\(", ".read("),
    (r"\.aclose\(", ".close("),
    (r"\bdef aclose\b", "def close"),
    (r"\b__aenter__\b", "__enter__"),
    (r"\b__aexit__\b", "__exit__"),
    (r"\bAsyncNuria\b", "Nuria"),
    (r"\bAsyncSessions\b", "Sessions"),
    (r"\bAsyncSession\b", "Session"),
    (r"\bAsyncTurn\b", "Turn"),
    (r"`async with Nuria\(", "`with Nuria("),
]


def unasync(source: str) -> str:
    for pattern, replacement in RULES:
        source = re.sub(pattern, replacement, source, flags=re.MULTILINE)
    return source


def formatted(source: str, path: Path) -> str:
    """As `ruff format` leaves it (lines a rule shortened may now fit on one)."""
    done = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--stdin-filename", str(path), "-"],
        input=source, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout


def main() -> int:
    target = PACKAGE / "_sync.py"
    written = formatted(unasync((PACKAGE / "_async.py").read_text()), target)
    if "--check" in sys.argv:
        if target.read_text() != written:
            print("nuria/_sync.py is not what scripts/unasync.py writes: run make sdk-python")
            return 1
        return 0
    target.write_text(written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
