"""What an agent remembers, yours to see and remove (phase H8).

    GET    /agents/{name}/memory                    its notes (and its helpers'), newest
                                                    first, forgotten ones too
    DELETE /agents/{name}/memory/{note_id}          delete one for good
    POST   /agents/{name}/memory/{note_id}/restore  bring back one it was asked to forget
    DELETE /agents/{name}/memory                    forget everything, for good

A test's notes (a Studio test chat, an eval turn) aren't listed: they belong to the test.
Every change is audited by the note's id only: a deleted note's text doesn't live on in
the audit trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response, status
from pydantic import BaseModel, Field

from agent_runtime.audit import AuditLog
from agent_runtime.db import Pool
from agent_runtime.memory.store import Memory, Note, NoteNotFound

memory_router = APIRouter(prefix="/agents/{name}/memory", tags=["memory"])

AgentName = Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)]
NoteId = Annotated[str, Path(pattern=r"^[0-9a-f]{6,64}$")]


def _pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


PoolDep = Annotated[Pool, Depends(_pool)]


class NoteView(BaseModel):
    id: str
    text: str
    saved_at: datetime
    helper: str | None = Field(description="The helper that keeps it; None: the agent itself")
    session_id: uuid.UUID | None = Field(description="The chat it was saved in, if it's kept")
    forgotten_at: datetime | None = Field(description="When the agent was asked to forget it")

    @classmethod
    def of(cls, note: Note) -> NoteView:
        return cls(id=note.id, text=note.text, saved_at=note.saved_at, helper=note.author,
                   session_id=note.session_id, forgotten_at=note.forgotten_at)  # fmt: skip


class MemoryView(BaseModel):
    notes: list[NoteView]


class Cleared(BaseModel):
    deleted: int


@memory_router.get("", response_model=MemoryView, summary="What the agent remembers")
async def list_memory(name: AgentName, pool: PoolDep) -> MemoryView:
    async with pool.connection() as conn:
        notes = await Memory(conn).of_agent(name)
    return MemoryView(notes=[NoteView.of(n) for n in notes])


@memory_router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT,
                      summary="Delete a note for good")  # fmt: skip
async def delete_note(name: AgentName, note_id: NoteId, pool: PoolDep) -> Response:
    async with pool.connection() as conn, conn.transaction():
        found = await Memory(conn).delete(name, note_id)
        if found is None:
            raise NoteNotFound(note_id)
        await AuditLog(conn).record("memory.deleted", "note", found.id, after={"agent": name})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@memory_router.post("/{note_id}/restore", response_model=NoteView,
                    summary="Bring back a forgotten note")  # fmt: skip
async def restore_note(name: AgentName, note_id: NoteId, pool: PoolDep) -> NoteView:
    async with pool.connection() as conn, conn.transaction():
        memory = Memory(conn)
        restored_ = await memory.restore(name, note_id)
        if restored_ is None:
            raise NoteNotFound(note_id)
        found, changed = restored_
        if changed:  # a note that wasn't forgotten: nothing happened, nothing to audit
            await AuditLog(conn).record("memory.restored", "note", found.id,
                                        after={"agent": name})  # fmt: skip
        (restored,) = await memory.of_agent(name, found.key)
    return NoteView.of(restored)


@memory_router.delete("", response_model=Cleared, summary="Forget everything, for good")
async def clear_memory(name: AgentName, pool: PoolDep) -> Cleared:
    async with pool.connection() as conn, conn.transaction():
        deleted = await Memory(conn).delete_all(name)
        if deleted:
            await AuditLog(conn).record("memory.cleared", "agent", name,
                                        after={"deleted": deleted})  # fmt: skip
    return Cleared(deleted=deleted)
