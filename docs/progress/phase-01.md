# Phase 1 — Durable single run

**Completed:** 2026-10-12 · **Branch:** `feat/phase-01-durable-run` · **Tag:** `phase-01` (after merge) · **Tests:** 108 (16 at the end of phase 0)

## What we built

**Epoch-fenced checkpointer** ([checkpointing.py](../../backend/src/agent_runtime/checkpointing.py), [fencing.py](../../backend/src/agent_runtime/fencing.py)). This is the heart of the phase, and it started as a spike. LangGraph saves a checkpoint after every step, but it doesn't know who owns the run. `FencedCheckpointer` wraps LangGraph's own Postgres checkpointer as a **Protection Proxy**. Every write runs inside our transaction, which first takes `SELECT epoch … FOR SHARE` on the run and refuses the write if the epoch has moved on. A "zombie" worker whose run was taken over can't persist anything. It only uses LangGraph's public API, so an upgrade can't silently bypass it.

**Run state machine** ([runs/state.py](../../backend/src/agent_runtime/runs/state.py)). The legal transitions from R1.1 as a table: waiting states always go back through `queued`, any non-terminal state can fail or be cancelled, and terminal states are final. Every failure reason the spec names is an enum value. UUIDv7 ids ([ids.py](../../backend/src/agent_runtime/ids.py)) sort by creation time.

**Run repository** ([runs/store.py](../../backend/src/agent_runtime/runs/store.py)). The only code that knows the SQL for runs:
- creating a run and its `run.created` event in one transaction
- fenced status transitions, where the losing side of a race is told the real status
- gap-free per-run event `seq`
- lease acquisition, using the exact R2.3 SQL (a lease that expires on a `running` run is a counted reclaim)
- heartbeat renewal, the step counter, and the run result

**Executor** ([runs/executor.py](../../backend/src/agent_runtime/runs/executor.py)). It runs a graph durably:
1. Acquire the lease.
2. Start the run, or record a reclaim.
3. Run the graph with `durability="sync"` while a heartbeat renews the lease.
4. Finish as `completed` or `failed`, with a reason, in one fenced transaction that also releases the lease.

Node events are **staged during a step and committed inside that step's checkpoint transaction**, so they are exactly-once per committed step. It enforces `max_steps` (it refuses to start the next node once the budget is spent) and the wall-clock timeout (measured from the first start, across resumes). If the heartbeat fails, the execution stops.

**Limits** ([runs/limits.py](../../backend/src/agent_runtime/runs/limits.py)). Options may only *tighten* the server ceilings; a value above a ceiling is a `422` naming the field and the maximum. Limits are resolved once and stored on the run.

**Agent definitions** ([agents/](../../backend/src/agent_runtime/agents/), [backend/agents/](../../backend/agents/)). `agents/<main>/agent.md`, with sub-agents as leaf sub-folders. The schema is strict: a typo in a key is an error. The loader reports **every** problem at once:
- folder/name mismatch
- unknown tool, hook, schema or model
- limits above the ceilings
- nesting below a sub-agent
- approval-gated tools in a sub-agent
- placeholders not on the allow-list
- an empty prompt
- unsafe YAML (rejected)

Definitions are snapshotted by content hash. `runtime agents validate` runs in CI and needs no secrets.

**Graph registry + `toy` graph** ([graphs/](../../backend/src/agent_runtime/graphs/)). A deterministic plan → research → answer graph. Its input can slow it down (`delay_s`) or make a chosen node fail (`fail_at`), which is what the crash, timeout and failure tests use.

**API** ([api/](../../backend/src/agent_runtime/api/)):
- `POST /runs` returns `202` with a `Location` header
- `GET /runs/{id}`, `/events` (paged by `after_seq`), `/result` (404 until completed)
- `GET /graphs[/{name}]` for introspection
- `/healthz` (no dependencies, so a database blip never restarts pods) and `/readyz`

Errors are RFC 9457 problem details, and the OpenAPI contract is published at `/openapi.json`.

**CLI** ([cli.py](../../backend/src/agent_runtime/cli.py)):
- `runtime db upgrade`: our Alembic schema plus LangGraph's own tables, in one migrate step
- `runtime api`: binds to 127.0.0.1 by default
- `runtime run`: create a run and execute it
- `runtime execute` / `resume`
- `runtime agents validate` / `show`

**Schema** ([migration 0002](../../backend/migrations/versions/0002_agents_budgets_subagents.py)). Agent snapshots, durable usage counters, resolved limits, the kill-switch row and sub-agent invocations. Everything is additive, so old code keeps working during a rolling upgrade.

## How it fits

```
 runtime run / execute / resume        POST /runs ──► RunService ──► runs (queued) + run.created
            │                                          (validate graph, input, options ≤ ceilings)
            ▼
       RunExecutor ── acquire_lease (epoch+1, R2.3) ──► run.started | run.reclaimed
            │
            ├── heartbeat every heartbeat_s ── renew fails? → stop (another worker owns it)
            │
            └── graph.ainvoke(durability="sync") ──► per superstep, ONE transaction:
                     _NodeRecorder (Observer)            SELECT epoch … FOR SHARE   ← fence
                       stages node.started/completed    LangGraph checkpoint rows
                       refuses node if steps spent      staged node events + steps+1  ← outbox
                                        │
                     completed (result) | failed(reason): fenced, lease released
```

## Requirements covered

