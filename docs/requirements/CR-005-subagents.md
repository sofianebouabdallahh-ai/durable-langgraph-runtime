# CR-005 — Sub-agents: leaf agents orchestrated in-process by their main agent

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-10-11 |
| **Base document** | [`Project_4_Detailed_Requirements_K8s.pdf`](Project_4_Detailed_Requirements_K8s.pdf) (v1.0 + Kubernetes) |
| **Depends on** | CR-001 (sessions), CR-002 (sandboxes), CR-003 (guardrails), CR-004 (agent definitions) |
| **Amends** | CR-004 R15.1 (file layout), R15.10, §6; ADR-0003 (agent folder layout); CR-003 R14.6 |
| **Scope** | New §16 Sub-agents; amendments listed in §3 |

## 1. Motivation

A main agent should be able to hand focused tasks to **sub-agents**: specialised agents with their own system prompt and tools, which work in parallel and report back. Sub-agents are:

- **Defined next to their main agent,** as sub-folders of its folder. The harness discovers them.
- **Leaf agents.** A sub-agent can't have sub-agents of its own.
- **Run in the same worker process as their main agent,** managed by an **orchestrator** in the harness.
- **In communication with the main agent:** a sub-agent reports its **status/progress** while working and **returns** a result when done. The main agent can check status, wait or cancel.

### Two fan-out mechanisms, on purpose

| | **Sub-agents (this CR)** | **Child runs (spec R2.8)** |
|---|---|---|
| Used for | An agent delegating focused tasks it decides on at runtime | The research **workflow**'s fixed researcher fan-out |
| Where they run | **Same worker, same container** as the main agent (concurrent asyncio tasks) | **Any worker pod** (each child is a queued run) |
| Lease / fencing | Share the main run's lease and epoch | Own lease, own epoch |
| Latency | Low: no queue hop | Higher: enqueue → claim |
| Scale limit | One pod's CPU/memory per run | The whole worker pool |
| Failure blast radius | A worker crash interrupts the run and all its sub-agents; all **resume from their own checkpoints** on reclaim | Each child fails and recovers independently |
| Communication | Rich: live status, progress, explicit return | Result only, at the end |

Claude Code subagents and LangChain `deepagents` (`SubAgentMiddleware`, a `task` tool) also run sub-agents in-process with a fresh context. We add durability: every sub-agent is checkpointed, so a crash doesn't throw away its work.

## 2. New section — §16 Sub-agents

### R16.1 Folder layout and discovery — MUST
Each **main agent is a folder**, and each **sub-agent is a sub-folder** of it:

```
backend/agents/
├── chat/                         main agent "chat"
│   ├── agent.md                  main definition (CR-004 R15.1 format)
│   ├── researcher/
│   │   └── agent.md              sub-agent "researcher" (leaf)
│   └── data-analyst/
│       └── agent.md              sub-agent "data-analyst" (leaf)
└── planner/
    └── agent.md                  main agent with no sub-agents
```

- **Discovery:** the harness treats every immediate sub-folder of a main agent's folder that contains an `agent.md` as one of its sub-agents. There is nothing to list in the main agent's frontmatter; the folder *is* the declaration.
- **Names:** the folder name is the agent name (kebab-case). The frontmatter `name` must match it. A sub-agent's full id is `<main>/<sub>` (e.g. `chat/researcher`).
- **Scope:** a sub-agent belongs to its main agent only. If two main agents need the same specialist, each has its own copy. Copying is the price of keeping each agent self-contained and reviewable in one folder.
- **Fail fast** (R15.2): a sub-agent folder without `agent.md`, a name mismatch or a duplicate name stops the loader with an error naming the path.

### R16.2 Sub-agents are leaf agents — MUST
Enforced in two places:
- **Structure:** a sub-agent folder may not contain further agent folders. A nested `agent.md` is a validation error ("sub-agents are leaf agents").
- **Schema:** the sub-agent schema is a restricted form of the main schema (below). Keys outside it, such as `subagents` or session hooks, are rejected as unknown.

```markdown
---
name: researcher
description: Finds and cites evidence for one focused question. Give it the question and what counts as done.
version: 1
model: researcher
max_turns: 8
limits: { max_tool_calls: 8, max_cost_usd: 0.20, timeout_s: 180 }
tools: [search, retrieve]
output_schema: null              # or a registered schema for a structured result
hooks:
  pre_tool:  [block_private_urls]
  post_tool: [redact_secrets_in_result]
---
You research exactly one question. Cite every claim with at least two sources.
Report progress with `report_progress` after each source you read.
Finish by calling `return_result`.
```

