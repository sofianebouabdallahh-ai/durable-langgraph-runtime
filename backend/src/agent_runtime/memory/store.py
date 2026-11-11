"""Memory across chats (phase H8): the notes an agent keeps, read and written in one place.

Pattern: Service Layer. The tools (save_note, recall_notes, forget_note), the prompt's
"What you remember" and the API all go through `Memory`, so what the model can see, what
it can change and what a person sees can't drift apart.

A note's scope is a `Scope` (Value Object), resolved from the run row by the database's
`run_memory_scope` (migration 0028), never from what the model says:
- the agent;
- the helper that keeps it (`author`; None for the agent itself);
- for a Studio test chat or an eval turn, the chat it keeps to (`test_scope`). A test's
  notes never reach real chats, and real notes don't sway a test (H6).

A forgotten note (`note_forgets`) is left out of everything the model sees. A person can
restore it or delete it for good.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_runtime.db import Conn
from agent_runtime.memory.rules import check

# Two notes are the same note with case, spacing and a final full stop ignored.
_SAME = r"regexp_replace(lower(regexp_replace(btrim({}), '\s+', ' ', 'g')), '[\s.!]+$', '')"
_IN_SCOPE = """
    n.agent = %(agent)s AND n.author IS NOT DISTINCT FROM %(author)s
    AND n.test_scope IS NOT DISTINCT FROM %(test)s
