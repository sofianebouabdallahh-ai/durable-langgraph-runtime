# Phase 6 plan — Chat sessions + chat agent

**Goal:** a user chats with an agent across many sessions. Every message is durably in the transcript, live on the session stream, and safe across crashes. The agent runs on a **real model** behind the same guardrails as the scripted one, and it can delegate to sub-agents.

**Done when:**
- **AC18:** multi-session, multi-turn, over 2 workers.
- **AC19:** a crash mid-turn → zero duplicate messages.
- **AC26–AC28:** runaway agent, loop, ceilings.
- **AC33–AC35:** definitions, tool hooks, session hooks.
- **AC37 / AC39:** parallel sub-agents and isolation in the chat agent (the sandbox part of AC39 is phase 7).
- **Plus** the success criteria below.

**Requirements:**
- Sessions: CR-001 R12.1–R12.10 (R12.11, the UI, is phase 11)
- Hooks and definitions: CR-004 R15.5, R15.6, R15.11
- Guardrails: CR-003 R14.2, R14.4, R14.7, R14.8
- Models and search: R3.1 `ModelProvider` (+ `embed()`, F3); R3.3 `SearchTool` (pulled forward from phase 8)
- The chat agent: CR-005 AC37 / AC39

**Delivered as three PRs on one plan.** The roadmap packs six subsystems into this phase; three PRs keep each one reviewable:

| PR | Branch | Content | ACs |
|---|---|---|---|
| **6a** | `feat/phase-06a-sessions` | Sessions, turns, transcript, session stream, HITL and cancel in chat, session hooks, `/agents` | AC18, AC19, AC33, AC35 |
| **6b** | `feat/phase-06b-guardrails` | Soft→hard wrap-up, loop detection, retries and circuit breaker, admission control, token and cost accounting | AC26, AC27, AC28, AC34 |
| **6c** | `feat/phase-06c-chat-agent` | Real `ModelProvider`s, token streaming, fixture `search`, the `chat` agent with `researcher` / `data-analyst` sub-agents, a live demo | AC37, AC39* |

The tag `phase-06` goes on the merge of 6c.

*Not in this phase:*
- `retrieve` + ingest (R4.5) stay in phase 8 with the research corpus. The chat agent gets them then; until then it has `search`, `save_note`, `calculator` and its sub-agents.
- The UI (R12.11) is phase 11.
- The context-window summary (R12.8, SHOULD) goes to the backlog unless real-model runs show a need.

---

## 1. Research findings

**Measured** (local experiment, langchain 1.4.2 / LangGraph 1.2.12, `create_agent` + scripted model + a spy checkpointer):

| Question | Finding | Consequence |
|---|---|---|
| A second `ainvoke` on the same thread with a new user message? | Messages accumulate: `[Human q1, AI, Tool, AI, Human q2, AI]`. The system prompt is **not** stored in state | Session = thread, turn = run (CR-001 D4) works with no new mechanism |
| Does `config["metadata"]` reach the checkpoint? | Yes: the latest checkpoint's metadata has the `run_id` we passed | **A bug to fix first:** today the executor treats *any* existing checkpoint as "resuming this run". For turn 2 that would drop the user's message. Resume iff the latest checkpoint's `run_id` is this run's |
| What does the checkpointer's `aput` receive? | Message objects in `channel_values["messages"]` | The transcript can be derived **inside the checkpoint transaction** (R12.3: "committed with the checkpoint") |
| Is a `ToolMessage.artifact` persisted? | Yes | The pipeline's `cached` / `duration_ms` reach the transcript's `tool_result` without a side channel |
| Message ids? | `lc_run--<uuid>` (random per execution) | Transcript ids must be positional, as R12.3 specifies: `sha256(run_id · node · message_index · type)` |
| The scripted model across turns | It picks its reply by the number of AI messages in the conversation, which keeps growing across turns | Each turn's script is indexed from that turn's own user message (an offset computed from the state) |