Allowed hook points for sub-agents: `pre_tool`, `post_tool`, `pre_model`, `post_model`. Session and turn hooks belong to the main agent.

### R16.3 The orchestrator — MUST
A harness component, the **sub-agent orchestrator**, owns the sub-agents of each run:

| Responsibility | Detail |
|---|---|
| Spawn | Starts each sub-agent as a concurrent task in the worker running the main agent, with a fresh context (R16.6) |
| Track | Keeps each sub-agent's status, progress, result and usage in `subagent_invocations` (durable) |
| Limit | Max **4 running in parallel** and **10 in total** per run (configurable down only, R14.3), a timeout per sub-agent, budgets (R16.8) |
| Persist | Each sub-agent is a LangGraph graph with **its own checkpoint thread** (`thread_id = <run_id>/sub/<handle>`), written through the epoch-aware checkpointer (R2.10) under the main run's epoch |
| Recover | On reclaim (R2.4) or graceful release (R10.7), the new owner resumes the main agent **and** every non-terminal sub-agent from its own checkpoint. Completed sub-agents are never re-run |
| Cancel | Cancels sub-agents on request, on main-run cancel (R1.6), on timeout, or at the main run's hard budget limit |
| Report | Emits `subagent.spawned`, `subagent.progress`, `subagent.completed` events (persisted, R1.5) |

A run's sub-agents run inside that run's worker slot. Worker `--concurrency` still counts runs; per-run parallelism is bounded by the limit above. Worker CPU and memory requests (R10.8) are sized for it.

### R16.4 Tools the main agent gets — MUST
When a main agent has sub-agents, the harness adds these tools automatically. They go through the full tool order (R15.7) like any tool:

