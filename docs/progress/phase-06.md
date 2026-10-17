# Phase 6 — Chat sessions + chat agent

**Plan:** [plans/phase-06.md](../plans/phase-06.md) · Delivered in three PRs: **6a, chat sessions**, **6b, guardrails**, and 6c real models & the chat agent (added below when it merges).

## Part A — Chat sessions

**Completed:** 2026-10-17 · **Branch:** `feat/phase-06a-sessions` · **Tests:** 323 (309 at the end of phase 5) · **Branch coverage:** 95 % (CI floor 90 %)

### What we built

**Turns on a session thread.** A session is a LangGraph thread and a turn is a run (CR-001 D4).
- **The bug found by research, fixed first:** the executor resumed *any* existing checkpoint on a run's thread, so a second turn would have lost its user message. Every checkpoint is now stamped with the `run_id` that wrote it, and a run resumes only its own.
- **A new turn's input:**
  - Its user message, with a stable id (`user:<run_id>`). That message's position in the thread is the turn's baseline on every execution, including after a reclaim, with nothing extra stored.
  - Before it, a closing result for every tool call a previous turn left unanswered (a turn that failed mid-tools). Providers reject a conversation with dangling tool calls.

**Sessions** ([sessions/service.py](../../backend/src/agent_runtime/sessions/service.py), [sessions/store.py](../../backend/src/agent_runtime/sessions/store.py)).
- **Create, list, detail, rename, archive.**
- **Sending a turn** is one transaction: lock the session, check it is active and has no turn running, insert the run (`thread = session`), insert the `user` message. Then publish and enqueue after commit.
- **Errors:** an archived session or an active turn → `409`. Admission control (kill switch, backpressure) is reused from `RunService.admit()`.
- **Approve and cancel** forward to the active run and add an `approval` / `error` message in the same transaction.

**The transcript, written with the checkpoint** ([sessions/transcript.py](../../backend/src/agent_runtime/sessions/transcript.py)).
- **When:** inside each superstep's checkpoint transaction (the step outbox gets the checkpoint), `TranscriptWriter` maps this turn's new messages to rows:

  | Thread message | Transcript row |
  |---|---|
  | AI message with text | `assistant` |
  | Each tool call | `tool_call` |
  | Tool message | `tool_result`, with `cached` and `duration_ms` from the message's artifact |
  | System message from `session_start` | `system` |

- **Ids** are positional `sha256(run · node · index · type)`. Existing ids are skipped *before* a `seq` is allocated, so a re-produced superstep writes nothing and leaves no gap.
- **Ordering and fencing:** `seq` is allocated under the session's row lock, and the epoch fence applies (in code and by the trigger).
- **Other rows:** pauses write an `interrupt` row and failures/cancels an `error` row, in their own fenced transactions.

**The session stream** ([streaming/session.py](../../backend/src/agent_runtime/streaming/session.py)). The phase 3 algorithm (subscribe → replay → live → back-fill → poll) became a Template Method, `PersistedStream`.
- **`RunStream`** reads `run_events` from `run:{id}`.
- **`SessionStream`** reads `session_messages` from `session:{id}`, across all of a session's turns, from any replica, resuming with `Last-Event-ID`.

**Session and turn hooks** (CR-004 R15.5, R15.6).
- **`session_start`** runs in the middleware's `before_agent` node, behind a flag in the thread's state. It is checkpointed, so it never runs twice, even when the first turn is reclaimed.
- **`turn_start`** may add context or deny the turn (`failed(turn_denied)`). It fails closed.
- **`turn_end`** observes after the outcome is committed.
- **`session_end`** is a run of its own kind (lease, fencing, reclaim): it runs the hooks once and stores the summary.
- **Idle sessions** are archived by a sweep on every worker. That's safe concurrently: archiving is a conditional `UPDATE`.
- **Built-ins:** `session_clock` and `summarize_session`.

**API.**
- `/sessions` with messages, stream, approve and cancel; `/agents`.
- Problem types: `session-not-found`, `session-archived`, `turn-active` (with the active `run_id`), `no-active-turn`, `not-an-agent`.

**The `chat` agent definition.** It has `calculator`, `save_note`, and `notify` with approval, plus the session hooks. 6c adds search and sub-agents.

