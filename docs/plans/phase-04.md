# Phase 4 plan — Tools & human-in-the-loop

> **Status: delivered.** Every success criterion passed; results are in [progress/phase-04.md](../progress/phase-04.md).

**Goal:** agents call tools through one safe pipeline. Every call is validated, permitted, budgeted, idempotent and audited, so a retry after a crash never repeats a side effect. And a run can **pause for a human** for hours, with no worker holding it, then resume exactly where it stopped.

**Done when:** AC4 passes as `make demo-approval`: a run pauses for approval, **all workers are killed**, the approval (with edits) is given through the API with no worker alive, fresh workers resume the run, and it completes using the edits. Plus the success criteria below.

**Requirements:** R2.6 idempotent tool calls · R3.2 `ToolPolicy` · R3.4 tool registry (+ `risk_class`, `max_calls`, `isolation`; CR-002/003 amendments) · R1.4 interrupt / approve / reject · R14.1 model-call and tool budgets (hard limits) · R14.5 per-call limits (result truncation, arg size) · R14.9 deny-by-default grants · R14.10 risk classes · R14.11 strict argument validation · R14.17 audit events · R14.20 scripted test model · R15.5, R15.7–R15.9 `pre_tool` / `post_tool` hooks · §5 `POST /runs/{id}/approve`.

*Kept in phase 6, as the roadmap says:* the soft-limit wrap-up turn (R14.2), loop detection (R14.4), retries with backoff (R14.7), token/cost budgets from real model usage, and session and turn hooks.

---

## 1. Research findings

