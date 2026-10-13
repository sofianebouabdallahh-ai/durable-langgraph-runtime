# Phase 3 plan — Streaming across replicas

> **Status: delivered.** Every success criterion passed; results are in [progress/phase-03.md](../progress/phase-03.md).

**Goal:** a client can watch any run live from **any** API replica. Every persisted event arrives exactly once and in order, with no sticky sessions, surviving reconnects, replica shutdowns and lost pub/sub messages.

**Done when:** AC3 passes as `make demo-replicas` (PASS/FAIL per check): a run is created on replica A and streamed from replica B, every event arrives in order, and with pub/sub disabled on B the stream visibly stalls. Plus the success criteria below.

**Requirements:** R1.5 (publish after persist; transient `token` events) · R2.5 (subscribe → replay → dedup by `seq` → back-fill gaps; no session affinity) · §5 `GET /runs/{id}/stream` (SSE, heartbeat every 15 s) · CR-001 D3 (SSE with `Last-Event-ID`; channels generic over `run:{id}` and `session:{id}`) · R10.7 API part (on shutdown: fail `/readyz`, send `reconnect`, close).

---

## 1. Research findings

| Topic | Finding | Source / evidence |
|---|---|---|
| Redis Pub/Sub delivery | **At-most-once.** A message is lost if the subscriber isn't connected or fails while handling it, and a resubscribed client doesn't know what it missed. The recommended pattern: keep durability elsewhere and use Pub/Sub only as a low-latency wake-up, with subscribers catching up on reconnect. | [Redis Pub/Sub docs](https://redis.io/docs/latest/develop/pubsub/), [Instaclustr](https://www.instaclustr.com/blog/redis-pub-sub-part-1/), [OneUptime](https://oneuptime.com/blog/post/2026-03-31-redis-pubsub-message-delivery-guarantees/markdown) |
| ⇒ Consequence | Our design already persists every event first (R1.5). Pub/Sub is only a *notification*; correctness comes from Postgres replay + gap back-fill. A lost publish, including the **last** one (`run.completed`), must not leave a stream hanging. So we also need a slow **safety-net poll**. | Reasoning |
| SSE protocol | `id:` is what the browser sends back as `Last-Event-ID` on reconnect; `retry:` sets the reconnect delay; comment lines (`: ping`) keep idle connections alive through proxies. | [Rocket SSE docs](https://api.rocket.rs/v0.5/rocket/response/stream/struct.Event.html), [BestHTTP EventSource](https://besthttp-documentation.readthedocs.io/en/dev/5.EventSource/) |
| SSE in FastAPI | **FastAPI ≥ 0.135 has a built-in `EventSourceResponse`** (we run 0.141.1). It sends `: ping` after 15 s idle (our R5 heartbeat) and supports `id`/`event`/`retry` via `ServerSentEvent`. **No new dependency.** It does *not* set `Cache-Control: no-cache` or `X-Accel-Buffering: no`; we add them so proxies (nginx/Ingress) don't buffer the stream. | [FastAPI SSE reference](https://fastapi.tiangolo.com/reference/sse/) + read the installed source |
| Disconnects | Starlette cancels the response generator when the client disconnects, so cleanup goes in `finally` (unsubscribe, drop the queue). | Installed source |
| Graceful shutdown | Uvicorn waits for open connections up to `timeout_graceful_shutdown`, and a never-ending SSE stream blocks shutdown. Streams must watch a shutdown signal and finish within a grace period shorter than the server's (sse-starlette's documented `shutdown_event` + grace pattern; MCP SDK hit the same issue). | [tessl uvicorn docs](https://tessl.io/registry/tessl/pypi-uvicorn/files/docs/server.md), [sse-starlette](https://pypi.org/project/sse-starlette), [MCP SDK PR #2259](https://github.com/modelcontextprotocol/python-sdk/pull/2259) |
| redis-py Pub/Sub | `redis.asyncio` `PubSub.subscribe/unsubscribe/get_message(timeout)/listen()`. **One connection can subscribe to many channels**, so a replica can multiplex every stream it serves over one subscription. | Inspected the installed API (8.1.0) |

## 2. Design

```
 worker:  BEGIN … checkpoint + events + steps … COMMIT ──► then PUBLISH run:{id} {event JSON}
 api:     BEGIN … run.created / run.cancelled … COMMIT ──► then PUBLISH
                                                  │ Redis Pub/Sub: at-most-once wake-up
                                                  ▼
 API replica (any): one Redis subscription ── Broker ── fan-out to local streams (bounded queue each)
                                                  │
   GET /runs/{id}/stream ── StreamMerger ── SSE  id: seq · event: type · data: {...}
     1. subscribe (before replay, so nothing slips between)
     2. replay from Postgres: seq > Last-Event-ID
     3. live: drop seq ≤ last (dup), back-fill from Postgres if seq > last + 1 (gap)
     4. safety net: no live event for 15 s → poll Postgres (catches lost publishes)
     5. end after the terminal event · `: ping` keep-alive · `reconnect` on shutdown
```

**Key decisions**

1. **Publish after commit, never before or inside.** Publishing inside the transaction could announce an event that then rolls back, for example a zombie's write rejected by the fence. The executor collects the events a transaction wrote and publishes them only after `COMMIT`. A publish failure is logged and never fails the run: Postgres has the event, and clients back-fill it.
2. **Pub/Sub is a hint, Postgres is the record** (the same rule as phase 2's queue). A client can never miss an event; the worst case is latency (the safety-net poll interval).
3. **One Redis subscription per replica, fanned out in-process** (Pub/Sub multiplexer). 100 open streams use one Redis connection, not 100. Channels are subscribed when the first local stream needs them and unsubscribed when the last one leaves (reference counting).
4. **Slow clients can't hurt others.** Each stream has a bounded queue. If it overflows, the stream drops its live backlog and catches up from Postgres. The broker never blocks.
5. **The merge algorithm is pure** (functional core, imperative shell). The subscribe → replay → dedup → back-fill logic is a small state machine with no I/O, tested with **property-based tests** (random interleavings, duplicates, drops and reorderings must always produce 1…N in order, exactly once).
6. **Transient events** (`token`, phase 6) are published but never persisted. They carry the `seq` they follow (`after_seq`), are sent without an SSE `id:` (so they never become a resume point), and are never used for gap detection.
7. **API graceful shutdown.** On SIGTERM, `/readyz` returns `503`, new streams are refused (`503` + `Retry-After`), and every open stream gets `event: reconnect`, then closes. The client reconnects (to another replica) with `Last-Event-ID` and loses nothing. Uvicorn's shutdown hook is a risk, so it starts with a short **spike**.
8. **Generic channels.** `run:{id}` now; the same broker and merger serve `session:{id}` in phase 6.
9. **Replicas are local processes** (API ×2 + workers ×2), consistent with phase 2; Compose/containers come in phase 12.
10. **Considered: Postgres `LISTEN/NOTIFY` instead of Redis Pub/Sub.** It's attractive because a `NOTIFY` is delivered only if the transaction commits. Rejected for v1.0: the spec prescribes Redis Pub/Sub (R2.5), and `NOTIFY` needs a dedicated connection per replica and caps payloads at 8 KB. Recorded as an ADR.

**Patterns:** Publish-Subscribe · Publish-after-commit · Ports & Adapters (`EventBus` → Redis / in-memory) · Pub/Sub multiplexer with reference counting · Bounded queue + catch-up (backpressure) · Functional core, imperative shell (pure merger) · Anti-entropy / reconciliation (safety-net poll).

## 3. Tasks

| # | Task | Requirements | Tests (written with the task) |
|---|---|---|---|
| 3.1 | **`EventBus` port**: Redis Pub/Sub adapter + in-memory fake; wire format (persisted vs transient events); channel names (`run:`, `session:`) | R1.5, CR-001 | Contract suite against both adapters |
| 3.2 | **Publish after commit**: the executor's outbox, completion/failure/release, and API-written events (created, cancelled) publish after `COMMIT`; failures logged, never fatal | R1.5 | Rolled-back (fenced) events are never published; Redis down doesn't affect runs |
| 3.3 | **`StreamMerger`**: the pure subscribe/replay/dedup/back-fill/terminal algorithm | R2.5 | Unit + **property-based** tests (`hypothesis`) |
| 3.4 | **Broker**: one subscription per replica, reference-counted channels, bounded per-stream queues, overflow → catch-up | R2.5 | 100 streams → 1 Redis connection; unsubscribe on last leave; a slow client doesn't delay others |
| 3.5 | **SSE endpoint** `GET /runs/{id}/stream`: `Last-Event-ID` / `?after_seq`, headers, `: ping`, safety-net poll, close after terminal, `404` for unknown runs | §5, R2.5, D3 | Live, late join, reconnect mid-run, lost publishes, keep-alive |
| 3.6 | **API graceful shutdown** (spike first): drain flag, `/readyz` `503`, refuse new streams, `reconnect` event, close within the grace period | R10.7 (API) | SIGTERM with open streams: clients get `reconnect`; the process exits in time |
| 3.7 | **E2E**: harness with 2 API replicas + 2 workers; `make demo-replicas` (AC3), incl. pub/sub-disabled stall and reconnect across a replica shutdown; delivery latency measured | AC3 | Scenarios run in CI and 5× locally |
| 3.8 | Phase summary, design doc, ADR (Pub/Sub vs LISTEN/NOTIFY), PR | — | Coverage ≥ 90 % |

**Order:** 3.1 → 3.2 → 3.3 → 3.4 → 3.5 is the core; 3.6 can be built alongside 3.5; 3.7 needs everything.

**Estimate:** ~10–14 focused hours (the roadmap said 6–8; the API shutdown work, the safety net and the property tests are new).

## 4. Success criteria

"e2e" = real processes (2 API replicas + 2 workers) on real Postgres and Redis, as in phase 2.

| # | Criterion | Measured by | Pass when |
|---|---|---|---|
| SC1 | **Complete, ordered, exactly-once delivery**: 10 concurrent runs, each streamed by a client | integration | every client receives `seq` 1…N with no gaps or duplicates, in order; each stream closes after its terminal event |
| SC2 | **Any replica (AC3)**: create on replica A, stream on replica B | `make demo-replicas` (e2e) | every event arrives, in order, exactly once; **p95 delivery latency < 250 ms** (commit → client) |
| SC3 | **Late join and reconnect**: join after completion; disconnect mid-run and reconnect with `Last-Event-ID` | integration + e2e | full replay; after reconnect, the union of both connections is 1…N with no duplicates |
| SC4 | **Lost publishes are recovered**: inject loss of 30 % of pub/sub messages, including the final `run.completed` | integration (fault-injecting bus) | every event still arrives, in order; the stream still closes, within the safety-net interval |
| SC5 | **Pub/Sub disabled on a replica (AC3 part 2)** | `make demo-replicas` | the stream visibly stalls: events arrive only in safety-net poll batches (no event sooner than the poll interval after its commit); re-enabled → real-time again |
| SC6 | **Merge algorithm is correct for any interleaving** | property-based test | for random replay/live orderings with duplicates, drops and reordering, output = 1…N in order, exactly once (≥ 500 generated cases) |
| SC7 | **Nothing uncommitted is ever published** | integration | a fenced (rolled-back) zombie write is never seen by any subscriber |
| SC8 | **Keep-alive and headers** | integration | an idle stream receives `: ping` at the configured interval; `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` |
| SC9 | **Graceful API shutdown** | e2e | SIGTERM a replica with open streams → each client gets `event: reconnect`, reconnects to the other replica with `Last-Event-ID`, misses nothing; `/readyz` is `503` while draining; the process exits within the grace period |
| SC10 | **Resource hygiene** | integration | 100 open streams on one replica → **1** Redis Pub/Sub connection; a channel is unsubscribed when its last stream closes; a client that stops reading doesn't delay others' events |
| SC11 | **Quality** | CI | all jobs green including e2e; branch coverage ≥ 90 %; each e2e scenario passes 5× in a row locally |

## 5. Risks

| Risk | Mitigation |
|---|---|
| Uvicorn's shutdown sequence doesn't let us notify open streams in time | Spike first (task 3.6); fall back to a drain flag set by our own signal handler that wraps uvicorn's |
| Timing-based assertions (latency, stall) are flaky on CI | Generous budgets on CI; measure and report the real numbers; deadline-bounded polling helpers |
| Property tests are slow | Pure algorithm, no I/O: hundreds of cases run in well under a second |
| Pub/Sub message loss is hard to reproduce for real | Fault-injecting `EventBus` adapter (a test double) that drops a chosen fraction or specific events |
