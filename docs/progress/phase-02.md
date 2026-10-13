# Phase 2 — Distributed workers

**Completed:** 2026-10-12 · **Branch:** `feat/phase-02-distributed-workers` · **Plan:** [plans/phase-02.md](../plans/phase-02.md) · **Tests:** 167 (116 at the end of phase 1) · **Branch coverage:** 95.0 % (CI floor 90 %)

## What we built

**Work queue** ([queue.py](../../backend/src/agent_runtime/queue.py)). A `WorkQueue` interface (Ports & Adapters) with two implementations:
- `RedisWorkQueue` on a Redis Stream + consumer group: competing consumers, at-least-once delivery, ack + delete, idle reclaim with `XAUTOCLAIM`, poison messages dropped
- an in-memory fake for fast tests

One contract test suite runs against **both**, so the fake can't drift from Redis.

**Outbox relay** ([runs/relay.py](../../backend/src/agent_runtime/runs/relay.py)). Creating a run writes to Postgres *and* sends a Redis message, and the second step can be lost (Redis down, API crash). The relay re-sends a message for any run that needs one but whose message is gone. Concurrent sweeps never double-send (`FOR UPDATE SKIP LOCKED`). That's what makes "Redis holds nothing that can't be rebuilt" true.

**Worker** ([worker.py](../../backend/src/agent_runtime/worker.py)). `runtime worker --concurrency C --workers N`. Each process:
- reads only as many messages as it has free slots (a bulkhead)
- executes each run with the phase-1 executor
- settles each message: ack when the run is finished or waiting; re-send then ack when it handed the run off; ack a duplicate only if it still holds it; otherwise leave it for the reaper
- runs the **reaper** (claims dead workers' messages) and the **relay** sweep in the background
- respects the kill switch

`--workers N` is a small **supervisor** that forwards stop signals to its children.

**Heartbeat touch.** Every lease renewal also resets the run's Redis message idle time, so a healthy run that's longer than the lease is never stolen by the reaper. This came from the research phase: Redis measures "idle" from the last delivery, not from the worker's last sign of life.

**Graceful shutdown** (R10.7). On SIGTERM a worker stops reading. Each in-flight run finishes its current step, then is released in one fenced transaction (`running → queued`, `run.released`, `releases + 1`, not a reclaim), and re-sent. Another worker picks it up within milliseconds. A second signal exits immediately.

**Cancellation and resume** (R1.6, R1.3):
- `POST /runs/{id}/cancel`: a queued run is cancelled immediately; a running one stops before its next node.
- `POST /runs/{id}/resume`: re-sends work for a queued or orphaned run, and does nothing for a live one.

Both return `409` for a run that has already ended.

**Kill switch** (R14.18). `/admin/pause`, `/admin/resume`, `/admin/cancel-all`, `/admin/state`. While paused, workers claim nothing and `POST /runs` returns `503` with `Retry-After`; runs already in flight finish. The state is stored in Postgres, so every replica sees it.

**The database enforces fencing** (migration `0004`). A trigger rejects any write whose epoch is older than the run's current epoch (SQLSTATE `EF001`), even in raw SQL that bypasses our code.

**Least-privilege database users** (migration `0005`, R14.13):
- **Group roles** `app_api`, `app_worker`, `app_ingest`, `app_sandboxd`, each with only the grants it needs.
- **Login users** are created by `runtime db provision-users` from `<COMPONENT>_POSTGRES_*`. That's an infrastructure step, so no password ever lives in a migration.
- **The API and the worker connect as their own users** and refuse to start without them.

**End-to-end harness and demos** ([tests/e2e/](../../backend/tests/e2e/)). A throw-away "cluster" of **real processes**: a fresh database, its own Redis stream, an API server and two worker processes. Three scenarios, each a list of named checks. They run as `make demo-crash`, `demo-zombie` and `demo-release` (printing PASS/FAIL) and as pytest tests in CI.

## How it fits

```
 POST /runs ─► INSERT run ─► XADD runs:work ◄── relay: re-send if the message is gone
                                 │ XREADGROUP (free slots)            ▲
                                 ▼                                    │ (every worker)
   worker process (C slots) ── RunExecutor ── lease + heartbeat (+ touch message)
       │  reaper: XAUTOCLAIM idle > TTL ─► lease decides who runs it (F2)
       │  SIGTERM: finish step → release → re-send → ack → exit
       └─ settle: ack · re-send · leave for reaper
 Postgres decides (lease, epoch, fencing trigger) · Redis only delivers hints
```

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | Runs created over HTTP execute without a manual command | ✅ All e2e scenarios |
| SC2 | 20 runs, 2 workers × 3 slots: each executed exactly once | ✅ All completed, epoch 1, every node once, both workers used, peak in-flight ≤ 3 |
| SC3 | **AC2: SIGKILL the owning worker** | ✅ One `run.reclaimed`, epoch 1 → 2, committed step not re-run, finished on the other worker; recovered in **6.4 s** (budget 10 s with a 3 s lease) |
| SC4 | **AC5: SIGSTOP the owner past its lease, then SIGCONT** | ✅ Taken over while frozen; **0 stale writes** after the takeover; completed exactly once; the zombie's own log shows it detected the lost ownership |
| SC5 | **Graceful hand-off on SIGTERM** | ✅ `run.released`, `releases = 1`, `reclaims = 0`; restarted by the other worker **0.01–0.02 s** after release (vs ≥ 3 s for a crash); clean exit 0 |
| SC6 | Redis is rebuildable | ✅ Redis down at creation, stream wiped, dead owner's message lost: all recovered by the relay |
| SC7 | A healthy run longer than 3 × TTL isn't stolen | ✅ epoch 1, `reclaims = 0` |
| SC8 | Cancellation | ✅ queued → cancelled immediately; running → before its next node (`answer` never started); terminal → `409` |
| SC9 | The database rejects a stale-epoch write in raw SQL | ✅ `EF001` on insert and update |
| SC10 | Least privilege | ✅ Worker can't DROP/DELETE/TRUNCATE/CREATE or flip the kill switch; API can't read checkpoints or tool results; **a full run works with only these grants** |
| SC11 | Kill switch | ✅ Paused → `503` + `Retry-After`, nothing claimed; resumed → work flows; cancel-all |
| SC12 | Quality | ✅ CI green, including the 3 e2e scenarios on Linux; coverage 95.0 %; **15/15** e2e passes locally (each scenario 5× in a row) |

## Concepts learned

- **Competing consumers and the pending list.** A consumer group gives each message to one worker. It stays "pending" until acknowledged, which is what makes delivery *at-least-once* rather than at-most-once.
- **At-least-once + idempotent decisions = effectively once.** Redis may deliver the same work twice; the lease guarantees only one worker executes it.
- **"Idle" isn't "dead."** Failure detection based on timeouts must be fed by the thing that's actually alive: hence the heartbeat touch.
- **The dual-write problem and the outbox pattern.** Two systems can't be updated atomically, so make one the source of truth and repair the other from it.
- **Graceful degradation of shutdown.** SIGTERM leads to a fast hand-off; SIGKILL leads to a slower reclaim. Both are correct; one is just faster.
- **Defence in depth.** The same invariant (no stale writes) is enforced in the application *and* in the database.
- **Least privilege that's tested both ways.** A permission test that only checks "denied" can pass with a broken system; the end-to-end run proves the grants are also sufficient.

## Decisions & trade-offs

- **The reaper reclaims through the queue** (`XAUTOCLAIM`), not by executing runs directly, so reclaimed runs respect `--concurrency`. That's a deliberate deviation from R2.4's wording, with the same outcome.
- **Ack also deletes the message** (`XDEL`). The stream then contains only unfinished work, stays small, and "message exists" means "not done", which the relay relies on.
- **A worker acks a duplicate only if Redis says it still holds it.** I found this while designing the zombie scenario: otherwise a woken zombie could ack the message its successor reclaimed. Not a correctness bug (the relay would recover), but it would slow recovery.
- **Unexecutable runs fail instead of looping.** A run whose graph no longer exists or whose input no longer validates becomes `failed`, rather than being retried forever by the reaper (a poison run).
- **Workers are local processes in this phase,** with containers in phase 12.1. The supervisor doesn't restart children on purpose.
- **Explicit grants over default privileges,** including for LangGraph's tables: every privilege is visible in a migration or in `runtime db upgrade`.

## Known issues & follow-ups

- **CI only runs on PRs and `main`.** A pushed branch without a PR gets no CI. That's how I noticed a Phase 1 test's timing assumption (a 1.5 s lease) didn't hold on GitHub's slower runner. Fixed with an 8 s lease in that test; the runtime itself was correct.
- **Redis has no authentication or ACL users yet** (R14.14 SHOULD; Kubernetes phase).
- **Worker health/readiness HTTP endpoints** (R10.5, port `:8081`) come with the Kubernetes probes in phase 12.
- **The queue-depth `429`** (R2.9) comes in phase 5, as planned.
- **No metrics yet** for queue lag, reclaims, releases or pending messages (phase 9).

## How to try it

```bash
make up                         # Postgres + Redis, migrate, provision per-component DB users
make worker                     # 2 worker processes (WORKERS=… CONCURRENCY=…)
make api API_PORT=8765          # in another terminal
curl -s -X POST localhost:8765/runs -H 'content-type: application/json' \
     -d '{"graph":"toy","input":{"question":"hello","delay_s":1}}'
# the workers pick it up; watch: GET /runs/<id>, /runs/<id>/events
# Ctrl-C the workers: runs in flight are handed off (run.released)

make demo-crash                 # AC2: SIGKILL the owner → PASS/FAIL per check
make demo-zombie                # AC5: SIGSTOP/SIGCONT the owner
make demo-release               # graceful SIGTERM hand-off
make demo-e2e REPEAT=5          # all three, five times
make coverage                   # 167 tests + coverage report
```
