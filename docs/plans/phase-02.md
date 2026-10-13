# Phase 2 plan — Distributed workers

**Goal:** many worker processes share the work safely. A run created by the API is picked up automatically, a crashed worker's run is reclaimed **automatically**, a worker asked to stop hands its runs off in seconds, and a "zombie" worker can't corrupt anything.

**Done when:** AC2 (crash-and-resume) and AC5 (zombie safety) pass as scripted demos (`make demo-crash`, `make demo-zombie`) that print PASS/FAIL, plus the integration tests below.

**Requirements:** R2.1 work queue · R2.2 worker pool · R2.4 reaper/reclaim · F2 reclaim race · R1.3 resume endpoint · R1.6 cancellation · R10.7 graceful shutdown (runtime part) · R14.13 least-privilege DB roles · R14.18 kill switch · fencing enforced by the database (R2.3 "the database rejects writes").
*Already done in phase 1:* lease acquisition, heartbeat, fencing in code, reclaim counting.

---

## 1. Research findings

| Topic | Finding | Source / evidence |
|---|---|---|
| Consumer groups | A message read with `XREADGROUP` stays in the group's **pending entries list (PEL)** until `XACK`. That is what makes delivery at-least-once: a crashed worker's message stays pending. | [Redis XREADGROUP](https://upstash.com/docs/redis/commands/streams/xreadgroup.md) |
| `XAUTOCLAIM` | Transfers pending messages idle longer than `min-idle-time` to the caller. Since Redis 7.0, entries deleted from the stream are removed from the PEL and returned in a third "deleted" list. | [redis.io XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/) + local experiment |
| **Trap: idle ≠ dead** | A message's idle time counts from its **last delivery**, not from the worker's last sign of life. A healthy run that executes longer than the lease TTL has an "idle" message, and a reclaim sweep would steal it every 5 s. | Reasoning, confirmed by experiment |
| **Fix: touch on heartbeat** | `XCLAIM <stream> <group> <me> 0 <id> JUSTID` re-claims your own message and resets its idle time to ~0 (measured: 1400 ms → 79 ms). The sweep then only takes truly dead workers' messages. | Local experiment on Redis 7.4 |
| redis-py | 8.1.0 is within our cooldown. It has asyncio `xreadgroup`, `xautoclaim(min_idle_time, start_id, count, justid)`, `xclaim(..., justid)`, `xack`, `xgroup_create(mkstream=True)`, `xgroup_delconsumer`. Newer features (`XREADGROUP … CLAIM`, idempotent `XADD`) need Redis 8; we run 7.4, so we don't use them. | Inspected the installed package |
| Postgres roles | One role owns the schema and runs migrations. Runtime roles get only DML. `ALTER DEFAULT PRIVILEGES FOR ROLE <owner>` covers tables created later (e.g. LangGraph's), but it **must name the owner role explicitly** or it silently doesn't apply. Revoke defaults granted to `PUBLIC`. | [Cybertec](https://cybertec-postgresql.com/en/postgresql-alter-default-privileges-permissions-explained), [Red Gate](https://red-gate.com/simple-talk/databases/postgresql/postgresql-basics-a-template-for-managing-database-privileges/), [pgsql mailing list](https://www.postgresql.org/message-id/CAPCETpvmBLfaUxWiAi6w1HRtijO%3D%2B6DtmbuE-yyY_7O%3DyuHrrg%40mail.gmail.com) |
| Graceful shutdown | Register `loop.add_signal_handler(SIGTERM/SIGINT)`. On the signal, stop taking new work and track in-flight work. Work that can't finish within the grace period must be handed off, not lost. Kubernetes sends SIGKILL after `terminationGracePeriodSeconds`. | [Kubernetes graceful shutdown](https://jorijn.com/en/knowledge-base/kubernetes/troubleshooting/kubernetes-graceful-shutdown-sigterm-pod-termination/), [NVIDIA Dynamo](https://docs.nvidia.com/dynamo/dev/user-guides/fault-tolerance/graceful-shutdown.md) |

## 2. Design

```
 API: POST /runs ── INSERT run (queued, enqueued_at) ─► XADD runs:work {run_id}
                          ▲                                  │
                          │ relay sweep: queued runs not      │ XREADGROUP (COUNT = free slots)
                          │ re-sent recently → XADD again     ▼
 Postgres (truth) ◄──── worker process (asyncio, C slots) ─── per run: RunExecutor (phase 1)
   lease, epoch,             │  heartbeat: renew DB lease + XCLAIM-touch own message
   events, checkpoints       │  reaper (every 5 s): XAUTOCLAIM idle > TTL → try lease → run it or ack-as-stale
                             │  SIGTERM: stop reading → finish current step → release → re-enqueue → ack → exit
                             └─ ack only on: terminal · waiting_* · released (R2.1)
```

**Key decisions**

1. **Postgres decides, Redis delivers.** A message is only a hint: "run X may need work". The lease `UPDATE` (R2.3) is the single arbiter of who runs X. That resolves the reclaim race (F2) *by construction*: duplicates, stale messages and two recovery paths are all safe, because at most one acquirer wins and losers just look at the run's state.
2. **Every message has one fate.** After trying the lease:
   - **won:** execute, then `XACK`.
   - **lost to a live owner:** leave it pending; the owner acks.
   - **run already terminal or waiting:** `XACK` as stale.
3. **The reaper executes through the queue, not around it.** It claims dead workers' messages with `XAUTOCLAIM` (`COUNT` = free slots), so reclaimed runs respect `--concurrency`. A second, slower sweep re-sends `queued` runs whose message may be lost (Redis flushed, API crashed between `INSERT` and `XADD`). That's the **outbox relay** pattern, and it's what makes "Redis holds nothing that can't be rebuilt" true. Deviation from R2.4's wording ("the reaper resumes the run") is deliberate: the effect is the same, but nothing bypasses backpressure.
4. **The heartbeat renews two things:** the Postgres lease (ownership) and the Redis message idle time (so it isn't claimed).
5. **Graceful release:** a SIGTERM sets a flag. The executor's node Observer (phase 1) checks it before starting the next node: the current superstep finishes and checkpoints, then the run is released in one fenced transaction (`running → queued`, owner cleared, `releases + 1`, `run.released`). It's re-enqueued, and the old message is acked. A release doesn't count toward `max_reclaims` (R2.4).
6. **Cancellation** (R1.6): `POST /runs/{id}/cancel` sets `cancel_requested`. A `queued` run is cancelled immediately. A running run is cancelled by its worker before the next node (the same Observer hook), then fenced, and the lease is released.
7. **The database enforces fencing too** (defence in depth). A trigger on every table with an `epoch` column rejects writes whose epoch is below the run's current epoch. The app-level check stays (it gives clearer errors). The trigger makes it impossible for future code to forget it.
8. **Least-privilege DB roles** (R14.13): migrations create `NOLOGIN` *group* roles (`app_api`, `app_worker`, `app_ingest`, `app_sandboxd`) and their grants, including `ALTER DEFAULT PRIVILEGES FOR ROLE <migrator>`. **Login users and their passwords are created by infrastructure, never by migrations** (secrets don't belong in migration files): a Compose init script now, a Kubernetes Job in phase 12. Each component connects with its own credentials (ADR-0002).
9. **Kill switch** (R14.18): `admin_state.paused` in Postgres. Workers check it before claiming; `POST /runs` returns `503` with `Retry-After`; `/admin/*` endpoints are internal-only (not routed by the Ingress in phase 12).
10. **Workers run as local processes in phase 2.** `runtime worker --concurrency C` is one process; `--workers N` starts a small supervisor that runs N of them. Containers come in phase 12.1 as planned: the distributed-systems logic doesn't depend on them, and processes keep the inner loop fast (kill a PID instead of a container).

**Patterns:** Competing Consumers (consumer group) · Outbox relay (re-send from Postgres) · Lease + fencing token · Bulkhead (`--concurrency` semaphore) · Supervisor (`--workers N`) · Ports & Adapters (`WorkQueue` interface + Redis Streams adapter + in-memory fake for unit tests).

## 3. Tasks

| # | Task | Requirements | Tests (written with the task) |
|---|---|---|---|
| 2.1 | **Work queue port + Redis Streams adapter**: `WorkQueue` interface; `RedisWorkQueue` (ensure group, enqueue, read, ack, touch, autoclaim, pending/lag, delete consumer); in-memory fake; Redis in CI; test isolation (dedicated DB index, flushed per session) | R2.1 | Adapter contract tests run against **both** the fake and real Redis |
| 2.2 | **Enqueue on create + outbox relay**: migration `0003` (`runs.enqueued_at`); `POST /runs` → `XADD`; relay sweep re-sends stale `queued` runs | R2.1, "Redis rebuildable" | Run created while Redis is down still executes after Redis returns; flush Redis → runs still complete |
| 2.3 | **Worker process**: read loop with `C` slots (bulkhead), one task per message, ack rules, heartbeat touches the message; `runtime worker --concurrency C --workers N`; consumer name `{hostname}:{pid}` / `WORKER_ID` | R2.2 | 2 workers × 10 runs: all complete, each exactly once; concurrency never exceeds C |
| 2.4 | **Reaper**: `XAUTOCLAIM` sweep (idle > TTL, `COUNT` = free slots) → lease arbitration → run or ack-as-stale; deleted-entry handling; dead-consumer cleanup; `max_reclaims` | R2.4, F2 | Race reaper vs relay vs owner on one run: exactly one executes; a healthy long run is never stolen |
| 2.5 | **Graceful shutdown & release**: SIGTERM/SIGINT → stop reading → release after the current superstep → `run.released` → re-enqueue → ack → exit; second signal = immediate exit | R10.7 (runtime), R2.4 | SIGTERM mid-run: another worker resumes **within seconds** (vs ≥ TTL for SIGKILL); `releases + 1`, `reclaims` unchanged |
| 2.6 | **Cancel + resume API**: `POST /runs/{id}/cancel` (queued → cancelled now; running → at the next node); `POST /runs/{id}/resume` (idempotent, `409` if terminal) | R1.6, R1.3, §5 | Cancel queued, cancel mid-run, cancel a terminal run (409), resume twice |
| 2.7 | **Fencing in the database**: migration with a fencing trigger on `run_events`, `run_results`, `tool_invocations`, `findings`, `session_messages`, `subagent_invocations` | R2.3 | A stale-epoch `INSERT` written *directly in SQL*, bypassing the app, is rejected |
| 2.8 | **Least-privilege DB roles**: group roles + grants + default privileges (migration); Compose init script creating login users from `.env`; per-component credentials | R14.13 | As `app_worker`: `DROP TABLE`/`DELETE FROM runs` fail; as `app_api`: can't touch checkpoints; LangGraph tables granted via default privileges |
| 2.9 | **Kill switch**: `/admin/pause`, `/admin/resume`, `/admin/cancel-all`; workers stop claiming; `POST /runs` `503` + `Retry-After` | R14.18 | Pause → no claims, in-flight runs finish; cancel-all; survives an API restart |
| 2.10 | **Demos**: `make demo-crash` (AC2: SIGKILL the owning worker, the run completes on the other one, one `run.reclaimed`, epoch +1, no re-executed step) and `make demo-zombie` (AC5: SIGSTOP past the TTL → reclaim → SIGCONT → its writes are rejected; the run completes once). Both print PASS/FAIL | AC2, AC5 | The demos *are* tests; CI runs them |
| 2.11 | Phase summary, design doc, PR | — | Coverage stays ≥ 90 % |

**Order:** 2.1 → 2.2 → 2.3 → 2.4 → 2.5 are the core, in dependency order. 2.6–2.9 are independent of each other. 2.10 needs 2.3–2.5.

**Estimate:** ~18–24 focused hours. That's more than the roadmap's 10–14, because CR-003 added the DB roles and kill switch and the database-level fencing is new.

## 4. Risks

| Risk | Mitigation |
|---|---|
| Timing-based tests (crash, release, reclaim) are flaky | Deadline-bounded polling helpers (phase 1); short TTLs in tests; each new demo repeated in a loop before merging |
| Two recovery paths (reaper + relay) produce duplicate messages | Safe by design (decision 1); a test sends duplicates on purpose |
| Graceful release takes longer than the grace period (a slow step) | The SIGKILL path (reclaim) still recovers it; documented, and measured in phase 12 (AC16) |
| DB roles break local development | `make up` creates the users automatically from `.env`; the migrator role is still used for migrations only |
