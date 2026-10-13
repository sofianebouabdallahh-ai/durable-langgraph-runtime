# Phase 3 — Streaming across replicas

**Completed:** 2026-10-12 · **Branch:** `feat/phase-03-streaming` · **Plan:** [plans/phase-03.md](../plans/phase-03.md) · **ADR:** [0004](../adr/0004-live-events-redis-pubsub.md) · **Tests:** 211 (167 at the end of phase 2) · **Branch coverage:** 95 % (CI floor 90 %)

## What we built

**Event bus** ([streaming/bus.py](../../backend/src/agent_runtime/streaming/bus.py)). An `EventBus` interface (Ports & Adapters, as with phase 2's queue): a Redis Pub/Sub adapter and an in-memory fake, verified by one contract suite. It defines a wire format for *persisted* events (which carry `seq`) and *transient* ones (tokens, from phase 6: no `seq`, but `after_seq`), plus channel names `run:{id}` and `session:{id}`.

**Publish after commit.** The repository records every event it writes in a transaction (`emitted`); the caller publishes them only **after** `COMMIT`. For node events, the checkpointer gained an `after_commit` hook, so they're announced only once their checkpoint is durable. A rolled-back (fenced) zombie write is therefore never seen by anyone. Publishing is best effort and never fails a run.

**`StreamMerger`** ([streaming/merger.py](../../backend/src/agent_runtime/streaming/merger.py)). The pure core of R2.5. It takes events from replay, live and back-fill, in any order and possibly duplicated, and emits strictly `last+1, last+2, …`. It holds events that arrive ahead of a gap and reports exactly which range to back-fill. It has no I/O, so it's tested with **property-based tests: 600 generated interleavings per run, 0 failures**.

**Broker** ([streaming/broker.py](../../backend/src/agent_runtime/streaming/broker.py)). **One Redis Pub/Sub connection per API replica**, however many clients it serves. Channels are reference-counted. A single reader task resolves subscription confirmations, so opening a stream costs one round trip. Each stream has a bounded queue: a slow client is told to catch up from Postgres instead of slowing everyone down. After a dropped Redis connection, the broker reconnects, resubscribes and makes every stream catch up.

**SSE endpoint** `GET /runs/{id}/stream` ([streaming/session.py](../../backend/src/agent_runtime/streaming/session.py), [api/app.py](../../backend/src/agent_runtime/api/app.py)), in this order:
1. subscribe (confirmed by Redis)
2. replay from Postgres after `Last-Event-ID` / `?after_seq`
3. live events, with gaps back-filled from Postgres
4. a **safety-net poll** when nothing live arrives (Pub/Sub can lose even the final event)
5. `: ping` keep-alive, then close after the terminal event

Persisted events carry `id: <seq>`. Responses set `Cache-Control: no-cache` and `X-Accel-Buffering: no`; an unknown run is a `404`.

**Graceful API drain** (R10.7). `runtime api` runs a `DrainingServer`: on SIGTERM it flags the app *before* uvicorn begins shutting down. From then on, `/readyz` returns `503`, new streams get `503` + `Retry-After`, and open streams receive `event: reconnect` and close. Clients resume on another replica with `Last-Event-ID`.

**E2E with multiple replicas.** The harness runs N API replicas, each with its own environment. Three new scenarios: `replicas`, `stall` and `api-shutdown`, run as `make demo-replicas`.

## How it fits

```
 worker / API ── BEGIN … event rows … COMMIT ──► PUBLISH run:{id}   (after commit only)
                                                     │ at-most-once hint
 API replica (any) ── 1 subscription ── Broker ── bounded queue per stream
   GET /runs/{id}/stream: subscribe → replay (Postgres) → live ⇄ StreamMerger
                          → back-fill gaps · safety-net poll · ping · close on terminal
                          → `reconnect` on SIGTERM → client resumes elsewhere (Last-Event-ID)
```

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | 10 concurrent streams: complete, ordered, exactly once | ✅ Every stream equals the run's events in Postgres; each closed after `run.completed` |
| SC2 | **AC3: create on replica A, stream on replica B** | ✅ All events, in order; **p95 latency 16–23 ms** across 7 runs (target < 250 ms) |
| SC3 | Late join and reconnect with `Last-Event-ID` | ✅ Full replay; union of both connections exact, no overlap |
| SC4 | 30 % of publishes lost, **including every terminal event** | ✅ Every event still delivered in order; streams still closed |
| SC5 | **AC3 part 2: Pub/Sub disabled on a replica** | ✅ Still complete (from Postgres) but visibly stalled: median **~2–2.95 s** at a 3 s poll, while the live replica stayed at p95 ~20 ms on the same run |
| SC6 | Merge algorithm correct for any interleaving | ✅ 600 property-based cases per run |
| SC7 | Nothing uncommitted is ever published | ✅ A spy bus checks each publish from another connection; a control test proves the spy catches a violation; zombie writes are never announced |
| SC8 | Keep-alive and headers | ✅ `: ping` when idle; `text/event-stream`, `no-cache`, `X-Accel-Buffering: no` |
| SC9 | Graceful API shutdown mid-stream | ✅ Client gets `reconnect`, resumes on the other replica with nothing lost (e.g. 4 + 5 = 9 events); drained in **1.9–2.0 s** (grace 10 s) |
| SC10 | Resource hygiene | ✅ **100 streams → 1 Redis Pub/Sub connection**; unsubscribe when the last stream leaves; a slow stream doesn't delay a fast one; recovers after Redis drops the connection |
| SC11 | Quality | ✅ 211 tests; coverage 95 %; **30/30 e2e runs** (6 scenarios × 5, phase 2's included) |

## Concepts learned

- **At-most-once notification + durable log = exactly-once display.** Pub/Sub makes it fast; Postgres makes it complete; `seq` makes it exact.
- **Subscribe before you read.** Subscribing after the replay leaves a window in which an event is neither replayed nor received live.
- **Publish after commit.** The transactional-outbox idea applied to notifications: never announce what might still roll back.
- **Anti-entropy.** Any best-effort channel needs a periodic reconciliation with the source of truth. Here, the safety-net poll catches even a lost final event.
- **Backpressure without blocking.** A bounded queue per consumer, plus a cheap way to recover (re-read from the log), protects everyone from the slowest client.
- **Graceful shutdown for long-lived connections.** The server must *ask* streams to leave; waiting for them to finish on their own never ends.

## Decisions & trade-offs

- **Redis Pub/Sub over Postgres `LISTEN/NOTIFY`, Redis Streams or pure polling.** See [ADR-0004](../adr/0004-live-events-redis-pubsub.md).
- **FastAPI's own SSE support,** not `sse-starlette`. The response is a `StreamingResponse` with our own ping and poll loop (configurable for tests), and FastAPI's event formatter is reused.
- **Transient events are dropped if they arrive ahead of what the client has seen.** Tokens are ephemeral; correctness comes only from persisted events.
- **The API replicas never host workers,** so every e2e stream is cross-process by construction.

## Bugs found by testing (all fixed before merge)

- **Slow stream starts.** Opening a stream took ~50–100 ms (it waited for the reader's poll tick), and 100 opens took 5.5 s. Redesigned so the single reader resolves confirmations immediately: **100 opens in 1.0 s.**
- **The broker could never recover from a dropped Redis connection.** After a reconnect, resubscribing waited for a reader that only started afterwards, so every attempt timed out and live streaming stayed down for good (streams fell back to the 15 s poll). Found by a new test that makes Redis kill the connection.
- **A test that didn't test what it claimed.** The first overflow test passed without ever overflowing (coverage showed the path unexecuted). It was replaced by a deterministic test that stops reading while a burst lands.
- **A wrong expectation, not a bug.** The API replica exits with status −15 after a clean shutdown because uvicorn deliberately re-raises SIGTERM; verified in the source and log. The check now requires "shutdown complete" in the log plus exit 0 or −SIGTERM.

## Known issues & follow-ups

- **No WebSocket endpoint** (§5 marks it SHOULD; SSE is the primary transport per CR-001 D3). It's in the backlog.
- **No stream metrics yet** (subscribers per replica, delivery latency): phase 9.
- **The Ingress settings** (timeouts, buffering) and the `preStop` sleep are phase 12; the headers are already set.
- **No session streams yet:** the channel and merger are generic; phase 6 adds `/sessions/{id}/stream`.

## How to try it

```bash
make up && make worker                      # terminal 1: two workers
make api API_PORT=8765                      # terminal 2: replica A
cd backend && uv run --env-file ../.env runtime api --port 8766   # terminal 3: replica B
RUN=$(curl -s -X POST localhost:8765/runs -H 'content-type: application/json' \
      -d '{"graph":"toy","input":{"question":"hi","delay_s":1}}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])')
curl -N localhost:8766/runs/$RUN/stream     # created on A, streamed live from B
curl -N -H "Last-Event-ID: 3" localhost:8766/runs/$RUN/stream    # resume after seq 3

make demo-replicas                          # AC3 + stall + replica shutdown, PASS/FAIL
make demo-e2e REPEAT=5                      # all six scenarios
```
