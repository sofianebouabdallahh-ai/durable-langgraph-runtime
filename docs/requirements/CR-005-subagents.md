# CR-005 — Sub-agents: any agent can delegate to other agents

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-10-11 |
| **Base document** | [`Project_4_Detailed_Requirements_K8s.pdf`](Project_4_Detailed_Requirements_K8s.pdf) (v1.0 + Kubernetes) |
| **Depends on** | R2.8 (sub-runs), CR-001 (sessions), CR-003 (guardrails), CR-004 (agent definitions) |
| **Scope** | New §16 Sub-agents; amendments to R2.8, R14.6, R15.1, CR-004 §6, §5, §6 (UI), §9, §11 |

## 1. Motivation

R2.8 lets a run spawn **child runs** that execute in parallel on any worker, but only the hard-coded research workflow uses them, and CR-004 §6 put "agents delegating to other agents" out of scope. We want this to be general: **any agent may declare sub-agents in its `.agent.md` file and delegate tasks to them**, including several at once, in parallel.

### How others do it, and what we do differently
- **Claude Code subagents** and the **LangChain `deepagents` library** (`SubAgentMiddleware`, a `task` tool) give the main agent a tool that runs another agent with its own prompt, its own tools and a **fresh context**, and returns only its final answer. That is the pattern we adopt.
- They run the sub-agent **in the same process**. We run each delegation as a **child run** (R2.8), so sub-agents spread across worker pods and each gets its own checkpoint, lease, fencing and reclaim. This is the same design decision the spec makes for research (sub-runs instead of LangGraph `Send`), now applied to every agent.

## 2. New section — §16 Sub-agents

### R16.1 Declaring sub-agents — MUST
An agent's frontmatter (CR-004 R15.1) lists the agents it may delegate to:

```yaml
subagents:
  - researcher                       # by name; must be another .agent.md
  - name: data-analyst
    max_parallel: 2                  # optional: tighter than max_children
    description: "Analyses CSV data with Python. Give it the data and the question."
```

