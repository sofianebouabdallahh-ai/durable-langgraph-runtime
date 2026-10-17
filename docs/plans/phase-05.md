# Phase 5 plan — Sub-runs, sub-agents & backpressure

**Goal:** an agent's work can fan out in two ways.
- **Child runs** are full runs on *any* worker. They are used for the research workflow's fixed fan-out, with distributed fan-in.
- **Sub-agents** are leaf agents that the main agent spawns at runtime and runs *in its own worker*, with live status, an explicit return, and their own checkpoints, so a crash loses none of their work.

Both obey limits and budgets that roll up to the root, and the API pushes back when the queue is too deep.

**Done when:**
- **AC6:** with 2 workers, child runs execute on more than one worker.
- **AC40:** status, return, cancel and timeout work for sub-agents.
- **AC41:** a SIGKILL while two sub-agents are mid-task → the reclaiming worker resumes the main agent and both sub-agents from their checkpoints. Nothing completed re-runs, nothing is spawned twice, and there is one result per handle.
- **AC42:** budgets roll up.
- **Plus** the success criteria below.

**Requirements:**
- Child runs and backpressure: R2.8 sub-runs · R2.9 backpressure · R14.6 fan-out limits · R14.1 roll-up (CR-003 amendment to R2.8)
- Sub-agents: CR-005 R16.3–R16.9 · R16.10 (the API part)

**Delivered as two PRs on one plan**, because the two halves share no code beyond the executor and are each about a day of work:

| PR | Branch | Content |
|---|---|---|
| **5a** | `feat/phase-05a-child-runs` | Child runs, fan-in, limits, roll-up, cancel cascade, backpressure (tasks 5.1–5.6) |
| **5b** | `feat/phase-05b-subagents` | The sub-agent orchestrator, its tools, persistence and recovery (tasks 5.7–5.13) |

The tag `phase-05` goes on the merge of 5b.

*Not in this phase, as the roadmap says:*
- AC37 (the `chat` agent with `researcher` / `data-analyst`) is phase 6.
- One sandbox per sub-agent (AC39, its sandbox part) is phase 7.
- Sub-agent spans and metrics are phase 9; `/metrics` comes with them, and until then the queue depth is reported by `/admin/state`.
- The main agent's own soft-limit wrap-up turn (R14.2) is phase 6. Here, the soft limit only asks *sub-agents* to wrap up (R16.8).

---

## 1. Research findings

**Measured** in a local experiment on LangGraph 1.2.12 (it becomes a regression test in 5.8):

| Question | Finding | Consequence |
|---|---|---|
| A graph started with `asyncio.create_task` from inside a running node: does it inherit the parent's run? | **Yes.** contextvars are copied into the task, and the **parent's callbacks saw the child's nodes** (`spawn, c1, after, c2`). | Our `_NodeRecorder` would count the sub-agent's nodes against the main run's `max_steps`, stage node events for them, and run cancel checks for them. **Sub-agents must start in a fresh `contextvars.Context()`.** With it, the parent saw only `spawn, after`. |
| Is the child's checkpoint nested under the parent's? | No. With an explicit `thread_id`, checkpoints land in `(run/sub/x, ns="")` either way. | `thread_id = <run_id>/sub/<handle>` (R16.3) works as is. |
| Does the child keep running after the node that started it returns? | Yes. The parent finished while the child was still waiting. | `spawn_subagent` returns a handle immediately (non-blocking, R16.4). |
| A child cancelled mid-node, then resumed from its checkpoint? | Resumes with `next=('c2',)`; only the interrupted node re-runs. | Pause, release and crash all reduce to "stop the tasks, resume them from their checkpoints later". There is one recovery path. |

**From the phase 4 measurements (still true):**
- `interrupt()` + `Command(resume=…)` re-runs the interrupted node, and `interrupt()` returns the resume value.
- So fan-in can be a resume value **computed at resume time from `run_results`**, rather than stored.

