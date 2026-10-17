# ADR-0004 — Live events: Redis Pub/Sub as a hint, Postgres as the record

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-12 |
| **Related** | R1.5, R2.5, CR-001 D3 (SSE), [phase 3 plan](../plans/phase-03.md) |

## Context

Clients stream a run's events from any API replica (no sticky sessions). Events are produced by worker processes on other machines. A replica therefore needs a low-latency way to learn "run X has a new event", and the client must never miss or duplicate one, across reconnects, replica restarts and message loss.

## Decision

1. **Every event is persisted in Postgres first** (`run_events`, gap-free `seq`). That is the record.
2. **After the transaction commits, the event is published to Redis Pub/Sub** on `run:{id}`. Pub/Sub is only a *wake-up hint*: it is at-most-once, and a lost message costs latency, never correctness.
3. **Each API replica holds one Pub/Sub subscription** and fans events out in-process (reference-counted channels, bounded per-stream queues).
4. **Each stream merges replay, live and back-fill through a pure algorithm** (`StreamMerger`): subscribe first, replay from Postgres, drop duplicates, back-fill holes, and poll Postgres as a safety net when nothing live arrives.

## Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Redis Pub/Sub** (chosen) | The spec prescribes it (R2.5); Redis is already deployed for the work queue; one connection multiplexes many channels; sub-millisecond fan-out | At-most-once; no delivery when no subscriber; publish is a separate step from the commit | Chosen, with Postgres as the record and the safety net covering loss |
| **Postgres `LISTEN/NOTIFY`** | Transactional: a `NOTIFY` is delivered only if its transaction commits, which removes the publish-after-commit step | A dedicated connection per replica, held outside the pool; 8,000-byte payload limit; notifications are also lost when the listener isn't connected, so the same catch-up is still needed; adds load to the database that is the system's only source of truth | Not for v1.0. Worth revisiting if Redis were removed from the stack |
| **Redis Streams per run** (durable, replayable) | Replay from Redis; at-least-once | A second durable copy of every event, which then has to agree with Postgres; retention and trimming per run; more memory | Rejected: duplicates the source of truth |
| **Polling Postgres only** | Simplest; no extra infrastructure | Latency equals the poll interval (seconds); load grows with the number of open streams | Kept only as the safety net |

## Consequences

- **Latency** is commit → publish → replica → client. It was measured at p50 17 ms / p95 24 ms locally (e2e, 2 replicas).
- **Losing Pub/Sub entirely** (Redis down or disabled) degrades streams to the safety-net poll interval (`STREAM_POLL_S`, default 15 s). Nothing is lost.
- **Publishing never fails a run.** A failed publish is logged and readers back-fill.
- **Phase 6 reuses all of it** for `session:{id}` channels.
