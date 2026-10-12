import uuid

import pytest

from agent_runtime.ids import new_id
from agent_runtime.runs.state import (
    TERMINAL,
    InvalidTransition,
    RunStatus,
    allowed_targets,
    check_transition,
    sources_of,
)

S = RunStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.QUEUED, S.RUNNING),
        (S.RUNNING, S.COMPLETED),
        (S.RUNNING, S.WAITING_APPROVAL),
        (S.RUNNING, S.WAITING_CHILDREN),
        (S.RUNNING, S.QUEUED),
        (S.WAITING_APPROVAL, S.QUEUED),
        (S.WAITING_CHILDREN, S.QUEUED),
    ],
)
def test_spec_transitions_are_allowed(current: RunStatus, target: RunStatus) -> None:
    check_transition(current, target)


@pytest.mark.parametrize("current", [s for s in RunStatus if s not in TERMINAL])
@pytest.mark.parametrize("target", [S.FAILED, S.CANCELLED])
def test_any_non_terminal_can_fail_or_cancel(current: RunStatus, target: RunStatus) -> None:
    check_transition(current, target)


@pytest.mark.parametrize("terminal", sorted(TERMINAL))
def test_terminal_states_are_final(terminal: RunStatus) -> None:
    assert allowed_targets(terminal) == frozenset()
    for target in RunStatus:
        with pytest.raises(InvalidTransition):
            check_transition(terminal, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.QUEUED, S.COMPLETED),  # must run first
        (S.WAITING_APPROVAL, S.RUNNING),  # must be re-claimed via queued (fresh lease)
        (S.WAITING_CHILDREN, S.RUNNING),
        (S.RUNNING, S.RUNNING),
    ],
)
def test_illegal_transitions_rejected(current: RunStatus, target: RunStatus) -> None:
    with pytest.raises(InvalidTransition, match=f"from {current} to {target}"):
        check_transition(current, target)


def test_sources_of_is_the_inverse_of_allowed_targets() -> None:
    for target in RunStatus:
        for source in RunStatus:
            assert (source in sources_of(target)) == (target in allowed_targets(source))


def test_status_values_match_the_database_check_constraint() -> None:
    """Migration 0001 hard-codes these strings in a CHECK constraint."""
    assert {s.value for s in RunStatus} == {
        "queued",
        "running",
        "waiting_approval",
        "waiting_children",
        "completed",
        "failed",
        "cancelled",
    }


def test_ids_are_uuid7_and_time_ordered() -> None:
    ids = [new_id() for _ in range(1000)]
    assert all(isinstance(i, uuid.UUID) and i.version == 7 for i in ids)
    assert ids == sorted(ids)  # same-millisecond ids stay ordered (monotonic counter)