**From the code:**
- The schema already has `parent_run_id`, `child_total`, `child_done`, `run_results.partial` and the `waiting_children` state (phase 0).
- The loader already discovers leaf sub-agents and rejects `external_side_effect` tools in them (phase 1).
- `run_max_children=6` and `queue_depth_limit=100` exist as settings, but nothing enforces them yet.
- The workers already settle `waiting_children` as "done" (acked).

**Prior art:**
- `deepagents`' `task` tool and Claude Code sub-agents run sub-agents in-process with a fresh context, as CR-005 does. Neither checkpoints them, which is what we add.
- Temporal's child workflows and Celery's chords are the models for child runs with a counted fan-in.

## 2. Design

### 2a. Child runs (R2.8)

```
 parent node: results = await spawn_children([ChildSpec(graph, input, key), …])
        │  (a helper around interrupt({"type": "spawn_children", children}))
        ▼
 executor sees the interrupt ── ONE fenced transaction ──────────────────────────────┐
   check limits: max_children (6), depth ≤ 2, descendants ≤ 20 per root,              │
                 children's limits ≤ the parent's remaining budget                    │
   INSERT child runs (parent_run_id, root_run_id, depth, child_key) ON CONFLICT DO NOTHING
   parent: child_total = n, running → waiting_children (lease released), children.spawned
 └───────────────────────────────────────── after COMMIT: enqueue the children ───────┘
        ▼   any worker, each child is a normal run (own lease, epoch, checkpoint, reclaim)
 child reaches a terminal state ── in THE SAME transaction as its terminal transition:
   UPDATE parent SET child_done = child_done + 1 WHERE status = 'waiting_children'
   child_done = child_total → parent waiting_children → queued (children.completed)
        ▼   after COMMIT: enqueue the parent (the relay sweep is the safety net)
 parent resumes: Command(resume={"children": [{key, status, output}], "partial": bool})
   ≥ 1 completed → the node continues (partial = some failed); none → failed(children_failed)
```

Patterns, and why:
- **Fan-in counter maintained by the database (atomic counter / Celery chord).** The counter changes in the child's terminal transaction, and the parent row lock serialises siblings. So exactly one sibling sees `child_done = child_total` and re-enqueues the parent, even if they all finish at once. It lives in `RunRepository.transition`, which is the **single choke point** for every terminal transition (worker, reaper, API cancel). No path can forget it.
- **Durable pause, reused.** Waiting on children is the same mechanism as waiting on a human: an interrupt, a waiting state, no lease, and resume with `Command`.
- **Idempotent spawn.** The children and the parent's transition commit in one transaction (all or nothing), and `UNIQUE (parent_run_id, child_key)` is defence in depth.
- **Enqueue after commit.** The same rule as publishing after commit: a child is never sent before its row exists. The relay sweep repairs a lost send.
- **Ports & Adapters for `--local-fanout`.** A `Spawner` port with two adapters:
  - `RunSpawner`: the interrupt protocol above.
  - `LocalSpawner`: runs the child graphs in-process with `asyncio.gather`, each in a fresh context, with nothing persisted. It is for tests and `runtime run --local-fanout`.

  The node calls `ctx.spawner.spawn(...)` and doesn't know which adapter it has.

**Limits → an error the node sees, not a crash (R14.6).** If a fan-out breaches a limit, the executor resumes the node at once with `{"rejected": reason}`, and `spawn_children` raises `FanOutRejected(reason)`. A workflow node can catch it; an agent's tool turns it into a tool error.

**Budget roll-up (R14.1, CR-003).** The usage counters (`model_calls`, `tool_calls_total`, `tokens`) count a whole **subtree**:
- Every charge increments the run *and its ancestors* in one statement.
- The charge is refused if any of them would pass its own limit.
- Depth ≤ 2, so that's at most 3 rows. Rows are locked child → parent → root in a fixed order, so sibling charges never deadlock.