**From the code:**
- `sessions`, `session_messages` (deterministic `message_id UNIQUE`), `runs.session_id`, `runs.thread_id` and the one-active-run partial unique index all exist since phase 0.
- `sessions.agent_name/summary/ended_at` and the idle index exist since migration 0002.
- `StreamMerger` and the broker are generic (`session:` channels since phase 3). The stream session is run-specific, so it needs a pluggable replay source.

**Prior art:**
- The OpenAI Assistants API (threads + runs): one active run per thread → `409`, the same rule as R12.2.
- LangGraph Platform: `thread_id` + per-run streaming.
- Both keep the transcript as a projection of the agent state; we do the same, in one transaction.

## 2. Design

### 2a. Sessions & transcript (PR 6a)

```
 POST /sessions/{id}/messages ── ONE transaction ──────────────────────────────────┐
   session active? no active run? (partial unique index) · rate limit (6b)          │
   INSERT user message (seq = sessions.last_seq + 1) · INSERT run (thread = session)│
 └── after COMMIT: publish message.created, enqueue the run ────────────────────────┘
 worker: run.thread_id = session_id; new turn iff the latest checkpoint isn't this run's
   each superstep: FencedCheckpointer.aput ── same txn: TranscriptWriter
       diff the checkpoint's messages against what this run already transcribed
       → assistant / tool_call / tool_result rows, id = sha256(run · node · index · type)
       ON CONFLICT (message_id) DO NOTHING · seq from the session row · epoch-fenced
   pause → `interrupt` message · fail/cancel → `error` message · approve → `approval`
 GET /sessions/{id}/stream: the phase 3 algorithm over session_messages (Strategy: source)
```

