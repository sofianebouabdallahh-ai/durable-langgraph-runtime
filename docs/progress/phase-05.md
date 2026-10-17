# Phase 5 — Sub-runs, sub-agents & backpressure

**Plan:** [plans/phase-05.md](../plans/phase-05.md) · **ADR:** [0005](../adr/0005-fan-out-child-runs.md) · Delivered in two PRs: **5a, child runs & backpressure**, and **5b, sub-agents**.

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

## Part B — Sub-agents

**Completed:** 2026-10-16 · **Branch:** `feat/phase-05b-subagents` · **Tests:** 309 (294 after 5a) · **Branch coverage:** 95 % (CI floor 90 %)

### What we built

**The orchestrator** ([subagents/orchestrator.py](../../backend/src/agent_runtime/subagents/orchestrator.py)). An in-process Supervisor, one per run execution of an agent that has sub-agents.
- **Running:** each sub-agent is an asyncio task in the main run's worker, started in a **fresh contextvars context** (the measured isolation fix).
- **Persistence:** each one is a `create_agent` graph with **its own checkpoint thread** (`<run>/sub/<handle>`). Its checkpoints go through a `FencedCheckpointer` using the **main run's fence**, so one lease covers everything.
- **Events:** each has its own outbox that writes into the run's event log but doesn't count toward the run's `max_steps`.
- **Limits:** 4 in parallel (a semaphore), 10 per run, and a timeout each, counted from when it was spawned, so a recovered sub-agent keeps its original deadline. All are configurable downwards only.
- **Lifecycle:**
  - `stop()` cancels the tasks and leaves their rows `running`.
  - `recover()` resumes every running row from its checkpoint.
  - A pause, a graceful release and a crash all take this one path.

**Persistence** ([subagents/store.py](../../backend/src/agent_runtime/subagents/store.py)). This uses the `subagent_invocations` table from migration 0002; migration `0008` adds a durable cooperative-cancel flag.
- The handle is **derived from the spawn call's idempotency key**, so a replayed spawn returns the same handle (`UNIQUE spawned_by_tool_call_id`).
- Every write is fenced, both in code and by the database trigger. It stamps the current epoch, because the trigger rejects an update that keeps an older one (a sub-agent spawned before a reclaim).
- `subagent.spawned / progress / completed` commit with the state they describe, exactly once per handle.

**Tools** ([subagents/tools.py](../../backend/src/agent_runtime/subagents/tools.py)), granted by the harness and run through the full tool pipeline:

| Tool | For | Behavior |
|---|---|---|
| `spawn_subagent` | main agent | Returns a handle at once (non-blocking) |
| `subagent_status` | main agent | Live status, latest progress message, usage |
| `wait_subagents` | main agent | Blocks up to 120 s; the tool spec carries its own timeout |
| `cancel_subagent` | main agent | Cooperative: checked before every model call and tool call |
| `report_progress` | sub-agent | At most 1 update per 2 s and 50 in total; extra updates are dropped with a note |
| `return_result` | sub-agent | Stores the result; the next model call then short-circuits to a final answer, ending the loop |

**Isolation & least privilege** (R16.6, R16.7).
- **Context:** a sub-agent's conversation is its own prompt plus one message with the task (and context).
- **Tools:** its grants are its own tools only.
- **Approvals:** the pipeline's `approvals=False` turns `RequireApproval` or a hook's `ask` into `Deny(approval_unavailable)`. A sub-agent never pauses the run.

**Budgets** (R16.8).
- **Roll-up:** every model call is charged to the sub-agent's `max_turns` **and** to the run's budget, in one fenced transaction. Every tool call is charged to the sub-agent's own tool limits (the ledger's `extra_charge`) **and** the run's.
- **Soft limit:** at 80 % of the run's model or tool budget, a wrap-up note is added to the sub-agents' next requests.
- **Hard limit:** when one sub-agent hits the run's limit, it ends `failed` (`partial` if it had reported progress) and the others are cancelled.