**Cancel cascade (R1.6).** Cancelling a parent requests cancel on every non-terminal descendant in the same transaction. A child that finishes after its parent is terminal leaves the counter alone (`WHERE status = 'waiting_children'`).

**Backpressure (R2.9).**
- `POST /runs` returns **`429` + `Retry-After`** (RFC 9457 problem `overloaded`) when the queue depth is above `queue_depth_limit`.
- Queue depth = runs in `queued`, counted in **Postgres**, the source of truth. That count is right even when Redis is down or a message is duplicated. It is cached for 1 s per API replica.
- Children spawned by workers are **not** refused. Refusing them would strand parents that are already waiting; they count toward the depth and slow new admissions instead.
- The depth is reported in `/admin/state`.

### 2b. Sub-agents (CR-005)

```
 RunExecutor._drive
   orchestrator = SubagentOrchestrator(run, fence, pool, limits, outbox, …)
   await orchestrator.recover()         ← restart every non-terminal invocation from its checkpoint
   main graph (create_agent) ── tools: spawn_subagent · subagent_status · wait_subagents · cancel_subagent
   finally: orchestrator.stop(…)        ← pause / release / crash: leave them resumable; cancel / fail: cancel them

 spawn_subagent(agent, task, context?)  → the ToolPipeline ledger (idempotent by key)
   orchestrator.spawn(key, agent, task)
     INSERT subagent_invocations (handle = f(key), spawned_by = key UNIQUE) ON CONFLICT DO NOTHING
     asyncio.create_task(run_one(handle), context=contextvars.Context())   ← the measured fix
       semaphore(4) · total ≤ 10 · asyncio.timeout(sub-agent timeout)
       create_agent(sub-agent definition, own tools + report_progress + return_result)
         checkpointer = FencedCheckpointer(fence = THE MAIN RUN'S, thread = <run>/sub/<handle>)
         its events: its own outbox → committed with ITS checkpoints into the main run's log
         its model/tool calls charge its own limits AND the main run's (roll-up)
```

Patterns, and why:
- **Supervisor (in-process).** The orchestrator owns the lifecycle of its tasks: spawn, track, limit, cancel, recover. The main agent only sees four tools.
- **Same lease, same fence.** Sub-agents write under the main run's epoch. A zombie's sub-agents are fenced along with it, and nothing new is needed for safety.
- **Durable task table (`subagent_invocations`) + checkpoint per sub-agent.** Recovery is one path: on any (re)start, resume every non-terminal handle from its thread. Completed handles are never touched (AC41).
- **Idempotent spawn.** The handle comes from the tool's idempotency key, so a replayed `spawn_subagent` returns the same handle, and `UNIQUE (spawned_by)` stops a second row.
- **Isolation by construction.**
  - **Context:** a fresh context and a fresh conversation (its own prompt and one user message with the task) (R16.6).
  - **Tools:** grants are its own tools only (R16.7).
  - **Policy:** for sub-agents, `RequireApproval` / `Ask` → `Deny`, because approval goes through the main agent.