- Only listed agents can be delegated to (**deny by default**, like tools, R14.9).
- Validation (R15.2) rejects: unknown names, self-reference, and **cycles** (A → B → A), since delegation forms a graph that must be acyclic. It also rejects chains deeper than the depth limit (R16.6).
- The `description` (or, by default, the sub-agent's own `description`) tells the parent model when to use that sub-agent.

### R16.2 Delegation is a tool — MUST
For each declared sub-agent the harness exposes a tool `delegate_to_<name>(task: str, context?: str)`. Like any tool call, it goes through the full order in CR-004 R15.7: schema validation, grant, `pre_tool` hooks, policy, budget, idempotency.
- **Several delegations in one model response run in parallel.** Each one becomes a child run on `runs:work`, so they land on any available worker.
- The child's **final answer is returned as the tool result** (truncated per R14.5, with the full output in `run_results`). With an `output_schema`, the result is structured.

### R16.3 Context isolation — MUST
A sub-agent starts with a **fresh context**: its own system prompt, plus a single user message containing `task` (and `context` if given). It does **not** see the parent's conversation, tool results or memory. The parent decides exactly what to pass.
This keeps child context small and cheap, and it stops data from the parent's session leaking into another agent's context.

### R16.4 Least privilege — MUST
A sub-agent gets **only its own tools** (from its own file), never the parent's, and it cannot raise any limit. Its budget is the **smaller** of its own limits and what remains of the parent's budget (R16.5).

### R16.5 Waiting costs no worker — MUST
While its children run, the parent is `waiting_children`. It **releases its lease and acks its message** (R2.8), so it occupies no worker slot.
This prevents a classic distributed deadlock: if waiting parents held their slots, a pool full of parents waiting for children that can't get a slot would stop forever. When the last child finishes, the parent is re-enqueued and resumes from its checkpoint with the tool results filled in.

### R16.6 Limits — MUST
- **Depth:** at most 2 levels below the root (root → sub-agent → sub-sub-agent; CR-003 R14.6).
- **Fan-out:** `max_children` per parent (default 6), `max_parallel` per sub-agent, and at most 20 descendants per root run.
- **Budget roll-up:** child usage (model calls, tool calls, tokens, cost) counts toward every ancestor. A parent can't escape its budget by delegating.
- Exceeding any of these is a **tool error the parent sees** (e.g. `subagent_limit: max_children`), not a crash, so the model can adapt.

### R16.7 Failure, cancellation and approval propagate — MUST
- **Child fails** (error, budget, timeout, loop): the parent gets a tool error with the reason and decides what to do (retry differently, continue, give up). If some children succeed and others fail, the parent continues with the successful results (`partial=true`, R2.8).
- **Parent cancelled** (R1.6): cancellation **cascades** to all non-terminal descendants.
- **Approval inside a child** (R1.4 interrupt, `ask` from a hook, R15.5): it bubbles up to the root's session as an `interrupt` message naming the child agent. Approving or rejecting it resolves the child. The parent stays `waiting_children` meanwhile.
- **Crash:** a child is a normal run, so reclaim (R2.4) applies. The parent is unaffected, because it was waiting without a lease. A reclaimed parent never re-spawns children whose delegation already completed: the delegation call is idempotent by key (R2.6).

### R16.8 Visibility — MUST
- **Events:** the parent emits `subagent.started {child_run_id, agent, task_summary}` and `subagent.completed {child_run_id, status, usage}`. Child runs keep their own event streams.
- **Session stream:** a chat session (CR-001 R12.5) shows delegations as nested, collapsible cards with the sub-agent's live status, the worker pod running it, its tool calls and its final answer. The UI subscribes to child streams on demand.
- **Tracing:** child runs continue the parent's trace (R2.7), so Jaeger shows the whole delegation tree.
- **API:** `GET /runs/{id}` includes the child tree (agent, status, usage, owner pod).

### R16.9 Example — MUST
- `agents/chat.agent.md` declares `subagents: [researcher, data-analyst]`.
- `agents/data-analyst.agent.md` is a new agent with `run_python` only.
- A demo (`make demo-subagents`) asks a question that makes the chat agent delegate to **two sub-agents in parallel** and shows the children running on different workers.

## 3. Amendments

| Req | Change |
|---|---|
| **R2.8** | Sub-runs become the general delegation mechanism (R16.2). The research workflow's researcher fan-out is now one use of it. |
| **CR-003 R14.6** | Applies to all delegations; adds per-sub-agent `max_parallel`. |
| **CR-004 R15.1, R15.2** | Frontmatter adds `subagents`; validation adds the cycle and depth checks. |
| **CR-004 §6** | "Agents delegating to other agents as tools" moves **into scope**. Free-form hand-off (transferring the conversation to another agent permanently) stays out of scope. |
| **§5 API** | `GET /runs/{id}` includes the child tree; the session stream carries `subagent.*` events. |
| **§6 / R12.11 UI** | Nested sub-agent cards in the chat view; child chips in the run view (R6.1) now apply to any agent. |
| **§9 Storage** | `runs` adds `delegated_by_tool_call_id` (links a child to the tool call that spawned it). |

## 4. Acceptance criteria (§11)

- **AC37 · Parallel delegation.** With 2 workers, the chat agent delegates to two sub-agents in one turn. Both children run concurrently on **different workers**, the parent holds no lease while waiting, and the answer uses both results.
- **AC38 · No deadlock.** With 1 worker at `--concurrency 1`, a parent that delegates to 3 children still completes, because waiting parents free their slot.
- **AC39 · Isolation & privilege.** A child's first model call contains only its own system prompt and the task. A child that tries to call a tool its parent has but it doesn't is denied.
- **AC40 · Failure & cancel.** One child forced to fail → the parent gets the tool error and completes with the other result (`partial`). Cancelling the parent → every descendant ends `cancelled`.
- **AC41 · Crash.** SIGKILL the worker running a child mid-task → the child is reclaimed elsewhere, completes once, and the parent receives exactly one result for that delegation.
- **AC42 · Validation.** A definition cycle (A → B → A) or an over-deep chain fails `runtime agents validate`.

## 5. Impact on the phase plan

| # | Phase | Adds |
|---|---|---|
| 1 | Durable single run | Definition schema includes `subagents` and the cycle/depth validation (AC42) |
| 5 | Sub-runs & backpressure | Built as the **general** delegation mechanism: `delegate_to_*` tools, context isolation, budget roll-up, propagation of failure/cancel/approval (R16.2–R16.7). AC38, AC40, AC41 |
| 6 | Chat | `chat` + `data-analyst` agents with sub-agents; `make demo-subagents`. AC37, AC39 |
| 8 | Research | The researcher fan-out uses the same mechanism |
| 9 | Observability | Delegation tree in traces and metrics |
| 11 | UI | Nested sub-agent cards (R16.8) |

Estimated additional effort: **~8–12 focused hours**. Most of the machinery (child runs) was already planned for Phase 5; this makes it general.

## 6. Out of scope / roadmap
- **Hand-off:** permanently transferring the conversation to another agent (rather than delegating a task and getting a result back).
- **Sub-agents calling back to the parent mid-task,** or messaging each other: only the task goes down and only the result comes up.
- **Dynamic sub-agents created by the model at runtime:** only declared agents can be delegated to.