**Turn guard** (R16.9). If the main agent answers while sub-agents still run, the middleware waits for them (bounded by the run's deadline), then makes **one more model call** that includes their results.

**Executor wiring.**
- **Before the run starts:** sub-agents are recovered.
- **Before the run leaves `running`:** they are stopped (pause, release) or cancelled (complete, fail, cancel). This rule exists because the fence compares epochs only, and a pause doesn't change the epoch.
- **On any exit:** a `finally` stops them, including when the executor task itself is cancelled.

**API.** `GET /runs/{id}` lists the run's sub-agents: agent, status, progress, usage and result.

### How it fits

```
 worker ── RunExecutor(main run, lease epoch e) ─────────────────────────────────────
   recover(): every `running` row → task resumes from <run>/sub/<handle>
   main graph ── spawn_subagent ── ledger (key) ── row (handle = f(key)) ── task ─┐
            ├── wait_subagents ≤ 120 s ◄── results ─────────────────────────────┐  │
            └── final answer while running? → wait → one more model call       │  │
   sub-agent task (fresh context, semaphore 4) ── create_agent ── own tools ────┘◄─┘
            each model call: cancel? → charge (own max_turns + the run's) → wrap-up?
            checkpoints: FencedCheckpointer(fence = e) · events → the run's log
   leaving `running`: pause/release → stop()  ·  complete/fail/cancel → cancel_all()
```

### Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC12 | Parallel in the same worker | ✅ Two sub-agents overlapped (`max_running_seen = 2`) in the main run's process; unknown sub-agent and over-limit spawns → tool errors the model sees |
| SC13 | Isolation & privilege (AC39 without sandboxes) | ✅ The sub-agent's first model request is exactly `[system prompt, task + context]`; a main-agent tool it lacks → `Deny(not_granted)`, audited with its handle; a hook's `ask` → `Deny(approval_unavailable)`, and the run never pauses |
| SC14 | **AC40: status, return, cancel, timeout** | ✅ `subagent_status` shows the progress message and percent; `return_result(status=partial)` reaches the main agent as partial; `cancel_subagent` stopped the sub-agent before its next step (1 of 2 notes written); past its 2 s timeout → `timed_out`, result `failed: timeout`; the second progress update within 2 s was dropped |
| SC15 | Turn guard (R16.9) | ✅ An early final answer → the runtime waited, then made one more call whose request contained the sub-agent's result; `subagent.completed` comes before `run.completed` |
| SC16 | **AC41: crash resume** | ✅ `make demo-subagents`, **5/5**, SIGKILL with real processes: resumed on another worker; both sub-agents completed; spawned 2 / completed 2 (one result per handle); the finished sub-agent's tool never re-ran; the unfinished one resumed from **its** checkpoint (2 model calls, not 3; its tool call taken over at epoch 2); one note |
| SC17 | **AC42: budget roll-up** | ✅ Usage adds up (main 3 + 3, sub-agents 3 + 3 and 2 + 2 → run 8 model / 8 tool calls). With `max_model_calls = 6`: the 5th and 6th calls carried the wrap-up note; the 7th was refused; the sub-agent ended `failed` / `partial`; the run failed `budget:model_calls` at exactly 6 |
| SC18 | Fenced | ✅ A stale epoch can't report progress, finish or cancel a sub-agent; a repeated spawn with the same key returns the same handle |
| SC19 | Visible | ✅ `GET /runs/{id}` lists sub-agents with status, usage and result; `subagent.*` events are in the run's log (and therefore its stream) |
| SC20 | Quality | ✅ 309 tests; coverage 95 %; **55/55 e2e runs** (11 scenarios × 5, every earlier phase's included); no API key |
| — | Also | ✅ An approval pause stops a running sub-agent, leaving its row `running`; after approval it resumes and completes |

### Concepts learned

- **Concurrency inside one run changes the locking story.** With one writer per run, `FOR SHARE` followed by `UPDATE` was harmless. With parallel tool calls and sub-agents it deadlocks: each transaction holds the share lock the other's upgrade needs. Choose the lock mode you'll end up needing (`FOR NO KEY UPDATE`).
- **contextvars are inherited by tasks.** An `asyncio.create_task` from inside a running graph silently joins the parent's run. Isolation has to be explicit.
- **Make every stop resumable, then there is one recovery path.** A pause, a release and a crash become the same operation: stop the tasks, keep their checkpoints, resume them later.
- **A fence that compares epochs needs a rule for pauses,** which keep the epoch. Here: stop every writer before the run leaves `running`.
- **Idempotent identity from the idempotency key.** Deriving the handle from the spawn call's key makes a replayed spawn find the same sub-agent with no extra bookkeeping.

### Decisions & trade-offs

- **Handles must be scripted somehow.** The scripted model resolves `${tool[i].field}` from earlier tool results in the conversation. It is replay-stable like the rest of the test double, and it keeps `wait_subagents` and `cancel_subagent` taking explicit handles, as the spec says.
- **Per-tool caps in a sub-agent count per sub-agent.** The run-wide caps still apply through the run's counters.
- **`return_result`'s `output_schema` validation waits** until output schemas are registered (none exist yet).
- **No new table.** `subagent_invocations` was designed in phase 0; 5b added only the cancel flag.
- **Not in this phase, as planned:**
  - AC37 (the `chat` agent and its sub-agents) is phase 6.
  - One sandbox per sub-agent is phase 7.
  - Sub-agent spans and metrics are phase 9.
  - The main agent's own soft-limit wrap-up turn is phase 6.

### Bugs found by testing (all fixed before merge)

- **A deadlock latent since phase 4,** found by the first real sub-agent run: two tool calls in one turn run concurrently, and each ledger transaction upgraded a `FOR SHARE` lock on the run row. Fixed in `check_fence` (`FOR NO KEY UPDATE`). There's a regression test that **fails with the old lock** (verified).
- **The first progress update always failed:** the rate limit subtracted `-infinity` from `now()`, which Postgres rejects. Found by the first smoke run.
- **A sub-agent's usage update would have been fenced after a reclaim:** the database trigger rejects an update that keeps an older epoch. Every write now stamps the current epoch.
- **Two tests that didn't prove what they claimed.** The budget test accepted any "budget" reason, and its script used a tool the sub-agent doesn't have (so those calls were denied, not charged). The crash test didn't distinguish "resumed from its checkpoint" from "restarted". Both now assert exact values.

### Known issues & follow-ups

- **Event-log contention:** sub-agents append to the main run's log, serialised on its row. That's fine at 4 in parallel; measure it with real models in phase 6.
- **Bidirectional messaging** (a sub-agent asking its main agent a question) remains on the roadmap (CR-005 §6).
