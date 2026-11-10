"""Which errors are the infrastructure's (phase H4): retried, not the end of the run."""

import psycopg
import psycopg_pool
import pytest
import redis.exceptions

from agent_runtime.queue import QueueUnavailable
from agent_runtime.runs.failures import REDRIVABLE, is_transient


@pytest.mark.parametrize(
    "exc",
    [
        psycopg.OperationalError("server closed the connection unexpectedly"),
        psycopg.errors.AdminShutdown("terminating connection due to administrator command"),
        psycopg.errors.CannotConnectNow("the database system is starting up"),
        psycopg.errors.SerializationFailure("could not serialize access"),
        psycopg.errors.DeadlockDetected("deadlock detected"),
        psycopg_pool.PoolTimeout("couldn't get a connection after 30 sec"),
        redis.exceptions.ConnectionError("Connection reset by peer"),
        redis.exceptions.TimeoutError("Timeout reading from socket"),
        QueueUnavailable("redis down"),
        ConnectionResetError(54, "Connection reset by peer"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_infrastructure_errors_are_transient(exc: BaseException) -> None:
    assert is_transient(exc)


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("a bug"),
        KeyError("missing"),
        psycopg.errors.UndefinedTable("relation does not exist"),  # a schema bug, not a blip
        psycopg.errors.UniqueViolation("duplicate key"),
        TimeoutError(),  # the run's own deadline: handled as `timeout`, never retried here
    ],
    ids=lambda e: type(e).__name__,
)
def test_other_errors_are_not(exc: BaseException) -> None:
    assert not is_transient(exc)


def test_a_wrapped_cause_is_found() -> None:
    try:
        try:
            raise psycopg.OperationalError("connection lost")
        except psycopg.OperationalError as inner:
            raise RuntimeError("checkpoint write failed") from inner
    except RuntimeError as outer:
        assert is_transient(outer)


def test_an_implicit_context_counts_unless_it_was_suppressed() -> None:
    try:
        try:
            raise redis.exceptions.ConnectionError("gone")
        except redis.exceptions.ConnectionError:
            raise RuntimeError("while publishing")  # noqa: B904 (the implicit context)
    except RuntimeError as during:
        assert is_transient(during)
    try:
        try:
            raise redis.exceptions.ConnectionError("gone")
        except redis.exceptions.ConnectionError:
            raise ValueError("a real bug") from None
    except ValueError as suppressed:
        assert not is_transient(suppressed)


def test_a_member_of_an_exception_group_is_found() -> None:
    group = ExceptionGroup("task group", [ValueError("x"), psycopg.OperationalError("lost")])
    assert is_transient(group)
    assert not is_transient(ExceptionGroup("task group", [ValueError("x")]))


def test_a_cycle_of_causes_ends() -> None:
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a
    assert not is_transient(a)


def test_only_failures_that_might_not_happen_again_can_be_retried() -> None:
    assert {"error", "infrastructure", "max_reclaims", "timeout"} == REDRIVABLE
    for final in ("budget:cost", "loop_detected", "step_limit", "turn_denied", "rejected"):
        assert final not in REDRIVABLE
