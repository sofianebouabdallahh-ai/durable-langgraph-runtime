"""Nuria's errors, as exceptions you can branch on.

The API answers every error with RFC 9457 problem details (`type`, `title`, `status`,
`detail`, and fields of its own); each becomes the exception for its status, carrying the
problem. Branch on the class, or on `kind` (the end of `type`: `turn-active`, `run-terminal`).
"""

from __future__ import annotations

from typing import Any


class NuriaError(Exception):
    """Any error from Nuria, or on the way to it."""


class ConnectionFailed(NuriaError):
    """Nuria couldn't be reached (after the retries a request is allowed)."""


class ApiError(NuriaError):
    """Nuria answered with an error."""

    def __init__(
        self,
        status: int,
        problem: dict[str, Any] | None = None,
        *,
        retry_after_s: float | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status = status
        self.problem = problem or {}
        self.type: str = str(self.problem.get("type", ""))
        self.title: str = str(self.problem.get("title", ""))
        self.detail: str = str(self.problem.get("detail", "")) or f"HTTP {status}"
        self.retry_after_s = retry_after_s
        self.request_id = request_id  # finds the request's lines in Nuria's logs
        super().__init__(f"{status} {self.title or 'error'}: {self.detail}")

    @property
    def kind(self) -> str:
        """`turn-active`, `run-terminal`, `duplicate-send`, …: the last part of `type`."""
        return self.type.rstrip("/").rsplit("/", 1)[-1]


class BadRequest(ApiError):
    """400."""


class NotFound(ApiError):
    """404: no such session, run, agent, …"""


class Conflict(ApiError):
    """409: the resource's state doesn't allow it (a turn is already active, the run ended)."""


class ValidationFailed(ApiError):
    """422: the request didn't validate. `errors` says where, when the request's own fields
    were wrong; other 422s say why in their fields (a limit's `field` and `maximum`)."""

    @property
    def errors(self) -> list[dict[str, Any]]:
        found = self.problem.get("errors")
        return found if isinstance(found, list) else []


class RateLimited(ApiError):
    """429: too many requests; `retry_after_s` says when to try again."""


class Unavailable(ApiError):
    """503: draining or paused; `retry_after_s` says when to try again."""


class ServerError(ApiError):
    """Any 5xx but 503."""


_BY_STATUS: dict[int, type[ApiError]] = {
    400: BadRequest, 404: NotFound, 409: Conflict, 422: ValidationFailed,
    429: RateLimited, 503: Unavailable,
}  # fmt: skip


def from_response(status: int, body: Any, headers: dict[str, str]) -> ApiError:
    problem = body if isinstance(body, dict) else None
    cls = _BY_STATUS.get(status) or (ServerError if status >= 500 else ApiError)
    return cls(status, problem, retry_after_s=retry_after(headers),
               request_id=headers.get("x-request-id"))  # fmt: skip


def retry_after(headers: dict[str, str]) -> float | None:
    """`Retry-After` in seconds (Nuria sends seconds, never a date)."""
    value = headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None