| Req | Status |
|---|---|
| R1.1 Run identity & lifecycle | ✅ UUIDv7, state machine, transitions + event in one transaction |
| R1.2 Checkpointing | ✅ Postgres checkpointer, `thread_id` per run (session threads in phase 6), one checkpoint per superstep, `durability="sync"` |
| R1.3 Resume | ✅ For crashed workers: idempotent while another live owner holds the run; terminal runs are rejected (exit 2). Approval resume comes in phase 4; graceful-release resume in phase 2 |
| R1.5 Event stream (persisted part) | ✅ Typed events, gap-free `seq`, replay via `after_seq`. Pub/sub and SSE come in phase 3 |
| R1.7 Run limits | ✅ Wall-clock and steps, configurable per run, `failed(timeout | step_limit)` |
| R2.3 Leases with fencing | ✅ Pulled in from phase 2: the exact acquire SQL, heartbeat, fencing on checkpoints, transitions and events |
| R2.10 / F1 Epoch-fenced checkpointer | ✅ Spike → production code, with a control test proving the bug it prevents |
| R2.4 Reclaim (counting, `max_reclaims`) | 🟡 Partial: reclaim is counted and capped. The automatic reaper loop comes in phase 2 |
| R14.3 Ceilings that options can only tighten | ✅ For timeout and steps. Model/tool/token/cost budgets come in phase 4 |
| R14.20 Scripted test model | ⏭ Moved to phase 4, where the first model call happens |
| R15.1–R15.4, R16.1, R16.2 Agent definitions | ✅ Loader, strict schema, validation, snapshots, `agents validate` in CI. Executing agents comes in phase 6 |
| §5 API (part) | ✅ `POST /runs`, `GET /runs/{id}`, `/events`, `/result`, `/graphs`, `/healthz`, `/readyz` |
| AC38 Leaf & layout validation | ✅ |
| Phase "done when" | ✅ `test_crash_resume.py`: a real process is SIGKILLed mid-run, then resumed by another process. The committed step isn't re-run, there's exactly one reclaim, and no events leak from the interrupted step. Stable across 5 repeated runs |

## Concepts learned

- **Supersteps and checkpoints.** LangGraph runs a graph in supersteps and saves a checkpoint after each one. Resume means "load the latest checkpoint for this thread and continue". Nodes that already committed are never re-executed.
- **Fencing tokens.** A lease alone isn't enough, because a frozen process can wake up still *believing* it owns the run. The epoch turns "who owns it" into something the database can check on every write. `FOR SHARE` makes the check and the write atomic with respect to a takeover.
- **Durability modes matter.** `async` durability (LangGraph's default) overlaps writing a checkpoint with running the next step. Our experiment showed a zombie then executes an extra step before learning it's fenced. `sync` closes that window.
- **Fencing bounds what a zombie can *persist*, not what it can *do*.** The interrupted node ran twice. Side effects therefore need idempotency keys as well (phase 4).
- **Transactional Outbox.** Write the events in the same transaction as the state change they describe, and the log can't disagree with reality.
- **Optimistic concurrency.** `UPDATE … WHERE status = ANY(legal sources)`: when two processes race, exactly one wins, without holding a lock across the race.
- **Gap-free sequences.** A row-locked counter, not a Postgres `SEQUENCE` (which leaves gaps on rollback). Replay and deduplication depend on it.
- **Liveness vs readiness.** `/healthz` never checks dependencies; `/readyz` does.

## Decisions & trade-offs

- **Pulled the lease and heartbeat in from phase 2.** "Resume after a crash" isn't correct without them: something must decide when the dead owner's claim is over. Phase 2 keeps the queue, the reaper and graceful shutdown.
- **Moved `ScriptedModelProvider` and the token/cost budgets to phase 4.** Nothing calls a model before phase 4, so building them now would have meant code with no real consumer. LangChain also ships fake chat models we can build on there.
- **Events are written at commit time, not when they happen.** That makes them exactly-once per committed step, but the persisted `node.started` appears together with its `node.completed`. Live "a node just started" notifications are a streaming concern (phase 3, pub/sub, not persisted).
- **`max_steps` is enforced by our callback, not LangGraph's `recursion_limit`.** The recursion limit resets on every resume, so on its own it can't enforce a per-run budget across crashes. It stays as a backstop (`max_steps + 5`).
- **LangGraph manages its own tables.** `runtime db upgrade` runs Alembic, then LangGraph's `setup()`. One command, which the Kubernetes migrate Job will run.
- **`AgentSettings` split from `Settings`** (interface segregation), so validating Markdown files needs no database password.
- **Supply-chain cooldown.** `uv` refuses package versions uploaded after a fixed date (~2 weeks back), which is bumped deliberately.

## Known issues & follow-ups

- **Nothing executes API-created runs automatically yet.** `POST /runs` creates a `queued` run, and `runtime execute <id>` runs it. Workers that pull from a queue arrive in phase 2.
- **Reclaim is manual:** you run `resume` after the lease expires. Phase 2 adds the reaper loop that does it automatically every 5 s.
- **Fencing covers checkpoints, transitions and run events.** Tool results, findings and transcripts get fenced as they're built (phases 4–6).
- **There's no cancel endpoint yet** (R1.6, phase 2).
- **Logs are plain text.** Structured JSON logs come in phase 9.
- **Port 8000 is taken by another project on this machine,** so use `make api API_PORT=8765`.

## How to try it

```bash
make up && make migrate                    # services + our schema + LangGraph's tables
make run-toy                               # create and execute a run; prints the event log
make agents-validate                       # validate backend/agents

make api API_PORT=8765                     # then open http://127.0.0.1:8765/docs
curl -s -X POST localhost:8765/runs -H 'content-type: application/json' \
     -d '{"graph":"toy","input":{"question":"hi","delay_s":2}}'
cd backend && uv run --env-file ../.env runtime execute <run_id>   # Ctrl-C it mid-run…
# …wait ~30 s for the lease to expire, then:
uv run --env-file ../.env runtime resume <run_id>                  # finishes; see run.reclaimed

make check                                 # 108 tests, lint, mypy --strict, agent validation
```