| Tool | Blocking? | Does |
|---|---|---|
| `spawn_subagent(agent, task, context?)` → `{handle}` | No | Starts a sub-agent. `agent` must be one of this main agent's sub-agents (anything else is denied). Idempotent by tool-call id, so replay after a reclaim never spawns twice |
| `subagent_status(handles?)` → `[{handle, agent, status, progress, elapsed_s, usage}]` | No | Live status of some or all sub-agents |
| `wait_subagents(handles, timeout_s)` → `{completed: [...results], pending: [...status]}` | Yes, up to `timeout_s` (≤ 120 s) | Waits for the given sub-agents and returns the results of those that finished |
| `cancel_subagent(handle, reason)` | No | Cooperative cancel (checked between the sub-agent's steps and before its tool calls) |

Parallel delegation therefore looks like: spawn several, then wait for them. The main agent may keep working (or check status) in between.

### R16.5 Tools the sub-agent gets — MUST
Added automatically to every sub-agent:

| Tool | Does |
|---|---|
| `report_progress(message, percent?)` | Non-blocking status update. It is stored on the invocation, visible through `subagent_status`, and streamed as `subagent.progress`. Rate-limited to 1 per 2 s and 50 per sub-agent; extra updates are dropped with a note to the model |
| `return_result(summary, result?, status = success \| partial \| failed)` | Ends the sub-agent with an explicit result. `result` is validated against `output_schema` if one is set |

If a sub-agent stops without calling `return_result`, its last assistant message becomes the result with `status=success`. If it hits a limit, the result is `status=failed` (or `partial` if it reported progress) with the reason.

**Communication is upward only** in v1.0: status and result go up, and the task goes down. A sub-agent asking the main agent a question mid-task is on the roadmap (§6).

### R16.6 Context isolation — MUST
A sub-agent starts with its own system prompt and a single user message containing `task` (and `context` if given). It never sees the main agent's conversation, tool results or session memory. The main agent decides exactly what to pass.

### R16.7 Least privilege — MUST
- A sub-agent has **only the tools in its own file**, never the main agent's. It cannot spawn sub-agents (it has no spawn tools).
- **No approval-gated actions in sub-agents:** tools with risk class `external_side_effect` (R14.10) and hooks returning `ask` are rejected for sub-agents at validation (for tools) and at runtime (for `ask` → treated as `deny`). Human approval goes through the main agent, which a person is talking to.
- **Sandboxed tools** (`run_python`, CR-002) get a **separate sandbox per sub-agent invocation**, so sub-agents can't see each other's files.

### R16.8 Budgets — MUST
- Each sub-agent has its own limits (from its file, tightened by the orchestrator).
- All sub-agent usage counts toward the **main run's budget** (R14.1).
- At the main run's soft limit (R14.2), running sub-agents are asked to wrap up (`return_result` with what they have). At the hard limit they are cancelled.

### R16.9 A turn can't end with sub-agents still running — MUST
If the main agent produces its final answer while sub-agents are still running, the orchestrator first waits for them (bounded by the run's remaining time), then gives the main agent one more model call with their results. A sub-agent spawned in one turn never outlives that turn's run.

### R16.10 Visibility — MUST
- **Session stream** (CR-001 R12.5): sub-agents appear as nested cards under the main agent's message, with live progress messages, their tool calls and their returned result.
- **Tracing** (R2.7): spans `subagent:{name}` sit under the main agent's span.
- **API:** `GET /runs/{id}` lists the run's sub-agent invocations (agent, status, progress, usage).
- **Metrics** (R7.2): sub-agents spawned, running, by outcome; duration; cost by sub-agent.

## 3. Amendments

| Req | Change |
|---|---|
| **CR-004 R15.1 / ADR-0003** | Agents move from flat files `agents/<name>.agent.md` to **folders** `agents/<name>/agent.md`; sub-agents are sub-folders (R16.1). |
| **CR-004 R15.10** | The research workflow's agents become `agents/planner/`, `agents/researcher/`, `agents/critic/`, `agents/synthesizer/` (main agents used by workflow nodes). The researcher fan-out remains **child runs** (R2.8) to keep the cross-pod fan-out and AC6. |
| **CR-004 §6** | "Agents delegating to other agents" moves into scope as sub-agents. Hand-off (transferring the conversation permanently) stays out of scope. |
| **CR-003 R14.6** | Depth is fixed by design: a main agent and its leaf sub-agents. Adds the per-run sub-agent limits (R16.3). |
| **§5 API** | `GET /runs/{id}` includes sub-agent invocations; the session stream carries `subagent.*` events. |
| **§9 Storage** | New table `subagent_invocations (handle PK, run_id, agent, task, status, progress jsonb, result jsonb, usage jsonb, epoch, spawned_by_tool_call_id UNIQUE, created_at, finished_at)`. |

## 4. Acceptance criteria (§11)

- **AC37 · Parallel sub-agents.** The chat agent spawns `researcher` and `data-analyst` in one turn. Both run concurrently in the **same worker** (same pod name in events). Progress updates arrive on the session stream while they run, and the final answer uses both results.
- **AC38 · Leaf & layout.** `runtime agents validate` fails for:
  - a nested agent folder inside a sub-agent
  - a `subagents` key or a session hook in a sub-agent file
  - an `external_side_effect` tool in a sub-agent
  - a folder/name mismatch
- **AC39 · Isolation & privilege.** A sub-agent's first model call contains only its own system prompt and the task. A sub-agent calling a tool its main agent has but it doesn't is denied. Two sub-agents using `run_python` get different sandboxes.
- **AC40 · Status, return, cancel, timeout.** `subagent_status` shows `report_progress` messages. `return_result(status=partial)` reaches the main agent as partial. `cancel_subagent` stops a sub-agent between steps. A sub-agent past its timeout returns `failed: timeout`. The main agent can't finish while a sub-agent runs (R16.9).
- **AC41 · Crash resume.** SIGKILL the worker while two sub-agents are mid-task. The reclaiming worker resumes the main agent and both sub-agents from their checkpoints: no completed sub-agent step is re-executed, no sub-agent is spawned twice, and `subagent_invocations` ends with exactly one result per handle.
- **AC42 · Budget roll-up.** Sub-agent usage appears in the main run's totals. A sub-agent burning tokens drives the main run to its soft limit (sub-agents asked to wrap up), then the hard limit (sub-agents cancelled).

## 5. Impact on the phase plan

| # | Phase | Adds |
|---|---|---|
| 1 | Durable single run | Folder-based loader with sub-agent discovery and the leaf/schema checks (R16.1, R16.2; AC38) |
| 5 | Sub-runs, sub-agents & backpressure | Workflow child runs (R2.8) **and** the sub-agent orchestrator, tools, persistence and recovery (R16.3–R16.9). AC40–AC42 |
| 6 | Chat | `chat` with `researcher` and `data-analyst` sub-agents; `make demo-subagents`. AC37, AC39 |
| 7 | Sandboxes | One sandbox per sub-agent invocation (R16.7) |
| 9 | Observability | Sub-agent spans and metrics |
| 11 | UI | Nested sub-agent cards with live progress |

Estimated additional effort: **~10–14 focused hours.**

## 6. Out of scope / roadmap
- **A sub-agent asking its main agent a question mid-task** (`ask_parent`): bidirectional messaging, with the sub-agent paused until answered.
- **Sharing a sub-agent across main agents** (a shared library folder referenced by name).
- **Running sub-agents on other pods:** a per-sub-agent `placement: remote` option using child runs (R2.8) for heavy sub-agents.
- **Hand-off** (permanently transferring the conversation to another agent).
