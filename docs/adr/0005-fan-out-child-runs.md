# ADR-0005 — Fan-out: child runs for distribution, sub-agents for delegation

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-16 |
| **Related** | R2.8, R2.9, R14.6, CR-005 (sub-agents), [phase 5 plan](../plans/phase-05.md) |

## Context

The research workflow fans out one researcher per sub-question and fans back in (R4.2). A main agent also delegates focused tasks to its sub-agents at runtime (CR-005). LangGraph offers `Send` for fan-out, but `Send` runs every branch inside one superstep, in one process. The question is how a fan-out should run when the workers are a pool of separate processes (pods).

## Decision

**Three mechanisms, each for one job:**

1. **Child runs (R2.8) for distributed fan-out.**
   - Each child is a full run: its own `run_id`, checkpoint thread, lease, epoch and reclaim. It is queued like any run, so the children spread over the whole worker pool (AC6).
   - The parent spawns the children and moves to `waiting_children` in **one fenced transaction**. It releases its lease and acks its message, so a parent that waits holds nothing.
   - Each child's terminal transition increments the parent's `child_done` **in the same transaction**. The parent's row lock serialises siblings, so exactly one of them re-queues the parent.
   - The parent resumes through the same `interrupt()` / `Command(resume=…)` path as an approval. The fan-in is computed at resume time from `run_results`.
2. **Sub-agents (CR-005) for in-process delegation.** These are concurrent tasks inside the main run's worker, sharing its lease and epoch, each with its own checkpoint thread. They have low latency and rich communication (progress, status, return), and they're bounded by one pod.
3. **`Send` only for local fan-out** (`--local-fanout`, tests) and within a single node's work. It is never used to distribute.

Workflow nodes depend on a `Spawner` port. `RunSpawner` implements the child-run protocol; `LocalSpawner` runs the same children in-process.

## Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Child runs** (chosen for distribution) | Crosses processes and pods; each child recovers on its own (a crash affects one child, not the fan-out); its own budget and limits; visible as runs in the API | A parent/child protocol: spawn, counter, re-enqueue, partial results, cancel cascade, budget roll-up; queue latency per child | Chosen. The protocol is ~150 lines plus tests, and it reuses the durable pause |
| **LangGraph `Send`** | Built in; no protocol; lowest latency | One superstep in one process: it can't distribute, and a crash re-runs every branch that hadn't been checkpointed | Local fan-out only |
| **Parent polls its children** (parent keeps its lease) | No counter | A worker slot is held for the whole fan-out; parents with many children starve the pool; polling load | Rejected |
| **Fan-in by a separate coordinator process** | The parent needs no protocol | One more component to run, scale and make highly available; the database transaction already gives atomicity | Rejected |
| **A database trigger maintains the counter** | No code path can bypass it | Business logic hidden in SQL; harder to test; the re-enqueue (Redis) can't happen in a trigger anyway | Rejected: `RunRepository.transition` is already the single choke point for terminal transitions |

## Consequences

- **Locks are taken deepest first everywhere:** child → parent → root, for fan-in, budget roll-up and fan-out. The cancel cascade locks descendants before the parent. A 50-round concurrency test covers the counter.
- **Budgets roll up.** A charge updates the run and its ancestors (at most 3 rows, depth ≤ 2), and each ancestor's own limit bounds its whole tree.
- **Children are not subject to API admission control** (`429`, R2.9). Refusing them would strand a parent that is already running; they count toward the queue depth instead.
- **A child's timeout is capped by its parent's remaining time.** The parent's own timeout is checked when it resumes.
- **`partial` is computed at completion from the children's statuses,** not kept in memory, so it survives a reclaim of the parent.
