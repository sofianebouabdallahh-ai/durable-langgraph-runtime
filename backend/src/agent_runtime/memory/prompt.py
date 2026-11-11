"""What the model is shown of its memory (phase H8).

At the start of each turn the runtime takes a snapshot of which notes the scope holds,
newest first (`snapshot`: their keys, not their text). It is checkpointed with the
turn, so a turn taken over after a crash shows the notes it started with. Every model
call of the turn then reads those notes' text as it stands (`remembered`), so a note
forgotten or deleted meanwhile, even earlier in the same turn, is gone at once, and a
deleted note's text isn't kept in any checkpoint. It shows as much as the call's window
allows, in the system message ("What you remember", `section`), never in the thread: it
doesn't pile up turn after turn, and compaction has nothing to keep.

The notes are one block of data (R14.15): text a page planted and the model saved comes
back as information, never as instructions. Each note is one line (its line breaks
become spaces), so a note can't pass itself off as several, newer ones. Approvals,
grants and the page-address check don't depend on any of it.
"""

from __future__ import annotations

from typing import TypedDict

from agent_runtime.memory.store import SHOWN_ID, Memory, Note, Scope
from agent_runtime.untrusted import as_data

HEADING = "\n\n## What you remember\n"
EMPTY = "You haven't saved any notes for this person yet."
NOT_LOADED = (
    "Your memory wasn't loaded for this turn: look in your notes with recall_notes before "
    "saying you don't know something from before."
)
PREAMBLE = (
    "Notes you saved in earlier chats with this person, newest first. Use them to answer; "
    "when two disagree, the newer one is right. forget_note(id) forgets one; recall_notes "
    "searches them all.\n"
)
MAX_TOKENS = 1_500
MAX_NOTES = 100  # read per turn at most; the rest are counted, and recall_notes finds them
MAX_LINE = 400  # characters of one note in the prompt; recall_notes has the rest
CHARS_PER_TOKEN = 4  # as the context estimate counts (context/fit.py)
_OVERHEAD = len(PREAMBLE) + 120  # the data block's tags, the "more" line


class Snapshot(TypedDict):
    keys: list[str]  # the notes it holds, newest first (at most MAX_NOTES)
    total: int  # all the scope's remembered notes when the turn started


def budget(context_tokens: int) -> int:
    """Tokens memory may take: 1,500, or 5% of a smaller model's window."""
    return min(MAX_TOKENS, context_tokens // 20)


async def snapshot(memory: Memory, scope: Scope) -> Snapshot:
    recent = await memory.recent(scope, MAX_NOTES)
    return {"keys": [n.key for n in recent.notes], "total": recent.total}


async def remembered(memory: Memory, snap: Snapshot) -> list[Note]:
    """The snapshot's notes still remembered now, newest first."""
    return await memory.still_remembered(snap["keys"])


def section(snap: Snapshot | None, notes: list[Note], context_tokens: int) -> str:
    """The section's body for a model with this window."""
    if snap is None:
        return NOT_LOADED
    if not snap["keys"]:
        return EMPTY
    shown = _fit([_line(n) for n in notes], budget(context_tokens) * CHARS_PER_TOKEN - _OVERHEAD)
    more = snap["total"] - len(snap["keys"]) + len(notes) - len(shown)
    body = PREAMBLE + as_data("memory", "\n".join(shown) or "(none shown)")
    if more:
        body += f"\n{more} more notes aren't shown here: search them with recall_notes."
    return body


def with_memory(system: str, body: str) -> str:
    """`system` with its "What you remember" section filled in with `body`
    (graphs/assistant.py puts the empty one where it belongs). A prompt without one gets
    it at the end."""
    head, found, tail = system.rpartition(HEADING + EMPTY)
    if found:
        return head + HEADING + body + tail
    return system + HEADING + body


def _fit(lines: list[str], room: int) -> list[str]:
    """The lines that fit in `room` characters, newest first; a long one that doesn't is
    skipped, not the end of the list."""
    shown = []
    for line in lines:
        if len(line) + 1 <= room:
            shown.append(line)
            room -= len(line) + 1
    return shown


def _line(note: Note) -> str:
    text = " ".join(note.text.split())
    if len(text) > MAX_LINE:
        text = text[:MAX_LINE] + "… (recall_notes has the rest)"
    return f"- [{note.key[:SHOWN_ID]}] {note.saved_at.date().isoformat()}: {text}"