### How it fits

```
 POST /sessions/{id}/messages ── one txn: lock session · checks · INSERT run · INSERT user msg
     └── after COMMIT: publish message.created on session:{id} · enqueue the run
 worker ── run.thread_id = session_id ── resume only this run's checkpoints (metadata.run_id)
     new turn: [repairs…, user:<run_id>] → create_agent
     before_agent: session_start (once per session) · turn_start (context | deny)
     each superstep: FencedCheckpointer txn = checkpoint + step events + transcript rows
     pause → interrupt row · fail/cancel → error row · after commit: publish
 GET /sessions/{id}/stream (any replica): subscribe → replay session_messages → live → back-fill
 archive / idle → session_end run → hooks → summary
```

### Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | Session API | ✅ Create (with `agent`; a workflow → `422`, unknown → `404`), list (newest activity first), detail (active run, message count), rename, archive; archived → `409 session-archived` |
| SC2 | One active turn | ✅ A second message → `409 turn-active` with the active `run_id`; **20 concurrent sends → exactly one accepted**, one `user` row |
| SC3 | Transcript = checkpoint (R12.4) | ✅ After a 3-turn session with tools, every non-user row equals the projection of the checkpoint's messages (ids, types, contents, order) |
| SC4 | Deterministic and fenced | ✅ Re-committing a turn's messages writes nothing; `seq` is gap-free; a stale-epoch insert is rejected by the trigger |
| SC5 | **AC19: crash mid-turn** | ✅ `make demo-chat-crash`, **5/5**: SIGKILL during a tool call → completed on the other worker; one `run.reclaimed`; **zero duplicate messages**; the turn's transcript is whole; one note |
| SC6 | **AC18: multi-session** | ✅ `make demo-chat`, **5/5**: 3 sessions × 3 interleaved turns ran on **both workers**; every transcript complete and in order; turn 3 computed `n·7 + 1` from turn 1's result in every session; a stream on the **other API replica** got every message once, in order |
| SC7 | Session stream | ✅ Replay and live with `id: <seq>`; `Last-Event-ID: 3` → exactly 4, 5 |
| SC8 | HITL in chat | ✅ `interrupt` row; a message while waiting → `409`; approve with edits → `approval` row (with the edits) and the turn completes |
| SC9 | Cancel a turn | ✅ The turn ends `cancelled` with an `error` row; the session stays active; the next turn works |
| SC10 | **AC35: session hooks** | ✅ `session_start` exactly once even when the first turn's worker died mid-tool and was reclaimed; `turn_start` context and deny; `turn_end` saw `completed` and `failed(turn_denied)`; archiving runs `session_end` once and stores the summary; an idle session (past the TTL) is archived with one `session_end` |
| SC11 | Agents API, **AC33** | ✅ `GET /agents` (hooks, sub-agents), `GET /agents/{name}` (with the prompt), a workflow → `404`; `runtime agents validate` passes for all 4 shipped agents (its failure cases are the phase 1 loader tests) |
| — | Quality | ✅ 323 tests; coverage 95 %; **65/65 e2e runs** (13 scenarios × 5) |

### Concepts learned

- **The transcript is a projection, not a second source of truth.** Deriving it from the checkpoint's messages in the same transaction makes "they must agree" (R12.4) true by construction, and a test can check it by replaying the projection.
- **Identity must survive replay.** Random message ids (LangChain gives each execution new ones) can't deduplicate. Positional ids within the thread can, and so can a stable id on the turn's user message.
- **"Resume" needs an owner.** On a shared thread, "a checkpoint exists" no longer means "this run already started". Stamping checkpoints with the run that wrote them makes the question answerable.
- **Lifecycle hooks need durability too.** "Exactly once per session" is a flag in checkpointed state; "once when the session ends" is a run with a lease.

### Decisions & trade-offs

