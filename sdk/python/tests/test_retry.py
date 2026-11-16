"""Which requests are retried (CR-007 R19.6)."""

import pytest

from nuria._retry import NO_RETRIES, RetryPolicy

policy = RetryPolicy(jitter=lambda: 1.0)


@pytest.mark.parametrize("status", [None, 429, 502, 503, 504])
def test_a_safe_request_is_retried_on_a_failure_that_may_pass(status: int | None) -> None:
    assert policy.delay(1, safe=True, status=status) == 0.5


@pytest.mark.parametrize("status", [None, 429, 503])
def test_an_unsafe_request_is_sent_once(status: int | None) -> None:
    assert policy.delay(1, safe=False, status=status) is None


def test_duplicate_send_is_retried_with_the_same_key() -> None:
    assert policy.delay(1, safe=True, status=409, problem_kind="duplicate-send") == 0.5


@pytest.mark.parametrize(
    "kind", ["approval-conflict", "not-waiting-for-approval", "turn-active", ""]
)
def test_any_other_409_is_final(kind: str) -> None:
    """A 409 on an approval means it was decided already: never retried (R19.6)."""
    assert policy.delay(1, safe=True, status=409, problem_kind=kind) is None


@pytest.mark.parametrize("status", [400, 404, 422, 500])
def test_other_errors_are_final(status: int) -> None:
    assert policy.delay(1, safe=True, status=status) is None


def test_retry_after_is_honoured_and_capped() -> None:
    assert policy.delay(1, safe=True, status=503, retry_after_s=2.0) == 2.0
    assert policy.delay(1, safe=True, status=429, retry_after_s=900.0) == 60.0


def test_the_backoff_doubles_up_to_its_cap_and_stops_after_the_retries() -> None:
    delays = [policy.delay(n, safe=True) for n in (1, 2, 3)]
    assert delays == [0.5, 1.0, 2.0]
    assert policy.delay(4, safe=True) is None
    assert RetryPolicy(retries=10, jitter=lambda: 1.0).delay(10, safe=True) == 8.0


def test_no_retries() -> None:
    assert NO_RETRIES.delay(1, safe=True) is None
