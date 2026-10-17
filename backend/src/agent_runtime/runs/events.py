"""Run event types (R1.5). Persisted to `run_events` before any publish."""

from enum import StrEnum


class EventType(StrEnum):
    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_RECLAIMED = "run.reclaimed"
    RUN_RELEASED = "run.released"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    NODE_FAILED = "node.failed"
    TOOL_CALLED = "tool.called"
    TOOL_COMPLETED = "tool.completed"
    INTERRUPT_RAISED = "interrupt.raised"
    APPROVAL_DECIDED = "approval.decided"  # R14.17
    RUN_RESUMED_AFTER_APPROVAL = "run.resumed"  # approved: back in the queue
    POLICY_DECISION = "policy.decision"  # R14.17: deny / require_approval
    HOOK_DECISION = "hook.decision"  # R15.8: any non-continue hook decision
    CHILD_STARTED = "child.started"
    CHILD_COMPLETED = "child.completed"
    # `token` is deliberately absent: it is pub/sub only and never persisted.