- **Turn guard (R16.9).** In `RuntimeMiddleware.awrap_model_call`: if the main agent answers with no tool calls while sub-agents are still running, wait for them (bounded by the run's remaining time), add their results to the conversation, and call the model once more.
- **Budgets (R16.8).**
  - **Soft limit:** at 80 % of the main run's `max_model_calls` / `max_tool_calls`, sub-agents get a wrap-up note before their next model call ("call `return_result` now").
  - **Hard limit:** they are cancelled.

**The four main-agent tools and two sub-agent tools** go through the full pipeline like any tool.
- They get the orchestrator from `ToolContext`.
- Each `ToolSpec` gets an optional `timeout_s`, because `wait_subagents` blocks for up to 120 s and the default tool timeout is 30 s.
- `report_progress` is rate-limited to 1 per 2 s and 50 per sub-agent. Extra calls are dropped with a note to the model.
- `return_result` is validated against `output_schema` if one is set.

**Test fixtures.**
- `AgentInput.subagent_scripts: {agent: [ScriptTurn]}` gives each scripted sub-agent its replies, so no API key is needed.
- A fixture main agent `delegator` has two leaf sub-agents:
  - `scribe`: `save_note`
  - `mathematician`: `calculator`

## 3. Tasks

| # | Task | Requirements | Verification |
|---|---|---|---|
| **5a** | | | |
| 5.1 | Migration `0007`: `runs.root_run_id`, `depth`, `child_key`, `descendants`; `UNIQUE (parent_run_id, child_key)`; index on `status = 'queued'` | R2.8, R14.6 | Migration test; up/down |
| 5.2 | `spawn_children` + `Spawner` port (`RunSpawner`, `LocalSpawner`); the executor's fan-out transaction with limits; `children.spawned` | R2.8, R14.6 | Integration: spawn, idempotence, every limit → `FanOutRejected` |
| 5.3 | Fan-in in `transition` (counter, re-enqueue, `children.completed`); resume with the children's results; `partial`; `children_failed`; cancel cascade | R2.8, R1.6 | Integration: N siblings finishing concurrently → exactly one re-enqueue; partial; all failed; cascade |
| 5.4 | Budget roll-up through ancestors (model calls, tool calls, tokens) | R14.1, R14.6 | Integration: totals; an ancestor's limit stops a child |
| 5.5 | Backpressure: `429` + `Retry-After`; depth in `/admin/state` | R2.9 | API tests |
| 5.6 | `fanout` demo workflow; e2e `fanout` (AC6) and `child-crash`; `make demo-fanout`; ADR-0005 (child runs vs `Send` vs sub-agents); PR 5a | AC6 | e2e 5× |
| **5b** | | | |
| 5.7 | Migration `0008`: `subagent_invocations` (+ fencing trigger, grants); repository | R16.3, §9 | Migration and grant tests |
| 5.8 | `SubagentOrchestrator`: spawn (fresh context), semaphore 4 / total 10, timeout, cancel, stop, recover | R16.3 | Integration with fake sub-agents |
| 5.9 | Sub-agent graphs from `SubAgentDefinition`: own checkpointer thread, own outbox, scripted model, isolated grants; approval → deny | R16.6, R16.7 | Integration: first model request = prompt + task only; denied tool |
| 5.10 | Tools: `spawn_subagent`, `subagent_status`, `wait_subagents`, `cancel_subagent`, `report_progress`, `return_result`; `ToolSpec.timeout_s`; automatic grants | R16.4, R16.5 | Integration per tool |
| 5.11 | Turn guard (R16.9); budgets: roll-up, soft → wrap-up note, hard → cancel | R16.8, R16.9 | Integration |
| 5.12 | Executor wiring: recover on start; stop on pause / release / cancel / fail / complete; `GET /runs/{id}` lists sub-agents; `subagent.*` events | R16.3, R16.10 | Integration: crash resume (cancel worker A mid-task, worker B resumes) |
| 5.13 | `delegator` fixture agent; e2e `subagents-crash` (AC41); `make demo-subagents`; summary, docs, PR 5b | AC40–AC42 | e2e 5×; coverage ≥ 90 % |

## 4. Success criteria

| # | Criterion | How | Pass when |
|---|---|---|---|
| **5a** | | | |
| SC1 | **AC6: fan-out across workers** | e2e (`make demo-fanout`) | With 2 workers, a parent spawns 6 children; `run.started` owners for the children show **≥ 2 distinct workers**; the parent completes with all 6 results |
| SC2 | **The parent waits without a lease** | integration | `waiting_children`: no owner, no lease, message acked |
| SC3 | **Atomic fan-in** | integration (50 rounds) | 6 children finishing *concurrently* → `child_done = 6` and the parent is re-enqueued **exactly once** |
| SC4 | **Partial results** | integration | Some children fail → the parent continues with `partial = true` (also in `run_results`); all fail → `failed(children_failed)` |
| SC5 | **A crashed child doesn't break the fan-in** | e2e (SIGKILL) | A worker running a child is killed → the child is reclaimed and completes; the parent fans in once with every result |
| SC6 | **Fan-out limits (R14.6)** | integration | > `max_children`, depth > 2, or > 20 descendants per root → `FanOutRejected` seen by the node; nothing created; the run continues |
| SC7 | **Idempotent spawn** | integration | A crash before the fan-out commit → no children; the retry creates each child exactly once |
| SC8 | **Cancel cascade** | integration | Cancelling the parent cancels every non-terminal descendant; a child finishing afterwards changes nothing |
| SC9 | **Budget roll-up** | integration | Children's usage appears in the parent's and root's counters; a child's charge that would pass an ancestor's limit fails the child with `budget:*` |
| SC10 | **Backpressure (R2.9)** | API | Depth > limit → `429`, `Retry-After`, problem `overloaded`; children are still created; depth in `/admin/state` |
| SC11 | **Local fan-out** | integration | The same `fanout` graph with `LocalSpawner` gives the same results with no worker |
| **5b** | | | |
| SC12 | **Parallel in the same worker** | integration | Two sub-agents run concurrently (their tool calls overlap in time) in the main run's worker; ≤ 4 at once; the 11th spawn → tool error |
| SC13 | **Isolation & privilege (AC39, minus sandboxes)** | integration | A sub-agent's first model request contains **only** its system prompt and the task; a main-agent tool it lacks → `Deny(not_granted)`; `ask` → deny |
| SC14 | **AC40: status, return, cancel, timeout** | integration | `subagent_status` shows `report_progress` messages; `return_result(status=partial)` reaches the main agent as partial; `cancel_subagent` stops it between steps; past its timeout → `failed: timeout`; rate limit enforced |
| SC15 | **Turn guard (R16.9)** | integration | A final answer while a sub-agent runs → it is awaited and the main agent gets one more model call with its result |
| SC16 | **AC41: crash resume** | e2e (`make demo-subagents`, SIGKILL) | Killed while two sub-agents are mid-task → the new owner resumes the main agent and both sub-agents from their checkpoints; no completed sub-agent step re-runs (its tool ledger shows no re-execution); no double spawn; **exactly one result per handle** |
| SC17 | **AC42: budget roll-up** | integration | Sub-agent usage appears in the main run's totals; at 80 % sub-agents get the wrap-up note; at the hard limit they are cancelled and the run fails `budget:*` |
| SC18 | **Fenced** | integration | A sub-agent of a fenced-off (zombie) execution can't write a checkpoint, event or invocation update |
| SC19 | **Visible** | API | `GET /runs/{id}` lists sub-agents (agent, status, progress, usage); `subagent.spawned / progress / completed` are in the run's event log and stream |
| SC20 | **Quality** | CI | All jobs green, including e2e; coverage ≥ 90 %; each new e2e scenario passes 5× in a row locally; no API key |

## 5. Risks

| Risk | Mitigation |
|---|---|
| Sub-agents inherit the parent's run context (measured) | Fresh `contextvars.Context()` per task; a test asserts the main run's step count and node events are unaffected |
| Deadlocks between sibling charges and fan-in | Fixed lock order (self → parent → root); the 50-round concurrency test |
| Event `seq` contention: many sub-agents append to one run's log | Short transactions; acceptable at ≤ 4 in parallel. Measure, and note the result in the summary |
| A long `wait_subagents` blocks the main graph's step | It's bounded (≤ 120 s, and by the run's remaining time); the heartbeat keeps the lease alive meanwhile |
| Scope (two subsystems) | Two PRs; 5b starts only after 5a has merged |