| Topic | Finding | Source / evidence |
|---|---|---|
| Resume semantics | Resuming with `Command(resume=…)` **re-executes the interrupted node from its start**: code before `interrupt()` runs again, and the value becomes `interrupt()`'s return value. Side effects before the interrupt must be idempotent or placed after it. | [LangGraph interrupts docs](https://docs.langchain.com/oss/python/langgraph/interrupts.md), [LangChain forum](https://forum.langchain.com/t/twice-execution-of-agent-when-using-the-interrupt/2964) |
| ⇒ Measured | Tool with `interrupt()` inside `create_agent`: before-interrupt code ran **2×**, after-interrupt 1×; our `wrap_tool_call` middleware ran **2×**; `tool_call_id` and args **identical** across the pause. | Local experiment (langchain 1.4.2) |
| ⇒ Consequence | Approval is decided in the wrapper **before** execution. Anything the wrapper counts (budgets) is counted **once per idempotency key**, not per invocation. The key is stable across resume. | Design |
| Why idempotency, not just checkpoints | A side effect can succeed externally while the checkpoint that records it fails; afterwards there's no local way to know whether it happened. Durable workflows need idempotency **before** they need checkpoints. | [HackerNoon](https://hackernoon.com/durable-agent-workflows-need-idempotency-before-they-need-checkpoints) |
| Idempotency keys | Derive keys deterministically from stable identifiers (no storage needed to recreate them); reuse across retries; never share a key across different payloads; enforce uniqueness with a database constraint; store and return the original result on duplicates. | [Shopify](https://shopify.dev/docs/api/usage/implementing-idempotency), [Prem](https://docs.prem.io/idempotency), [DEV](https://dev.to/techforge/designing-idempotent-apis-for-reliability-5ai1) |
| LangChain v1 HITL | Built-in `HumanInTheLoopMiddleware(interrupt_on={tool: …})`; needs a checkpointer and `thread_id`; resume with `Command`. | [LangChain HITL docs](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) |
| ⇒ Decision | We don't use the built-in HITL middleware. Approval must come from *our* policy and hooks (`RequireApproval`, hook `ask`), be audited, and survive across processes. The built-in one is keyed by tool name only. | Design |
| Middleware API | `awrap_tool_call(request, handler)`; `request` is a `ToolCallRequest` with `tool_call` (`id`, `name`, `args`), `tool`, `state` and `runtime`. | Inspected at runtime |
| Fake models | `GenericFakeChatModel` has **no `bind_tools`**, which `create_agent` requires, so our `ScriptedChatModel` implements it and reports `usage_metadata` for budgets. | Experiment |

## 2. Design

```
 model proposes a tool call ──► RuntimeToolMiddleware.awrap_tool_call (Adapter) ──► ToolPipeline
   1 schema      strict args (unknown field / wrong type → tool error the model can fix)
   2 grant       deny by default: not granted to this graph/node → Deny(not_granted)
   3 pre_tool    hooks in order: continue · modify(args) · deny · ask        (fail closed)
   4 re-validate if args were modified
   5 policy      risk-class default, then ToolPolicy: Allow · Deny · RequireApproval
                 RequireApproval / ask → interrupt() → run pauses (waiting_approval)
   6 budget      max_tool_calls (total, per tool), counted once per key (R14.1)
   7 idempotency key = sha256(run · node · call_index · tool · canonical_json(final args))
                 done → return the stored result (tool.completed {cached: true}); no execution
                 in_progress at a lower epoch → abandoned: re-execute under this epoch
   8 execute     in-process (phase 7 adds the sandbox for `isolation: sandbox`)
   9 post_tool   hooks: continue · modify(result) · deny      (also on cached results)
  10 truncate    ≤ 16 KB to the model (marker added); the full result is stored
     every non-trivial decision → audit event (policy.decision, hook.decision, tool.*)
```

**Key decisions**

1. **One pipeline, many front doors** (Chain of Responsibility, R15.7's fixed order). `ToolPipeline` doesn't depend on LangChain. `RuntimeToolMiddleware` adapts it to `create_agent` (Adapter); workflow nodes (phase 8) can call it directly.
2. **Record, then act** (the outbox idea applied to effects). Before executing, the pipeline inserts `tool_invocations(key, status='in_progress', epoch)` (fenced). After executing, it stores `done` + result. A retry finds `done` and returns the stored result; a crash mid-execution leaves `in_progress` at an old epoch, which the next owner re-executes. Tools with `side_effect: true` **also** use the key as their own primary key (`ON CONFLICT DO NOTHING`), so even that re-execution can't duplicate the effect (R2.6).
3. **Stable `call_index`.** It's derived from the checkpointed conversation (the number of tool calls before this one), not from a counter in memory. A replay therefore computes the same index and the same key.
4. **Approval is a durable pause, not a waiting worker** (R1.4). On `interrupt` the executor commits `waiting_approval` + `interrupt_payload` + `interrupt.raised`, releases the lease, and the worker **acks** its message. `POST /runs/{id}/approve {decision, edits?}` stores the resume value and re-enqueues (`approve`), or ends the run `cancelled(rejected)` (`reject`); `409` unless the run is waiting. The worker that picks it up resumes with `Command(resume=…)`.
5. **Budgets count per key.** Tool calls are counted when a `tool_invocations` row is first created; model calls when a model response is checkpointed. Both counters are stored on `runs` in the step's transaction, so they survive reclaim and are never double-counted on resume (measured: the wrapper re-runs on resume).
6. **Hooks are registered code** (`@hook("name", point="pre_tool")`, R15.9). They are deterministic, have a timeout, **fail closed** and are audited. They can only tighten: deny, ask, or modify (then re-validated). Built-ins: `redact_secrets_in_args` / `redact_secrets_in_result`.
7. **Tools are declared once** (`@runtime_tool(name, risk_class, side_effect, cache, max_calls, isolation)`, with a pydantic args model in strict mode) and registered in a `ToolRegistry`, which also feeds the agent loader's `Catalog`, so agent files are validated against real tools.
8. **A graph to exercise it:** `assistant`, a `create_agent` graph built from an agent definition (`agents/assistant/agent.md`) and driven by the scripted model in tests. Phase 6 swaps in real models with no changes to the pipeline.
9. **Phase 4 tools are deliberately small fixtures:** `calculator` (read), `save_note` (write_internal, side-effecting: a `notes` table keyed by the idempotency key), `notify` (external_side_effect: needs approval; writes an `outbox_notifications` row keyed by the idempotency key). Real tools (search, retrieve, run_python) arrive in phases 6–8.

**Patterns:** Chain of Responsibility (pipeline stages) · Adapter (LangChain middleware) · Registry (tools, hooks) · Decorator (tool and hook registration) · Idempotency key + "record, then act" · Fencing on every write (the phase 2 trigger already covers `tool_invocations`) · Durable pause (interrupt → persisted payload → resume value).

## 3. Tasks

| # | Task | Requirements | Tests (written with the task) |
|---|---|---|---|
| 4.1 | **Tool registry**: `@runtime_tool` decorator, strict args models, risk classes, `ToolRegistry` feeding the agent `Catalog`; fixture tools + migration `0006` (`notes`, `outbox_notifications`, `runs.resume_value`, `runs.model_calls`/`tool_calls` already exist) | R3.4, R14.10, R14.11 | Unit: declarations, strict validation; agent files validate against registered tools |
| 4.2 | **Hook registry** + built-in redaction hooks; timeouts; fail-closed | R15.5, R15.8, R15.9 | Unit: registration, ordering, timeout, failure → deny |
| 4.3 | **`ToolPipeline`**: the 10 stages in fixed order, audit events, truncation; `ToolPolicy` protocol + static default | R2.6, R3.2, R14.5, R14.9, R14.17, R15.7 | Unit (fake store) + integration: each stage, the order, cached replay, abandoned `in_progress` |
| 4.4 | **`ScriptedChatModel`** (`bind_tools`, tool calls, usage metadata) + the `assistant` graph from an agent definition + `RuntimeToolMiddleware` | R14.20, R15.1 | The scripted model drives a full agent loop |
| 4.5 | **Durable approval**: executor handles `__interrupt__` → `waiting_approval`; resume with `Command(resume)`; `POST /runs/{id}/approve` (approve with edits / reject); the worker acks on `waiting_approval` | R1.4, §5 | Approve, edit, reject, `409`, approval with no live worker |
| 4.6 | **Budgets**: `max_model_calls` (from the agent's `max_turns`), `max_tool_calls` total and per tool, counted per key, durable; `failed(budget:*)` | R14.1 (hard limits) | Each limit; counts survive a reclaim; no double count on resume |
| 4.7 | **E2E**: crash after a tool's side effect but before its checkpoint (SIGKILL), approval surviving a full worker restart (AC4); `make demo-tools`, `make demo-approval` | AC4, R2.6 | Scenarios in CI; 5× locally |
| 4.8 | Summary, design doc, PR | — | Coverage ≥ 90 % |

**Order:** 4.1 → 4.2 → 4.3 → 4.4 → 4.5 → 4.6 → 4.7.

**Estimate:** ~16–22 focused hours. The roadmap said 8–10, but CR-003 and CR-004 moved grants, risk classes, hooks, budgets and the scripted model into this phase.

## 4. Success criteria

| # | Criterion | Measured by | Pass when |
|---|---|---|---|
| SC1 | **Fixed pipeline order** (R15.7) | integration | a spy proves the order: schema → grant → pre_tool → re-validate → policy → budget → idempotency → execute → post_tool → truncate |
| SC2 | **A side effect happens once, even across a crash** | e2e (SIGKILL) | a worker is killed after `save_note`'s effect but before its step's checkpoint → the run completes on another worker; **exactly one** `notes` row; charged once. Two windows: (a) killed before the ledger recorded the result → the new owner takes the call over (`tool.called {taken_over: true}`) with the same key and the tool dedupes (e2e, SIGKILL); (b) killed after → the stored result is replayed (`tool.completed {cached: true}`, integration) |
| SC3 | **Idempotency rules** (R2.6) | integration | same key → no second execution; different args → new key; `in_progress` at a lower epoch → re-executed under the new epoch; a stale-epoch write → rejected by the fence |
| SC4 | **Deny by default** (R14.9) | integration | a tool not granted to the agent (including a hallucinated name) → `Deny(not_granted)` tool error to the model, `policy.decision` audited, run continues |
| SC5 | **Strict arguments** (R14.11) | integration | an unknown field or wrong type → a tool error describing the problem; the model's corrected retry succeeds |
| SC6 | **Hooks** (R15.7–R15.9) | integration | `modify` changes what executes and the key follows the final args; `deny` → tool error; `ask` → approval pause; a raising or slow hook → **fails closed**; `post_tool` redaction also applies to a **cached** result; all audited |
| SC7 | **Durable approval** (R1.4) | integration + API | `waiting_approval` with payload, lease released, message acked; approve with edits → resumes and the tool receives the edits; reject → `cancelled(rejected)`; approve when not waiting → `409` |
| SC8 | **AC4: approval survives a full restart** | `make demo-approval` (e2e) | pause → **kill every worker** → approve with edits via the API (no worker alive) → start fresh workers → completes using the edits; exactly one notification sent |
| SC9 | **Budgets** (R14.1, hard limits) | integration | exceeding `max_tool_calls` (total or per tool) or `max_turns` → `failed(budget:*)`; counters survive a reclaim; a call resumed after approval is counted **once** |
| SC10 | **Result truncation** (R14.5) | integration | a 100 KB tool result → the model sees ≤ 16 KB with a truncation marker; the full result is stored |
| SC11 | **No API key needed** | CI | every test is driven by `ScriptedChatModel` |
| SC12 | **Quality** | CI | all jobs green including e2e; coverage ≥ 90 %; each new e2e scenario passes 5× in a row locally |

## 5. Risks

| Risk | Mitigation |
|---|---|
| A crash *between* a side effect and recording it is hard to hit deliberately | A test tool that blocks after its effect until killed (e2e), plus integration tests with an injected failure at that point |
| LangChain middleware APIs change between minor versions | Pinned by the lock + cooldown; the pipeline is independent of LangChain; one thin adapter |
| Resume re-runs the wrapper (measured) | Counting and approval are idempotent by key; tests resume twice on purpose |
| Scope creep from phase 6 (real models, wrap-up, loops) | Explicitly out of scope above; the scripted model only |
