# Phase S2 — The Python SDK

**Completed:** 2026-11-15 · **Branch:** `feat/s2-python-sdk` (on top of S1) · **Plan:** [plans/phase-S2.md](../plans/phase-S2.md) · **Requirements:** [CR-007](../requirements/CR-007-client-sdks.md) R19.3 to R19.7 · **Decision:** [ADR-0009](../adr/0009-client-sdks.md)

Nuria from Python, in a few lines, through everything a durable runtime does to a connection:

```python
async with AsyncNuria("http://localhost:3000/api") as nuria:
    session = await nuria.sessions.create(agent="chat")
    turn = await session.send("What is 2 + 2?")
    async for text in turn.text():
        print(text, end="")
    result = await turn.wait()   # Completed | Failed | Cancelled | AwaitingApproval
```

## What we built

**A package of its own** ([`sdk/python`](../../sdk/python/README.md), `nuria`, Python ≥ 3.11, its own `uv.lock` under the repository's cooldown). ADR-0001's layout gains `sdk/`.

**Generated calls** (`nuria/_generated`, 349 files). `openapi-python-client` 0.29.1, pinned exactly (0.30.0 is inside the cooldown), from S1's spec. Never edited: `make sdk-python` regenerates it, CI fails on any difference, and the repository's whitespace hooks leave it alone (on the first commit they rewrote hundreds of its files, which CI's regeneration would then have undone). One endpoint isn't generated: the run report, a `.zip` download.

**The Facade** (the rest of `nuria/`).
- `AsyncNuria` and `Nuria`, the same API. `_sync.py` is written from `_async.py` by [`scripts/unasync.py`](../../sdk/python/scripts/unasync.py) (21 textual rules, then `ruff format`); CI fails if it isn't what the script writes.
- The generated code builds each request; the Facade sends it and **reads the answer itself**. The generated parsers raise on a missing field or a status value they don't know (`RunView.from_dict` on a new status), which would break an older client against a newer Nuria (R19.4).
- `Session.send()` carries one `Idempotency-Key` (yours or a new one) through every retry (R19.6).
- `Turn` is a handle: `nuria.turn(session_id, run_id)` rebuilds it in any process. `events()` yields the turn's messages, tokens, status and helpers' progress; `text()` the reply's text, made whole from the stored message if a token was lost; `wait()` the result; `cancel()` cancels this run, never another turn of the session.
- `wait()` returns `Completed` (with the answer), `Failed` (with the reason and any wrap-up answer), `Cancelled`, or `AwaitingApproval` (with the approval's id, the tool, the redacted arguments and the `hidden` count). Every other status, `waiting_children` and unknown ones included, means keep waiting.
- **Nothing decides an approval** (R19.7). The generated package has the endpoint, as `curl` does; the SDK's API has no way to approve or reject.

**The sans-IO cores**, each tested without a network:
- [`_sse.Decoder`](../../sdk/python/src/nuria/_sse.py): the WHATWG event-stream parser. It keeps an event's own `id` apart from the standard's last-event-id buffer, because Nuria's transient events carry none.
- [`_resume.Resumption`](../../sdk/python/src/nuria/_resume.py): R19.5 as a state machine.
- [`_retry.RetryPolicy`](../../sdk/python/src/nuria/_retry.py): reads and keyed sends retry on connection failures, 429, 502, 503 and 504 (`Retry-After` first); `409 duplicate-send` retries with the same key; any other 409 is final.

**How a turn's stream ends.** The session stream never closes on its own, and a turn's status on it is transient: a status sent while the client was between connections is gone. So before every connection, and after 30 s with nothing but keep-alives, the client asks the run. If the turn stopped, it reads the messages it missed from `GET /sessions/{id}/messages` and ends with the run's status.

## Success criteria: results

Every run below is mine, on the committed branch, on 2026-11-15. The stack runs used a stack built from the branch (`s2check`), one heavy job at a time.

| # | Criterion | Result |
|---|---|---|
| 1 | **AC51:** a turn streams through a drain and a cut, every stored message once | ✅ 5/5. Each run: both API replicas stopped in turn (SIGTERM: `event: reconnect`) and the proxy killed and restarted; 15 messages seen exactly once, in order, equal to `GET /sessions/{id}/messages`; 2 or 3 reconnects, 1 or 2 of them drains; `Completed` with the answer |
| 2 | **AC52:** an approval is a result; the person decides | ✅ 5/5. `wait()` returned `AwaitingApproval` for `notify` with its approval id; the public API has no approve, decide or reject; approved through the API as the web app does, then a handle rebuilt in a new process returned `Completed` |
| 3 | **AC53:** a retried send makes one turn | ✅ 5/5 on the stack: six sends of one key, five at once, made one turn and one user message. The `409 duplicate-send` retry is covered by the unit tests: with the fix below, the real server answered every overlapping attempt 202 |
| 4 | R19.5 in isolation | ✅ Each of the seven rules removed from the state machine in turn (dedupe, the cursor only on ids, `reconnect`, 404 fatal, fresh attempts on progress, `Last-Event-ID`, giving up) fails the unit tests (1 to 5 tests each) |
| 5 | Nothing else changes | ✅ The table below |

| Check | Result |
|---|---|
| SDK: ruff, format, `mypy --strict`, unit tests | clean; 86 passed |
| SDK: `make sdk-python` regenerated twice, and `unasync --check` | identical files; no drift |
| The README's example, run against the stack | streamed the reply, `Completed` |
| Backend: unit and integration, with coverage | 1,090 passed, 3 skipped, **91.93 %** |
| CI's API drift step; `make api-breaking` against `main` | no drift; no breaking change |
| Web app (`pnpm check`) | 86 tests, build passes |
| Runtime e2e ×5 | 73/75 (448 checks). The two misses, then 20 reruns of each, all passing: see below |
| Tester setup twice (from the branch) | both healthy; `.env` identical |
| Container e2e | 9/9, 56 checks |
| Browser suite, observability on | 63 passed, 1 skipped (the live-model spec) |

## What running it found

- **Overlapping attempts of one send got `409 turn-active`** (fixed, `sessions/service.py`). The key was looked up only before the session lock: an attempt that overlapped the first (a client retrying after a timeout while the first was still committing) waited on the lock, then saw the first attempt's turn as another active turn. Found by AC53's five sends at once on the real stack; the key is now looked up again under the lock. A new integration test fails 3/3 without the fix.
- **Two schemas had one name** (`ResultView`). FastAPI published both under module-qualified names, and the generator dropped the four Tests endpoints. The Tests one is `TestResultView` (same shape; oasdiff's four lines accepted with the reason), and a spec test now fails on any qualified name.
- **The generated parsers would have broken forward compatibility.** `openapi-python-client`'s models raise on a missing field or a status they don't know. The Facade builds requests with them and reads answers itself.
- **The whitespace hooks rewrote generated code** on the first commit (hundreds of files), which CI's regeneration would then have undone. Generated code is excluded from them now.
- **Two runtime e2e scenarios each missed once in 75 runs** while the machine was loaded: "stream from any replica" (p95 latency 339 ms against 250 ms, one slow event of 8) and "parallel sub-agents in a chat" (no note saved: the main agent's `save_note` failed at execute). Rerun alone, each passed 20/20. The second check now prints the call's result from the ledger. One cause it may have been: the memory rules refuse a note that looks like a card number, and a note holding two random helper handles does that 0.14 % of the time (29 of 20,000 simulated); not proven for this run.
- **My own test was wrong once:** AC52 first called `notify` with the wrong arguments, so the call failed validation, no approval was asked, and the scripted model answered anyway. It now uses `to` and `message`.

## Design notes

- **Build with the generator, read by hand.** The generated code is exact about requests and strict about answers; for a long-lived client, strict answers are the wrong default.
- **Ask the run, not only the stream.** The session stream never closes on its own and a turn's status on it is transient, so the client checks the run before every connection and after 30 s of keep-alives. A turn that ended while the client was away is caught up from the stored messages.
- **A handle, not a blocking call.** A turn waits as long as it takes, hours for an approval, and any process can pick it up from two ids.
- **One source for two clients,** checked in CI, instead of two hand-kept copies.