Patterns:
- **Transcript as a projection, written in the checkpoint's transaction.** This is the Transactional Outbox again. The checkpoint (the agent's context) and the transcript (the user's view) can't disagree (R12.4).
- **Deterministic ids + `ON CONFLICT DO NOTHING`.** A reclaimed worker that re-produces a superstep writes nothing new (AC19).
- **The stream source is a Strategy.** One `StreamSession` drives both `run:{id}` (events) and `session:{id}` (messages + transient events).
- **Session hooks as durable work (R15.6):**
  - `session_start` runs in a middleware `before_agent` on the first turn. Its result is checkpointed, so it never runs twice, even across a reclaim.
  - `turn_start` / `turn_end` run around every run.
  - `session_end` is a run of kind `session_end` (lease, fencing, reclaim). The relay sweep also archives idle sessions and enqueues it.
- **Registry** for `/agents` (read-only).

### 2b. Guardrails (PR 6b)

- **Soft → hard (R14.2).** At 80 % of a model-call, tool-call, token or cost budget, the next model call gets **no tools** plus a wrap-up note. Its answer is marked `budget_limited`. At 100 %, `failed(budget:*)` as today.
- **Loop detection (R14.4).**
  - **Repeats:** the ledger already sees identical keys. The 2nd repeat returns the cached result plus a note, and the 3rd fails `loop_detected`.
  - **No progress:** 5 consecutive model calls with no tool call and no new message.
- **Retries (R14.7).** Retry/backoff as a Decorator around the model: 3 attempts, exponential from 1 s, capped at 20 s, full jitter, honouring `Retry-After`, and only for retryable errors. Every attempt is charged. A **circuit breaker** per provider (SHOULD): open after 5 failures in 30 s, for 30 s; waiting runs are released.
- **Admission control (R14.8).** At most 10 user messages per session per minute, and a global daily cost ceiling. Both return `429` (`reason=daily_budget` for the ceiling).
- **Accounting.** `usage_metadata` → tokens and cost (from a price table in settings), charged with roll-up, summed per session.

### 2c. Real models & the chat agent (PR 6c)

- **`ModelProvider` port** (R3.1): `chat(role) → BaseChatModel`, `embed(texts)`, `price(usage)`.
  - **Adapters:** OpenAI, and Ollama through its OpenAI-compatible API (one adapter, two base URLs), plus the scripted one.
  - **Selection:** `MODEL_PROVIDER`, with `MODEL_CHAT` / role models.
  - `RuntimeMiddleware` already swaps the model per call. That is the seam.
- **Token streaming.** Model tokens become transient `token` events on the session stream (pub/sub only). The assistant message is written once, when complete. A cancel mid-reply persists the partial text (`interrupted: true`, R12.7).
- **Fixture `SearchTool`** (R3.3): `fixtures/search/*.json`, normalised query with fuzzy fallback. It is deterministic and keyless.
- **`agents/chat`** with `researcher` (search) and `data-analyst` (calculator) sub-agents (CR-005), and `make demo-subagents`.
- **Live demo** (`make demo-chat-live`): opt-in, on **Ollama, local** (decided 2026-10-16: free and keyless; a tool-calling model such as `qwen2.5:7b`). The OpenAI adapter is built and contract-tested too. CI stays keyless.

## 3. Tasks

| # | Task | Verification |
|---|---|---|
| **6a** | | |
| 6.1 | Fix "resume vs. new turn" (checkpoint metadata `run_id`); per-turn script offset | Integration: a second turn on one thread gets its message |
| 6.2 | `SessionRepository` + `SessionService`: create/list/get/patch, send a turn (one transaction, `409`s), approve / cancel forwarding | Integration + API |
| 6.3 | `TranscriptWriter` in the checkpoint transaction; `interrupt` / `approval` / `error` messages; `ToolMessage.artifact` | Integration: transcript = checkpoint (R12.4); deterministic ids; fenced |
| 6.4 | Session stream (stream source as a Strategy), `message.created`, transient `run.status` | Integration: replay, live, Last-Event-ID, any replica |
| 6.5 | Session hooks (`session_start` / `turn_*` / `session_end`), `session_end` run kind, idle archiving; `/agents` API, `POST /sessions {agent}` | Integration: AC35 incl. a reclaim |
| 6.6 | E2E `chat-sessions` (AC18) and `chat-crash` (AC19); `make demo-chat`, `make demo-chat-crash`; PR 6a | e2e 5× |
| **6b** | | |
| 6.7 | Soft→hard wrap-up; token and cost accounting with roll-up | AC26 incl. a forced reclaim |
| 6.8 | Loop detection (repeat + no-progress) | AC27 |
| 6.9 | Retry Decorator + circuit breaker | Unit with a fake clock and a failing model |
| 6.10 | Admission control (per-session rate, daily cost); AC28 for sessions; PR 6b | API |
| **6c** | | |
| 6.11 | `ModelProvider` port + OpenAI-compatible adapter (OpenAI, Ollama) + `embed`; settings | Contract tests against a local fake server (recorded responses), no key |
| 6.12 | Token streaming → `token` events; partial reply on cancel | Integration with a streaming fake model |
| 6.13 | Fixture `SearchTool` + fixtures | Unit |
| 6.14 | `agents/chat` + `researcher` / `data-analyst`; `make demo-subagents` (AC37 scripted); `make demo-chat-live` (real model, opt-in) | e2e 5× (scripted); 1 live run recorded in the summary |
| 6.15 | Summary, docs, PR 6c | Coverage ≥ 90 % |

## 4. Success criteria

| # | Criterion | How | Pass when |
|---|---|---|---|
| **6a** | | | |
| SC1 | **Session API** (R12.10) | API | Create (with `agent`), list (paged, newest activity first), detail (active run, totals), rename, archive; an archived session → `409` on a new message |
| SC2 | **One active turn** (R12.2) | integration | A message while a turn is active → `409` with the active `run_id`; **20 concurrent sends → exactly one accepted** |
| SC3 | **Transcript = checkpoint** (R12.4) | integration | After a 3-turn session with tools, the checkpoint's messages map 1:1 (type, order, content) to `session_messages` |
| SC4 | **Deterministic and fenced** (R12.3) | integration | Re-committing a superstep writes nothing; a stale-epoch insert is rejected; `seq` is strictly increasing |
| SC5 | **AC19: crash mid-turn** | e2e (`make demo-chat-crash`) | SIGKILL during a tool call → completes on the other worker; exactly one `run.reclaimed`; **zero duplicate** messages |
| SC6 | **AC18: multi-session** | e2e (`make demo-chat`) | 3 sessions × 3 turns, interleaved over 2 workers (both used); every transcript complete and in order; turn 3 uses a value from turn 1's tool result (resolved from the conversation, proving the context carried) |
| SC7 | **Session stream** (R12.5) | integration + e2e | Every persisted message once, in order, with `id: <seq>`; Last-Event-ID resume; transient `run.status`; served by a replica that hosts nothing |
| SC8 | **HITL in chat** (R12.6) | integration | `interrupt` message; `POST /sessions/{id}/approve` → `approval` message and the turn resumes; a message while waiting → `409` |
| SC9 | **Cancel a turn** (R12.7) | integration | The session stays active; the turn ends `cancelled` with an `error` message; the next turn works |
| SC10 | **AC35: session hooks** | integration (incl. a reclaim) | `session_start` exactly once per session, even when the first turn is reclaimed; `turn_start` / `turn_end` per turn; archive → one `session_end` run, summary stored; idle past the TTL → archived with the same `session_end` |
| SC11 | **Agents API** (R15.11), **AC33** | API + CLI | `GET /agents`, `GET /agents/{name}`; `runtime agents validate` passes for all shipped agents and fails each listed misconfiguration naming file and field |
| **6b** | | | |
| SC12 | **AC26: runaway agent** | integration (incl. a forced reclaim) | A scripted agent calling tools forever: at 80 % one wrap-up call with no tools; ends `failed(budget:tool_calls)` with a `budget_limited` answer; tokens and cost equal the sum of its steps |
| SC13 | **AC27: loop** | integration | 2nd identical call → cached result + note; 3rd → `loop_detected`; 5 no-progress model calls → `loop_detected` |
| SC14 | **AC28: ceilings** | API | Above the ceiling → `422` (runs and session messages); a lower value is honoured |
| SC15 | **Retries** (R14.7) | unit (fake clock) | 429 / 5xx / timeout retried ≤ 3 times with capped full-jitter backoff and `Retry-After`; 400 / auth fail at once; every attempt charged; the breaker opens after 5 failures / 30 s and half-opens after 30 s |
| SC16 | **Admission control** (R14.8) | API | 11th message in a minute → `429`; daily cost ceiling → `429 reason=daily_budget`; in-flight turns finish |
| SC17 | **AC34: tool hooks** | integration | The phase 4 hook tests, re-run inside a chat session |
| **6c** | | | |
| SC18 | **Model providers** (R3.1) | contract (fake HTTP server) | The same suite passes for the OpenAI and Ollama base URLs: tool calls, usage, streaming, `embed`; no key in CI |
| SC19 | **Token streaming** | integration | `token` events reach the session stream and are never persisted; one `assistant` message per reply; a cancel mid-reply stores the partial text with `interrupted: true` |
| SC20 | **Fixture search** (R3.3) | unit | Exact and fuzzy matches; deterministic; unknown query → empty result |
| SC21 | **AC37: parallel sub-agents in chat** | e2e (scripted) | The chat agent spawns `researcher` and `data-analyst` in one turn; both run concurrently in the same worker; `subagent.progress` arrives on the session stream while they run; the final answer uses both results |
| SC22 | **AC39** (without sandboxes) | integration | The sub-agent's first model call = its prompt + the task; a chat-agent tool it lacks → denied |
| SC23 | **Live** | `make demo-chat-live` (manual) | A 2-turn chat on a real model completes; turn 2 uses turn 1's context; tool calls go through the pipeline; the transcript and the cost are recorded in the summary |
| SC24 | **Quality** | CI | All jobs green, including e2e; coverage ≥ 90 %; each new e2e scenario 5× in a row locally; CI needs no API key |

## 5. Risks

| Risk | Mitigation |
|---|---|
| The transcript diverges from the checkpoint | Same transaction, derived from the same messages; SC3 checks it after every scenario |
| Real models are non-deterministic | Every guarantee is tested with the scripted model; the live run is a demo, not a gate |
| Token-event volume on Pub/Sub | Transient, coalesced (≥ 20 ms batches), never persisted |
| Provider differences (OpenAI vs Ollama tool calling) | One OpenAI-compatible adapter; a contract suite for both base URLs |
| Scope | Three PRs; each starts only after the previous one merges |
