"""Approvals: one row per tool call a run asked a person to approve (phase H1, R1.4).

An approval is bound to the LangGraph interrupt that asked (`interrupt_id`) and to a
hash of the call's real arguments (`args_hash`). The worker resumes a run only with
decisions whose interrupt id and hash match what is pending (`decided_for`), so a
crash, an earlier decision or a changed call can never pass for an approval.

States: pending → approved | rejected | cancelled | superseded. Every change is a
compare-and-set (`… WHERE status = 'pending'`), so deciding twice can't happen.

Patterns:
- Repository: the only code that knows `run_approvals`' SQL; callers get immutable
  `Approval` objects. Bound to one connection; the caller owns the transaction
  (Unit of Work), e.g. the pause's fenced transaction or the decision's.
- State machine: the allowed statuses are a CHECK in the table, and only the methods
  here move a row between them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from agent_runtime.db import Conn
from agent_runtime.ids import new_id

Status = Literal["pending", "approved", "rejected", "cancelled", "superseded"]

APPROVAL_TYPE = "tool_approval"  # the interrupt value's `type` for an approval


def args_hash(args: dict[str, Any]) -> str:
    """The canonical hash of a call's real arguments (before any redaction)."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalConflict(Exception):
    """The decision can't apply (→ 409): unknown or already decided approval, or no
    `approval_id` while several are pending."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class ApprovalAsk:
    """What one pending interrupt asks, as the worker found it."""

    interrupt_id: str
    call_id: str | None
    tool: str
    args: dict[str, Any]  # as shown to the person: secrets redacted
    args_hash: str | None
    reason: str | None

    @classmethod
    def of(cls, interrupt_id: str, value: dict[str, Any]) -> ApprovalAsk:
        return cls(
            interrupt_id=interrupt_id,
            call_id=value.get("call_id"),
            tool=str(value.get("tool") or "unknown"),
            args=dict(value.get("args") or {}),
            args_hash=value.get("args_hash"),
            reason=value.get("reason"),
        )


@dataclass(frozen=True, slots=True)
class Approval:
    id: uuid.UUID
    run_id: uuid.UUID
    interrupt_id: str | None
    call_id: str | None
    tool: str
    args: dict[str, Any]
    args_hash: str | None
    reason: str | None
    status: Status
    edits: dict[str, Any] | None
    comment: str | None
    decided_by: str | None
    decided_at: datetime | None
    asked_epoch: int
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Approval:
        return cls(**{k: row[k] for k in _FIELDS})

    def payload(self) -> dict[str, Any]:
        """What the person is shown (transcript, events, API): never the real args."""
        return {
            "type": APPROVAL_TYPE,
            "approval_id": str(self.id),
            "tool": self.tool,
            "args": self.args,
            "call_id": self.call_id,
            "reason": self.reason,
        }

    def resume_value(self) -> dict[str, Any]:
        """What `interrupt()` returns in the tool pipeline: the decision, and the hash
        of the call that was approved (the pipeline refuses to run anything else)."""
        return {
            "decision": "approve",
            "edits": self.edits or {},
            "args_hash": self.args_hash,
            "approval_id": str(self.id),
        }


_FIELDS = (
    "id", "run_id", "interrupt_id", "call_id", "tool", "args", "args_hash", "reason",
    "status", "edits", "comment", "decided_by", "decided_at", "asked_epoch", "created_at",
)  # fmt: skip
_COLUMNS = ", ".join(_FIELDS)


class ApprovalRepository:
    """Persistence for approvals, bound to one connection."""

    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def pending(self, run_id: uuid.UUID) -> list[Approval]:
        """The approvals the run waits on, in the order they were asked."""
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM run_approvals WHERE run_id = %s AND status = 'pending' "
            "ORDER BY created_at, id",
            (run_id,),
        )
        return [Approval.from_row(r) for r in await cur.fetchall()]

    async def decided_for(self, run_id: uuid.UUID, asks: list[ApprovalAsk]) -> dict[str, Approval]:
        """The approved decision for each pending interrupt, keyed by interrupt id; only
        when its interrupt id AND args hash match (a changed call needs a new decision)."""
        if not asks:
            return {}
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM run_approvals WHERE run_id = %s AND status = 'approved' "
            "AND interrupt_id = ANY(%s)",
            (run_id, [a.interrupt_id for a in asks]),
        )
        approved = {r["interrupt_id"]: Approval.from_row(r) for r in await cur.fetchall()}
        return {
            a.interrupt_id: approved[a.interrupt_id]
            for a in asks
            if a.interrupt_id in approved and approved[a.interrupt_id].args_hash == a.args_hash
        }

    async def ask(self, run_id: uuid.UUID, epoch: int, asks: list[ApprovalAsk]) -> list[Approval]:
        """Record what the pending interrupts ask; return the approvals NEWLY asked.

        Idempotent: an interrupt already asked with the same arguments is left alone (a
        pause repeated after a crash doesn't ask twice). One whose arguments changed is
        superseded and asked again. Call inside the pause's fenced transaction."""
        created: list[Approval] = []
        for a in asks:
            cur = await self._conn.execute(
                f"SELECT {_COLUMNS} FROM run_approvals WHERE run_id = %s AND interrupt_id = %s "
                "AND status IN ('pending', 'approved') FOR UPDATE",
                (run_id, a.interrupt_id),
            )
            live = await cur.fetchone()
            if live is not None:
                if live["args_hash"] == a.args_hash:
                    continue  # asked already (and maybe decided) for this very call
                await self._conn.execute(
                    "UPDATE run_approvals SET status = 'superseded' WHERE id = %s", (live["id"],)
                )
            cur = await self._conn.execute(
                f"""INSERT INTO run_approvals (id, run_id, interrupt_id, call_id, tool, args,
                        args_hash, reason, asked_epoch)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}""",
                (new_id(), run_id, a.interrupt_id, a.call_id, a.tool, Jsonb(a.args),
                 a.args_hash, a.reason, epoch),
            )  # fmt: skip
            row = await cur.fetchone()
            if row is None:  # RETURNING on a successful INSERT always yields a row
                raise RuntimeError("INSERT INTO run_approvals returned no row")
            created.append(Approval.from_row(row))
        return created

    async def decide(
        self,
        run_id: uuid.UUID,
        approval_id: uuid.UUID | None,
        *,
        decision: Literal["approve", "reject"],
        edits: dict[str, Any] | None,
        comment: str | None,
        decided_by: str,
    ) -> Approval:
        """Decide one pending approval (compare-and-set). Without an id, only when exactly
        one is pending. Raises ApprovalConflict. Call with the run's row locked."""
        if approval_id is None:
            pending = await self.pending(run_id)
            if len(pending) != 1:
                raise ApprovalConflict(
                    f"{len(pending)} approvals are pending: say which one (approval_id)"
                    if pending
                    else "nothing is waiting for approval"
                )
            approval_id = pending[0].id
        status: Status = "approved" if decision == "approve" else "rejected"
        cur = await self._conn.execute(
            f"""UPDATE run_approvals SET status = %s, edits = %s, comment = %s,
                    decided_by = %s, decided_at = now()
                WHERE id = %s AND run_id = %s AND status = 'pending' RETURNING {_COLUMNS}""",
            (status, Jsonb(edits) if edits else None, comment, decided_by, approval_id, run_id),
        )
        row = await cur.fetchone()
        if row is None:
            cur = await self._conn.execute(
                "SELECT status FROM run_approvals WHERE id = %s AND run_id = %s",
                (approval_id, run_id),
            )
            found = await cur.fetchone()
            raise ApprovalConflict(
                f"approval {approval_id} is {found['status']}, not pending"
                if found
                else f"approval {approval_id} is not one of this run's"
            )
        return Approval.from_row(row)

    async def cancel_pending(self, run_id: uuid.UUID) -> int:
        """The run stopped (a rejection, a cancel): what it still asked is moot."""
        cur = await self._conn.execute(
            "UPDATE run_approvals SET status = 'cancelled' WHERE run_id = %s "
            "AND status = 'pending'",
            (run_id,),
        )
        return cur.rowcount
