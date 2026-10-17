# Phase 6 — Chat sessions + chat agent

**Plan:** [plans/phase-06.md](../plans/phase-06.md) · Delivered in three PRs: **6a, chat sessions** (this part), 6b guardrails, and 6c real models & the chat agent (added below as they merge).

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

- **One unexplained test failure.** One full coverage run (run right after the 5× e2e loop) had 1 failing test out of 323. pytest named it (`-ra`), but my log filter matched only the summary line, so the name was lost. **5 further full runs passed** (323/323 each). The flaky test is not identified yet. Full logs are kept from now on, so the next occurrence will name it.
- **No token streaming yet:** `run.status` / `token` transient events and the partial reply on cancel come with real models in 6c.
