# nuria: the Python client for Nuria

Send a message to a Nuria agent, follow the reply as it streams, and get a typed result: through a replica that drains, a connection that drops, or an approval that takes hours.

```python
import asyncio
from nuria import AsyncNuria, AwaitingApproval, Cancelled, Completed, Failed


async def main() -> None:
    async with AsyncNuria("http://localhost:3000/api") as nuria:
        session = await nuria.sessions.create(agent="chat")
        turn = await session.send("What is 6 × 7?")
        async for text in turn.text():
            print(text, end="", flush=True)
        match await turn.wait():
            case Completed(answer=answer):
                print("\n", answer)
            case AwaitingApproval(approval=pending):
                print(f"\nwaiting for your approval of {pending.tool} in Nuria")
            case Failed(reason=reason) | Cancelled(reason=reason):
                print("\nended:", reason)


asyncio.run(main())
```

`Nuria` is the same API without `await`.

## What it does for you

- **Streams that don't lose or repeat.** A turn's events come from the session's stream. A dropped connection, a refused one, a 429 or a 5xx is retried with backoff; a replica that drains sends `reconnect` and the client moves to another at once. Persisted events resume after the last one seen (`Last-Event-ID`) and are never shown twice.
- **A turn you can pick up anywhere.** `nuria.turn(session_id, run_id)` rebuilds the handle in another process, hours later.
- **One result type.** `wait()` returns `Completed`, `Failed`, `Cancelled` or `AwaitingApproval`. Waiting on an approval is a result, not a timeout.
- **Sends that are safe to retry.** Each send carries one `Idempotency-Key`, reused on every retry, so a retried send never makes a second turn.
- **Errors you can branch on.** Each API problem is an exception (`NotFound`, `Conflict`, `RateLimited`, `Unavailable`, …) carrying its `type` and fields.
- **Forward compatible.** A field, an event type or a status a newer Nuria adds is ignored, never an error.

## Approvals

The client shows a pending approval (its id, the tool, the arguments with secrets hidden, and how many values were hidden) and has no way to approve or reject it. Until Nuria can tell a person from a program, approving belongs to the person, in Nuria ([CR-007](../../docs/requirements/CR-007-client-sdks.md) R19.7).

## Layout

- `src/nuria/_generated/` is generated from Nuria's OpenAPI spec by `openapi-python-client` (`make sdk-python`). It is never edited, and private: its names follow the generator.
- The rest of `src/nuria/` is the hand-written client. Its stream and retry logic are sans-IO cores (`_sse.py`, `_resume.py`, `_retry.py`), tested without a network.

## Development

```
make sdk-python        # regenerate nuria/_generated from frontend/openapi.json
cd sdk/python && uv run pytest        # unit tests
uv run pytest -m stack                 # against a running Nuria (NURIA_URL, see tests/stack/)
uv run ruff check . && uv run mypy
```
