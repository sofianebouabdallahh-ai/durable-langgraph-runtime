"""The Python client for Nuria (CR-007): send a message, follow the reply, get a typed result,
through replica drains, dropped connections and approvals that take hours.

    async with AsyncNuria("http://localhost:3000/api") as nuria:
        session = await nuria.sessions.create(agent="chat")
        turn = await session.send("What is 2 + 2?")
        result = await turn.wait()

`Nuria` is the same API, synchronous.
"""

from nuria._async import AsyncNuria, AsyncSession, AsyncSessions, AsyncTurn
from nuria._retry import RetryPolicy
from nuria._sync import Nuria, Session, Sessions, Turn
from nuria.errors import (
    ApiError,
    BadRequest,
    Conflict,
    ConnectionFailed,
    NotFound,
    NuriaError,
    RateLimited,
    ServerError,
    Unavailable,
    ValidationFailed,
)
from nuria.types import (
    AwaitingApproval,
    Cancelled,
    Completed,
    Failed,
    HelperEvent,
    Message,
    MessageEvent,
    PendingApproval,
    SessionInfo,
    StatusEvent,
    TokenEvent,
    TurnEvent,
    TurnResult,
)

__version__ = "0.1.0"

__all__ = [
    "ApiError",
    "AsyncNuria",
    "AsyncSession",
    "AsyncSessions",
    "AsyncTurn",
    "AwaitingApproval",
    "BadRequest",
    "Cancelled",
    "Completed",
    "Conflict",
    "ConnectionFailed",
    "Failed",
    "HelperEvent",
    "Message",
    "MessageEvent",
    "NotFound",
    "Nuria",
    "NuriaError",
    "PendingApproval",
    "RateLimited",
    "RetryPolicy",
    "ServerError",
    "Session",
    "SessionInfo",
    "Sessions",
    "StatusEvent",
    "TokenEvent",
    "Turn",
    "TurnEvent",
    "TurnResult",
    "Unavailable",
    "ValidationFailed",
]
