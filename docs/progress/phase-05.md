# Phase 5 — Sub-runs, sub-agents & backpressure

**Plan:** [plans/phase-05.md](../plans/phase-05.md) · **ADR:** [0005](../adr/0005-fan-out-child-runs.md) · Delivered in two PRs: **5a, child runs & backpressure** (this part), and 5b, sub-agents (added below when it merges).

## Part A — Child runs & backpressure

**Completed:** 2026-10-16 · **Branch:** `feat/phase-05a-child-runs` · **Tests:** 294 (267 at the end of phase 4) · **Branch coverage:** 96 % (CI floor 90 %)

### What we built

**Fan-out from a workflow node** ([runs/fanout.py](../../backend/src/agent_runtime/runs/fanout.py)).
- A node calls `await runtime.context.spawner.spawn([ChildSpec(key, graph, input), …])` and gets back a `FanIn`: one `ChildResult` per child, and `partial`.
- This is Ports & Adapters:
  - `RunSpawner` raises an `interrupt({"type": "spawn_children"})`, which the executor carries out.
  - `LocalSpawner` (`runtime run --local-fanout`) runs the same children in-process. Each child gets a fresh context, so it can't leak into the parent's run (measured in the research).

**The fan-out transaction** (`RunRepository.spawn_children`). One fenced transaction:
- checks the limits: `max_children` (6), depth ≤ 2, and ≤ 20 descendants per root (counted on the locked root row)
- inserts the children (`UNIQUE (parent_run_id, child_key)` is defence in depth)
- moves the parent to `waiting_children`, releasing its lease

The children are sent to the queue **after** the commit. A breached limit is a `FanOutRejected` that the node can handle; nothing is created.

**Fan-in** (`RunRepository._child_ended`, called from `transition`).
- A child's terminal transition increments its parent's `child_done` **in the same transaction**. The last one re-queues the parent (`children.completed`).
- `transition` is the one path for every terminal transition (worker, reaper, API cancel), so none of them can skip the fan-in.
- On resume, the executor computes the fan-in from `run_results` and LangGraph re-runs the node, with `interrupt()` returning the results.
- The outcome:
  - Some children failed → `partial = true`. It is computed at completion from the children's statuses, so it survives a reclaim.
  - All failed → `failed(children_failed)`.
- If a worker dies after the node's interrupt is checkpointed but **before** the fan-out commits, the next owner finds the pending interrupt with no children, and fans out then.

**Cancel cascade.** Cancelling a run cancels its live descendants.
- Locks are taken deepest first; cancels are applied shallowest first.
- So a child that ends afterwards can't re-queue its cancelled parent.

**Budget roll-up** ([tools/invocations.py](../../backend/src/agent_runtime/tools/invocations.py)).
- A model or tool call charges the run *and its ancestors* (≤ 3 rows, locked child → parent → root).
- Each ancestor's own limit bounds its whole tree: `budget:* … reached by ancestor <id>`.

**Backpressure** (R2.9).
- `POST /runs` → **`429` + `Retry-After`** (problem `overloaded`) once `QUEUE_DEPTH_LIMIT` runs are queued.
- The depth is counted in Postgres (correct even with Redis down), cached for 1 s per replica, and shown in `/admin/state`.
- Validation runs first, so a bad request still gets `422`.
- Workers' own fan-outs are never refused.

**The `fanout` demo workflow** ([graphs/fanout.py](../../backend/src/agent_runtime/graphs/fanout.py)): plan → research (one `toy` child per sub-question) → synthesize. Its inputs slow children down or make chosen ones fail.

### How it fits

```
 parent node ── spawn([...]) ── interrupt ─► executor: ONE fenced txn
     limits · INSERT children · child_total · running → waiting_children (no lease)
     └── after COMMIT: enqueue children ──► any worker (own lease, epoch, checkpoint, reclaim)
 child ends ── same txn as its terminal transition: parent.child_done += 1
     last one: parent waiting_children → queued ── after COMMIT: enqueue parent
 parent resumes: Command(resume = fan-in from run_results) ─► node continues (partial?)
```

### Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | **AC6: fan-out across workers** | ✅ `make demo-fanout`, **5/5**: 6 children ran on **2 different worker processes**; the parent got all 6 results; fanned in once |
| SC2 | The parent waits without a lease | ✅ `waiting_children` with no owner and no lease; children handed to the queue only after commit |
| SC3 | Atomic fan-in | ✅ **50 rounds × 6 siblings ending concurrently:** `child_done = 6`, the parent re-queued **exactly once**, one `children.completed` each round |
| SC4 | Partial results | ✅ 1 of 3 failed → `partial = true` (also in `run_results`); all failed → `failed(children_failed)` |
| SC5 | A crashed child doesn't break the fan-in | ✅ e2e, SIGKILL, **5/5**: the child was reclaimed once and finished on another worker; the parent fanned in once (`4/4`) |
| SC6 | Fan-out limits | ✅ `max_children`, depth and descendants (including grandchildren counted against the root): the node sees the reason; nothing is created; the run continues. A stale owner can't fan out (fenced) |
| SC7 | Idempotent spawn | ✅ Worker A dies after the interrupt's checkpoint but before the fan-out commit → no children; worker B fans out each child exactly once. Invalid children and reused keys → rejected |
| SC8 | Cancel cascade | ✅ Queued children cancelled, a running child flagged; when it ends afterwards, the cancelled parent is untouched (`child_done` stays 0) |
| SC9 | Budget roll-up | ✅ Two children's model and tool calls add up on the root; the root's limit stops the next child call (`reached by ancestor`) |
| SC10 | Backpressure | ✅ `429`, `Retry-After`, problem `overloaded` with depth and limit; `422` still first for invalid input; per-replica cache; fan-outs not refused; depth in `/admin/state` |
| SC11 | Local fan-out | ✅ The same graph completes with no worker and no child rows; the children's nodes don't leak into the parent's events |
| — | Quality | ✅ 294 tests; coverage 96 %; **50/50 e2e runs** (10 scenarios × 5) |

### Concepts learned

- **A durable pause is a general tool.** Waiting for children is the same protocol as waiting for a human: interrupt, a waiting state, no lease, `Command(resume)`. Only the resume value differs.
- **Count in the transaction that ends the work.** An atomic counter, updated in the same transaction as the child's terminal state, gives exactly-once fan-in without a coordinator.
- **One choke point beats N call sites.** Fan-in lives where *every* terminal transition already passes.
- **Ordered locking prevents deadlocks.** Agree on one order (deepest first) and every multi-row transaction follows it. The cascade cancel shows a subtlety: the order you *lock* in and the order you *apply* in can differ.
- **Backpressure belongs at admission,** not on internal work. Refusing children of a running parent would turn overload into deadlock.

### Decisions & trade-offs

- **The node that spawns receives the fan-in.** R2.8 says a "fan-in node reads results from `run_results`". Here the spawning node is re-run and gets the results as `interrupt()`'s return value, read from `run_results` at resume. It's equivalent, and a workflow can't forget to read them.
- **Queue depth from Postgres, not Redis.** It's the source of truth, and it's correct even with a duplicated message or Redis down. It costs one indexed `COUNT` per replica per second.
- **Tokens and cost are not rolled up yet.** Nothing records them before real models arrive (phase 6); model and tool calls are.
- **`/metrics` (Prometheus) waits for phase 9.** The queue depth is in `/admin/state` until then.

### Bugs found by testing (all fixed before merge)

- **A rejected fan-out would have lost the step's staged events.** The transaction that rolled back had already taken them from the outbox. They are now restored on rejection.
- **A later fan-out reusing an earlier one's keys would have silently received the old results.** It now has to match the stored fan-out, or it is rejected.
- **A test that waited for an event that can't exist yet.** `node.started` for the spawning node is committed with the *next* checkpoint, which the test was deliberately blocking. The test now waits for the blocked call itself.
