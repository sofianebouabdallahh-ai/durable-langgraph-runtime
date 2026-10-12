# Design

How the runtime is built and why. Requirements (*what*) live in the [spec](requirements/Project_4_Detailed_Requirements_K8s.pdf) and [change requests](requirements/). Individual decisions are recorded as [ADRs](adr/). This document is the map that connects them, and it grows phase by phase.

## Pattern catalogue

Every non-trivial component names the pattern it applies. If no pattern fits, the code says so instead of forcing one.

| Pattern | Where | Why here |
|---|---|---|
| **State machine (table-driven)** | [`runs/state.py`](../backend/src/agent_runtime/runs/state.py) | Run lifecycle rules (R1.1) as data: one place answers "is this transition legal?" for the API, workers and reaper, and the whole table is unit-tested. Waiting states return through `queued`, so every resume takes a fresh lease. |
| **Repository** | [`runs/store.py`](../backend/src/agent_runtime/runs/store.py) `RunRepository` | Only this class knows the SQL for runs and events. Callers use domain operations and get immutable `Run` / `Event` objects back, never raw rows. |
| **Unit of Work** | Call sites: `async with conn.transaction()` | The repository is bound to a connection and doesn't decide transaction boundaries beyond a single atomic operation. Callers group operations that must succeed or fail together; nested calls become savepoints. The executor uses this to commit a status change, its events and the checkpoint as one unit. |
| **Optimistic concurrency (conditional update)** | `RunRepository.transition` | `UPDATE … WHERE status = ANY(legal sources)`. When two processes race, exactly one row update succeeds; the loser gets `InvalidTransition` with the real current status. No lock is held across the race. |
| **Transactional event log** | `RunRepository.append_event` | A status change and its event commit together (R1.1). Events are persisted *before* any publish (R1.5, phase 3), so the log is the source of truth and pub/sub is only a notification. |
| **Gap-free sequence via row lock** | `runs.last_event_seq` | `UPDATE … SET last_event_seq = last_event_seq + 1` serialises writers per run and gives the number back on rollback. That makes `seq` strictly increasing and gap-free, which the replay/dedup algorithm (R2.5) relies on. A Postgres `SEQUENCE` would leave gaps. |
| **Content-addressed snapshot** | `agent_definitions.hash` (migration 0002) | A run references the exact definition it started with, by hash. Identical definitions dedupe, and a changed file never alters an in-flight run (R15.4). |
| **Expand / contract migrations** | `backend/migrations/` | Schema changes are additive first (new columns are nullable or defaulted), so old and new code can run side by side during a rolling upgrade (R10.6, AC15). |
| **Fail-fast configuration** | [`config.py`](../backend/src/agent_runtime/config.py) | Invalid or missing settings stop the process at startup, with the field named, rather than failing later in the middle of a run. |
| **Fencing token** | [`checkpointing.py`](../backend/src/agent_runtime/checkpointing.py) `Fence`, `check_fence` (events, transcript and tool writes join in phase 2) | Every write carries the lease epoch, and the database rejects writes from a stale epoch, so a paused "zombie" worker can't corrupt a run it no longer owns (R2.3, R2.10). |
| **Protection Proxy** | `FencedCheckpointer` | Same interface as LangGraph's `AsyncPostgresSaver`; reads pass through, and every write runs inside our transaction after the fence check. It uses only LangGraph's public API, so an upgrade can't silently bypass the guard. |
| **Idempotency key** | *Phase 4* | Tool calls keyed by `sha256(run · node · call_index · tool · args)`. A retry after reclaim returns the stored result instead of executing again (R2.6). |

## Spike: fencing LangGraph checkpoints (phase 1, task 1.4)

**Question:** can we stop a zombie worker's checkpoint writes without forking LangGraph?

**Approach:** wrap each checkpoint write in our own transaction. `SELECT epoch FROM runs … FOR SHARE` runs first; if the epoch isn't ours, raise `FencedError` and roll back. Otherwise LangGraph writes on that same connection. `FOR SHARE` conflicts with the takeover's `UPDATE … epoch = epoch + 1`, so the check and the write are atomic with respect to a takeover.

**Results** (3-node graph; node `b` triggers a takeover mid-run):

| Scenario | Zombie behaviour | Persisted |
|---|---|---|
| No fence (plain LangGraph) | Executed `b` and `c` and finished | `[a, b, c]`: the zombie's work won |
| Fence, `durability="sync"` | Stopped right after `b` | `[a]`: the new owner resumes from here; `a` is not re-run |
| Fence, `durability="async"` (LangGraph default) | Stopped, but only **after executing `c`** | nothing: even `a` was lost |

**Conclusions**
1. **Fencing works on the public API.** Only `aput`, `aput_writes` and `adelete_thread` write; the other write hooks aren't implemented by the Postgres saver.
2. **`durability="sync"` is mandatory** for every run. With async durability a zombie executes extra steps (extra side effects) before learning it's fenced, and more progress is lost.
3. **Fencing bounds what a zombie can *persist*, not what it can *do*:** `b` executed twice. External side effects therefore also need idempotency keys (R2.6, phase 4).
4. **Cost:** one extra `SELECT … FOR SHARE` per checkpoint write, on the same connection and in the same round trip budget.
5. **Ownership:** LangGraph creates and migrates its own tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) through `setup()`; Alembic manages ours. The migrate step will run both (phase 1, task 1.7).

Tests: [`test_fenced_checkpointer.py`](../backend/tests/integration/test_fenced_checkpointer.py), including a control test proving that the unfenced zombie really does corrupt the run.

## Key design decisions

- **Sub-runs vs LangGraph `Send` for distributed fan-out:** see the spec's design note under R2.8. *(Expanded in phase 5, as R2.8 requires.)*
- **In-process sub-agents vs child runs:** [CR-005 §1](requirements/CR-005-subagents.md).
- **Configuration and secrets:** [ADR-0002](adr/0002-configuration-and-secrets.md).