- **The `user` message is written by the API**, in the turn's transaction, and has no epoch. The agent's messages are written by the worker, fenced.
- **A turn's script for the scripted model starts at its own user message** (an offset from the thread's state), and its tool-call ids are unique across the session. Test-double details, but real providers give unique ids too.
- **Archiving allows an active turn to finish.** `session_end` is a separate run, not tied to the one-active-turn index.
- **Not yet:**
  - Token streaming and the partial reply on cancel (R12.7's second half) come with real models in 6c.
  - The context-window summary (R12.8, SHOULD) is in the backlog.

### Bugs found by testing (all fixed before merge)

- **The resume bug above** (found by the research probe, before any code was written).
- **The transcript projection swallowed later turns.** `transcript_of` mapped "everything after this turn's user message", which is right while a turn runs, but wrong for a full history, where it included the next turns too. Found by the R12.4 check; it now stops at the next turn's user message.
- **Repaired tool calls had no ids,** so they would never have reached the transcript. Found while writing the repair test, which was vacuous at first (its turn never left a dangling call) and now really fails a turn mid-tools.
- **The scripted model reused tool-call ids across turns** (`call_0_0` in every turn), so "is this call answered?" was ambiguous on a session thread. Ids are now unique across the session.

### Known issues & follow-ups

- **One unexplained test failure** (in one of 6 full coverage runs). **Identified in 6b:** `test_cancel_stops_a_subagent_between_steps` raced the sub-agent's start. Under coverage tracing, the cancel could land before the sub-agent's first step, which the runtime handles correctly but the test didn't expect. The test now orders the steps deterministically (see Part B).
- **No token streaming yet:** `run.status` / `token` transient events and the partial reply on cancel come with real models in 6c.

## Part B — Guardrails

**Completed:** 2026-10-17 · **Branch:** `feat/phase-06b-guardrails` · **Tests:** 344 (323 after 6a) · **Branch coverage:** 95 %

### What we built

**Soft → hard budgets** (R14.2).
- **Trigger:** before each model call, a main agent's budgets are compared with what's been used: model calls, tool calls, tokens and cost.
- **At 80 % of any budget,** that call is the **wrap-up turn**:
  - It goes out with **no tools** and a system note ("give your best final answer now").
  - Any tool call the model returns anyway is dropped.
  - The answer is stored (`output.budget_limited = true`, and `budget_limited` on the transcript's `assistant` row).
  - The run ends `failed(budget:<kind>)`.
- **At 100 %** the hard limits still refuse the call. Sub-agents get their wrap-up note as in phase 5.

**Tokens and cost** (R14.1).
- **Priced** per model from `MODEL_PRICES` (USD per million input / output tokens).
- **Counted with the step,** in the checkpoint's transaction, so a run's totals are exactly the sum of its committed steps, including across a reclaim (AC26).
- **Rolled up** to ancestors and the session.
- **Hard limits:** `max_tokens` / `max_cost_usd` (from the agent file, options and ceilings). A call is refused once a budget is used up.
- Model *calls* are still counted immediately: they are the runaway guard.

**Loop detection** (R14.4).
- **Repeats:** a call with the same tool and canonical arguments as an earlier one in the run is found through `tool_invocations.args_hash` (migration `0009`). The idempotency key can't be used: it includes the call's position.
  - The 2nd identical call is recorded and charged, but **served from the 1st's result** with a note.
  - The 3rd ends the run `loop_detected`.
  - Polling tools (`wait_subagents`, `subagent_status`, `report_progress`) are exempt.
- **No progress:** 5 identical model outputs in a row also end the run.

**Retries and the circuit breaker** (R14.7, [models/retry.py](../../backend/src/agent_runtime/models/retry.py)).
- **`ModelCaller`, a Decorator around one model call:**
  - Only retryable errors (429, 5xx, timeouts), at most 3 attempts.
  - Exponential backoff from 1 s, capped at 20 s, with full jitter; `Retry-After` is honoured.
  - **The budget is charged before every attempt.**
- **A circuit breaker per provider:** 5 failures in 30 s open it for 30 s, and a trial call half-opens it. While it's open, a run is **released** (`run.released {reason: circuit_open}`) and *not* re-sent at once. The outbox relay re-sends it once the message is stale, which is the backoff.

**Admission control** (R14.8).
- At most `SESSION_MESSAGES_PER_MINUTE` (10) user messages per session per minute, counted under the session lock.
- A global daily cost ceiling (`GLOBAL_DAILY_COST_USD`, over root runs, so roll-ups aren't counted twice). New work is refused; in-flight runs finish.
- Both are `429` problems with a `reason` (`rate_limited`, `daily_budget`, `queue_depth`).

**No secrets in the transcript** (R14.12). The model's tool-call arguments are recorded as it produced them, before any `pre_tool` hook ran, so the transcript writer redacts secret-looking strings itself (defence in depth).

### Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC12 | **AC26: runaway agent** | ✅ An agent calling tools forever, `max_tool_calls = 5`: 4 tool calls, then **one wrap-up call with 0 tools bound** (every earlier call had tools) and the note; the dropped tool call became "I had to stop early…"; `failed(budget:tool_calls)` with the stored `budget_limited` answer; **tokens and cost equal the sum of the thread's AI messages' usage**, also for a run killed mid-tool and reclaimed |
| SC13 | **AC27: loop** | ✅ 3 identical calls: executed once; the 2nd served from cache (`cached: true`, the earlier result + the note); the 3rd → `loop_detected` and never recorded. Polling `wait_subagents` 5× identically → `loop_detected`, and the sub-agent was cancelled with the run |
| SC14 | **AC28: ceilings** | ✅ `POST /runs` with `options.max_tool_calls: 1000` → `422 limit-above-ceiling` naming `options.max_tool_calls` and its maximum 100; `3` is honoured. A chat turn above the ceiling is refused the same way; `2` is honoured |
| SC15 | Retries | ✅ Fake-clock unit tests: backoff `1, 2` s at the top of the jitter range; jitter capped; `Retry-After` 7 s honoured and 99 s capped at 20; 400 fails at once; 3 attempts maximum; breaker opens after 5 in 30 s, failures outside the window don't count, half-open trial, re-open. Integration: two 503s then success → completed with **3 model calls charged**; a 400 → failed after 1 attempt; an open breaker → the next run is **released, not failed**, with 0 calls charged |
| SC16 | Admission control | ✅ The 3rd message within a minute at a limit of 2 → `rate_limited` (`Retry-After` 60); with today's spend at the ceiling → `daily_budget` |
| SC17 | **AC34: tool hooks in chat** | ✅ In a chat turn, the `pre_tool` redaction changed what executed (the note stored `key=[REDACTED]`); the secret appears in no transcript row (the phase 4 hook suite covers modify / deny / ask / fail-closed / cached redaction) |
| — | Quality | ✅ 344 tests; 8 new fake-clock unit tests; coverage 95 %; **65/65 e2e runs** (13 scenarios × 5) with the guardrails in place; CI keyless |

### Decisions & trade-offs

- **Tokens and cost commit with the step; model calls don't.** A step lost to a crash doesn't bill its tokens to the run (so the totals match the transcript), but it still counted as a model call (so a crash loop can't run forever).
- **The wrap-up turn is enforced on the response, not only the request.** A provider that ignores "no tools", like the scripted model, still can't act during wrap-up.
- **"No progress" = identical consecutive outputs.** In `create_agent`, a reply without tool calls ends the loop, so a run can only make no progress by repeating itself. Identical outputs capture exactly that.
- **The breaker's backoff is the relay's staleness window** (`RELAY_STALE_S`, 30 s), the same order as the 30 s open time. There's no new scheduler.

### Bugs found by testing

- **A secret the model put in tool-call arguments would have reached the transcript**: hooks clean the args *before execution*, but the transcript records the model's raw call. Fixed by redacting in the writer.
- **A test claimed more than it checked.** The runaway test's spy recorded "tools bound" as always true. It now records the real count from `bind_tools` (0 for the wrap-up call).
- **The flaky test from 6a, found.** With full logs kept, the next coverage run named it: `test_cancel_stops_a_subagent_between_steps`. The main agent cancelled right after spawning, which sometimes landed before the sub-agent's first step (cooperative cancel, correctly honoured), so no note was written. The test now waits 1 s first, so the cancel arrives during the sub-agent's slow first tool call. It asserts what the test is about: the first note exists, the second never does. 3/3 under coverage, and 2 full coverage runs clean (344/344).
- **AC28's exact case had no test.** `POST /runs` with `options.max_tool_calls` above the ceiling was only covered for `max_steps`. Added.