"""
_REMEMBERED = "NOT EXISTS (SELECT 1 FROM note_forgets f WHERE f.note_key = n.key)"
_ID = re.compile(r"[0-9a-f]{6,64}")
_WORD = re.compile(r"[^\W\d_]{3,}")
# Words that say nothing about what a note is about.
_COMMON = frozenset(
    [
        "the",
        "and",
        "that",
        "this",
        "with",
        "for",
        "from",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "you",
        "your",
        "yours",
        "his",
        "her",
        "their",
        "our",
        "its",
        "not",
        "but",
        "all",
        "any",
        "can",
        "will",
        "would",
        "should",
        "about",
        "into",
        "than",
        "then",
        "them",
        "they",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "how",
        "is",
        "my",
        "me",
        "mine",
    ]
)
SHOWN_ID = 8  # the id's length in the prompt; any unique prefix of 6+ finds the note


class NoSuchRun(LookupError):
    pass


class NoteNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Scope:
    agent: str
    author: str | None
    test_scope: uuid.UUID | None

    def params(self) -> dict[str, Any]:
        return {"agent": self.agent, "author": self.author, "test": self.test_scope}


@dataclass(frozen=True, slots=True)
class Note:
    key: str
    text: str
    saved_at: datetime
    author: str | None = None
    session_id: uuid.UUID | None = None
    forgotten_at: datetime | None = None

    @property
    def id(self) -> str:
        return self.key[:16]


@dataclass(frozen=True, slots=True)
class Recent:
    notes: list[Note]
    total: int  # all the scope's remembered notes, shown or not


async def scope_of(conn: Conn, run_id: uuid.UUID, author: str | None) -> Scope:
    cur = await conn.execute("SELECT agent, test_scope FROM run_memory_scope(%s)", (run_id,))
    row = await cur.fetchone()
    if row is None or row["agent"] is None:
        raise NoSuchRun(str(run_id))
    return Scope(row["agent"], author, row["test_scope"])


class Memory:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    # ------------------------------------------------------------- the model's

    async def save(
        self, *, key: str, run_id: uuid.UUID, epoch: int, text: str, author: str | None
    ) -> tuple[Note, bool]:
        """(the note, whether it was there already). The idempotency key is the primary
        key: the same call made again after a crash finds its note (R2.6). The epoch
        fence rejects a stale worker. Raises NotRemembered for what mustn't be kept."""
        check(text)
        if (done := await self._by_key(key)) is not None:
            return done, False
        scope = await scope_of(self._conn, run_id, author)
        cur = await self._conn.execute(
            f"SELECT n.key, n.text, n.created_at FROM notes n WHERE {_IN_SCOPE} "
            f"AND {_REMEMBERED} AND {_SAME.format('n.text')} = {_SAME.format('%(text)s')} "
            "ORDER BY n.created_at DESC LIMIT 1",
            scope.params() | {"text": text},
        )
        if (row := await cur.fetchone()) is not None:
            return _note(row), True
        await self._conn.execute(
            "INSERT INTO notes (key, run_id, text, epoch, author) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (key) DO NOTHING",
            (key, run_id, text, epoch, author),
        )
        saved = await self._by_key(key)
        assert saved is not None
        return saved, False

    async def recent(self, scope: Scope, limit: int) -> Recent:
        """The scope's newest remembered notes, newest first, and how many there are."""
        cur = await self._conn.execute(
            f"SELECT n.key, n.text, n.created_at, count(*) OVER () AS total FROM notes n "
            f"WHERE {_IN_SCOPE} AND {_REMEMBERED} ORDER BY n.created_at DESC LIMIT %(n)s",
            scope.params() | {"n": limit},
        )
        rows = await cur.fetchall()
        total = rows[0]["total"] if rows else 0
        return Recent([_note(r) for r in rows], total)

    async def still_remembered(self, keys: list[str]) -> list[Note]:
        """Of these notes, those still remembered (not forgotten, not deleted), newest
        first."""
        if not keys:
            return []
        cur = await self._conn.execute(
            f"SELECT n.key, n.text, n.created_at FROM notes n WHERE n.key = ANY(%(keys)s) "
            f"AND {_REMEMBERED} ORDER BY n.created_at DESC",
            {"keys": keys},
        )
        return [_note(r) for r in await cur.fetchall()]

    async def search(self, scope: Scope, query: str | None, limit: int) -> list[Note]:
        """Newest first; only those containing `query` (any case), when given."""
        cur = await self._conn.execute(
            f"SELECT n.key, n.text, n.created_at FROM notes n WHERE {_IN_SCOPE} "
            f"AND {_REMEMBERED} "
            "AND (%(q)s::text IS NULL OR strpos(lower(n.text), lower(%(q)s)) > 0) "
            "ORDER BY n.created_at DESC LIMIT %(n)s",
            scope.params() | {"q": query or None, "n": limit},
        )
        return [_note(r) for r in await cur.fetchall()]

    async def related(self, scope: Scope, text: str, *, besides: str) -> list[Note]:
        """The scope's remembered notes that look like they're about the same thing as
        `text` (`besides` excepted): a fact that changed, or a second note of what the
        person asked to forget. Measured with qwen2.5:7b: with two "gym locker" notes, it
        forgot one; told about the other, it can forget both."""
        mine = _words(text)
        if len(mine) < 2:
            return []
        recent = await self.recent(scope, 100)
        return [n for n in recent.notes if n.key != besides
                and len(mine & _words(n.text)) >= max(2, min(len(mine), 4) // 2)][:3]  # fmt: skip

    async def forget(
        self, scope: Scope, note_id: str, *, key: str, run_id: uuid.UUID, epoch: int
    ) -> Note | None:
        """Forget the scope's note whose id starts with `note_id`. None: no such note (or
        not this scope's), or more than one starts so. The same call made again after a
        crash finds what it forgot; forgetting a note twice is a no-op."""
        cur = await self._conn.execute(
            "SELECT n.key, n.text, n.created_at FROM note_forgets f "
            "JOIN notes n ON n.key = f.note_key WHERE f.key = %s",
            (key,),
        )
        if (row := await cur.fetchone()) is not None:
            return _note(row)
        found = await self._find(scope, note_id)
        if found is None:
            return None
        await self._conn.execute(
            "INSERT INTO note_forgets (note_key, key, run_id, epoch) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (found.key, key, run_id, epoch),
        )
        return found

    # ---------------------------------------------------------- a person's (API)

    async def of_agent(self, agent: str, key: str | None = None) -> list[Note]:
        """Everything the agent and its helpers remember, forgotten notes too, newest
        first (or only the note `key`). A test's notes are left out: they belong to the
        test."""
        cur = await self._conn.execute(
            "SELECT n.key, n.text, n.created_at, n.author, r.session_id, f.forgotten_at "
            "FROM notes n LEFT JOIN runs r ON r.id = n.run_id "
            "LEFT JOIN note_forgets f ON f.note_key = n.key "
            "WHERE n.agent = %s AND n.test_scope IS NULL AND (%s::text IS NULL OR n.key = %s) "
            "ORDER BY n.created_at DESC",
            (agent, key, key),
        )
        return [
            Note(r["key"], r["text"], r["created_at"], r["author"], r["session_id"],
                 r["forgotten_at"])
            for r in await cur.fetchall()
        ]  # fmt: skip

    async def delete(self, agent: str, note_id: str) -> Note | None:
        """Delete the note for good (its forget row goes with it)."""
        found = await self._of_agent(agent, note_id)
        if found is not None:
            await self._conn.execute("DELETE FROM notes WHERE key = %s", (found.key,))
        return found

    async def restore(self, agent: str, note_id: str) -> tuple[Note, bool] | None:
        """(the note, whether it was forgotten): restoring a remembered one changes nothing."""
        found = await self._of_agent(agent, note_id)
        if found is None:
            return None
        cur = await self._conn.execute(
            "DELETE FROM note_forgets WHERE note_key = %s RETURNING note_key", (found.key,)
        )
        return found, await cur.fetchone() is not None

    async def delete_all(self, agent: str) -> int:
        cur = await self._conn.execute(
            "DELETE FROM notes WHERE agent = %s AND test_scope IS NULL", (agent,)
        )
        return cur.rowcount

    # ---------------------------------------------------------------- helpers

    async def _by_key(self, key: str) -> Note | None:
        cur = await self._conn.execute(
            "SELECT key, text, created_at FROM notes WHERE key = %s", (key,)
        )
        row = await cur.fetchone()
        return _note(row) if row else None

    async def _find(self, scope: Scope, note_id: str) -> Note | None:
        """The scope's one remembered note whose key starts with `note_id`."""
        if not _ID.fullmatch(note_id := _clean(note_id)):
            return None
        cur = await self._conn.execute(
            f"SELECT n.key, n.text, n.created_at FROM notes n WHERE {_IN_SCOPE} "
            f"AND {_REMEMBERED} AND left(n.key, %(len)s) = %(id)s LIMIT 2",
            scope.params() | {"len": len(note_id), "id": note_id},
        )
        rows = await cur.fetchall()
        return _note(rows[0]) if len(rows) == 1 else None

    async def _of_agent(self, agent: str, note_id: str) -> Note | None:
        if not _ID.fullmatch(note_id := _clean(note_id)):
            return None
        cur = await self._conn.execute(
            "SELECT key, text, created_at FROM notes WHERE agent = %s AND test_scope IS NULL "
            "AND left(key, %s) = %s LIMIT 2",
            (agent, len(note_id), note_id),
        )
        rows = await cur.fetchall()
        return _note(rows[0]) if len(rows) == 1 else None


def _note(row: dict[str, Any]) -> Note:
    return Note(row["key"], row["text"], row["created_at"])


def _clean(note_id: str) -> str:
    """An id as a model copies it from the prompt: `[abcd1234]`, quoted, any case."""
    return note_id.strip().strip("[]()\"'` ").lower()


def _words(text: str) -> set[str]:
    """What a note is about, roughly: its words of 3+ letters, the common ones aside."""
    return {w for w in (m.group().casefold() for m in _WORD.finditer(text)) if w not in _COMMON}
