"""The run state machine (R1.1), as pure data plus one check.

    queued ──► running ──► completed
      ▲  │       │ │ │
      │  │       │ │ └──► waiting_approval ──► queued (approved)
      │  │       │ └────► waiting_children ──► queued (children done)
      │  │       └──────► queued (lease expired / graceful release)
      │  └──► (any non-terminal) ──► failed | cancelled

Waiting states always go back through `queued`: resuming means a worker must
claim the run again and acquire a fresh lease (R2.3), never continue in place.

Keeping the rules here, with no I/O, means every caller (API, worker, reaper)
asks the same question the same way, and the whole table is unit-testable.
"""

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CHILDREN = "waiting_children"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL


TERMINAL: frozenset[RunStatus] = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)

_ALLOWED: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.COMPLETED,
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_CHILDREN,
            RunStatus.QUEUED,  # lease expired (reclaim) or graceful release (R10.7)
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset({RunStatus.QUEUED}),  # approved → re-enqueued
    RunStatus.WAITING_CHILDREN: frozenset({RunStatus.QUEUED}),  # all children done
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}
# "any → failed / cancelled": every non-terminal state may end that way.
for _status in RunStatus:
    if not _status.is_terminal:
        _ALLOWED[_status] |= {RunStatus.FAILED, RunStatus.CANCELLED}


class FailureReason(StrEnum):
    """Why a run ended `failed` or `cancelled`. Stored in `runs.reason`."""

    ERROR = "error"
    TIMEOUT = "timeout"  # R1.7
    STEP_LIMIT = "step_limit"  # R1.7
    MAX_RECLAIMS = "max_reclaims"  # R2.4
    BUDGET_MODEL_CALLS = "budget:model_calls"  # R14.1
    BUDGET_TOOL_CALLS = "budget:tool_calls"
    BUDGET_TOKENS = "budget:tokens"
    BUDGET_COST = "budget:cost"
    LOOP_DETECTED = "loop_detected"  # R14.4
    DEPTH_LIMIT = "depth_limit"  # R14.6
    CHILDREN_FAILED = "children_failed"  # R2.8: every child failed
    REJECTED = "rejected"  # R1.4: approval rejected → cancelled
    CANCEL_REQUESTED = "cancel_requested"  # R1.6


class InvalidTransition(Exception):
    def __init__(self, current: RunStatus, target: RunStatus) -> None:
        super().__init__(f"run cannot go from {current} to {target}")
        self.current = current
        self.target = target


def allowed_targets(current: RunStatus) -> frozenset[RunStatus]:
    return _ALLOWED[current]


def sources_of(target: RunStatus) -> frozenset[RunStatus]:
    """Every status a run may be in for `target` to be legal (used in SQL WHERE)."""
    return frozenset(s for s, targets in _ALLOWED.items() if target in targets)


def check_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidTransition(current, target)
