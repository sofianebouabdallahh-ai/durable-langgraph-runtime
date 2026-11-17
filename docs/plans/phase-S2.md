# Phase S2 plan — The Python SDK

**Goal:** a program uses Nuria in a few lines: send a message, follow the reply as it streams, and get a typed result, through a replica drain, a cut connection or an approval that takes hours.

```python
from nuria import AsyncNuria, Completed, AwaitingApproval

async with AsyncNuria("http://localhost:3000/api") as nuria:
    session = await nuria.sessions.create(agent="chat")
    turn = await session.send("What is 6 × 7?")
    async for text in turn.text():
        print(text, end="")
    match await turn.wait():
        case Completed(answer=answer): ...
        case AwaitingApproval(approval=pending): ...  # decided in Nuria, by the person
```

**Requirements:** [CR-007](../requirements/CR-007-client-sdks.md) R19.3, R19.4, R19.5, R19.6, R19.7. **Acceptance:** AC51, AC52, AC53. **Builds on:** S1's spec (described streams and errors).

---

## 1. Design

### 1.1 Layout (R19.3)
`sdk/python/` is its own package (`nuria`, Python ≥ 3.11, its own `uv.lock` under the repository's cooldown), next to `backend/` and `frontend/`: the SDK is a deliverable of its own (ADR-0001's layout gains `sdk/`).
- `nuria/_generated/`: `openapi-python-client` 0.29.1 (MIT, the newest release past the cooldown) from `frontend/openapi.json`. Never edited; regenerated in CI and failing on a diff, like the web app's types. Private: its names can change with the generator.
- `nuria/` (the rest): the hand-written Facade. The generator never touches it.

### 1.2 The Facade
| Piece | What it does | Pattern |
|---|---|---|
| `AsyncNuria`, `Nuria` | The entry points, async and sync, with the same API: `sessions.create/get/list`, `turn(session_id, run_id)` | Facade |
| `Session` | `send(text)`: one `Idempotency-Key` per send, reused on every retry (R19.6) | |
| `Turn` | A handle any process can rebuild from `(session_id, run_id)`: `events()`, `text()`, `wait()`, `cancel()` | Handle (Temporal's `WorkflowHandle`) |
| `wait()` | Returns `Completed`, `Failed`, `Cancelled` or `AwaitingApproval`; keeps waiting through `queued`, `running`, `waiting_children` and any status it doesn't know | Discriminated union of results (AWS waiters' end states) |
| `_sse.Decoder` | The WHATWG event-stream parser, no I/O | sans-IO |
| `_resume.Resumption` | R19.5's rules as a state machine, no I/O: the cursor, dedupe, `reconnect`, backoff, what's fatal | State, sans-IO |
| `_retry.RetryPolicy` | Which requests retry, how long to wait (`Retry-After`), and that a 409 on approval is final | Strategy |
| `errors` | One exception per problem kind (`NotFound`, `Conflict`, `RateLimited`, `Unavailable`, …), each with the problem's `type` and fields | |

- **The stream is the session stream, filtered to the turn**: it carries the turn's messages (persisted, replayed after `Last-Event-ID`) and its tokens and status (transient). The turn ends on its `turn.status`; after any reconnect the Facade asks the run its status first, and if the turn ended meanwhile it reads the missed messages from `GET /sessions/{id}/messages` instead, so a lost transient status can't leave it waiting.
- **Tolerant reading (R19.4):** the Facade reads only the fields it needs from the JSON, so a new field, event type or status from a newer server is ignored, never an error. The generated models are used to build requests.
- **No deciding (R19.7):** `AwaitingApproval` carries the approval's id, tool, arguments and `hidden` count; there is no `approve()`. The person decides in Nuria.

### 1.3 Tests
- **Unit:** the decoder on the WHATWG examples and split chunks; the resumption machine on recorded streams (a drain, a cut, a duplicate replay, a 404, a 503); the retry policy; the Facade against an `httpx.MockTransport` server that drops and drains on cue.
- **On the real stack** (`sdk/python/tests/stack/`): AC51 (a turn streamed through a `docker stop` of the API replica serving it and a `docker kill`, every persisted event once, `Completed`), AC52 (a turn that asks for approval: `AwaitingApproval`, then approved through the API as the person would, then a handle rebuilt in a new process gets `Completed`), AC53 (a send retried with the same key, including after a 409, makes one turn). 5×, in CI's container job.

## 2. Tasks

| # | Task | Done when |
|---|---|---|
| 1 | `sdk/python` project, the generator pinned, `make sdk-python` regenerates | `_generated` builds; `mypy --strict` passes on the package |
| 2 | `_sse` and `_resume`, sans-IO | Their unit tests pass, every R19.5 rule covered |
| 3 | Errors and the retry policy | 409 on approval never retried; sends retried with their key |
| 4 | The Facade, async and sync | Mock-server tests pass for both |
| 5 | The real-stack suite | AC51–AC53 pass 5/5 |
| 6 | CI | a `sdk-python` job: lint, types, unit, regenerate-and-diff; the stack suite in the container job |
| 7 | Docs | `sdk/python/README.md`, the design catalogue, the CHANGELOG, the summary |

## 3. Success criteria

| # | Criterion | How it's measured |
|---|---|---|
| 1 | **AC51** | The stack suite's drain-and-cut scenario 5/5: every persisted event of the turn seen exactly once, in order, against `GET /sessions/{id}/messages`; at least one `reconnect` followed |
| 2 | **AC52** | `wait()` returns `AwaitingApproval` with the pending approval's id; `nuria` has no way to decide; after an approval through the API, a new process's handle gets `Completed` |
| 3 | **AC53** | Two sends with one key, and a third after a `409 duplicate-send`, make one turn |
| 4 | R19.5 in isolation | Each rule has a unit test with a control (the rule removed from the machine fails it) |
| 5 | Nothing else changes | The backend, web app and stack suites still pass |

## 4. Out of scope
Publishing to PyPI (a release decision); deciding approvals (S4, after identity); the TypeScript SDK (S3).
