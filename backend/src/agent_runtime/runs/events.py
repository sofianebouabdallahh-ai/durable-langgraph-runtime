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
    RUN_REDRIVEN = "run.redriven"  # H4: a person tried a failed run again
    CONTEXT_TRIMMED = "context.trimmed"  # H5: what one model call was sent was fitted
    CONTEXT_COMPACTED = "context.compacted"  # H5: older turns folded into a summary
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
    CHILD_COMPLETED = "child.completed"  # on the parent: one child reached a terminal state
    CHILDREN_SPAWNED = "children.spawned"  # R2.8: the parent fanned out and now waits
    CHILDREN_COMPLETED = "children.completed"  # every child ended: the parent is re-queued
    SUBAGENT_SPAWNED = "subagent.spawned"  # CR-005 R16.3
    SUBAGENT_PROGRESS = "subagent.progress"
    SUBAGENT_COMPLETED = "subagent.completed"  # any end: completed, failed, cancelled, timed_out
    # `token` is deliberately absent: it is pub/sub only and never persisted.
