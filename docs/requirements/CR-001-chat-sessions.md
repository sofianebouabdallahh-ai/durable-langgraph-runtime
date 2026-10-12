# CR-001 — Chat sessions

| | |
|---|---|
| **Status** | Accepted (2026-10-11) |
| **Date** | 2026-10-11 |
| **Base document** | `Project_4_Detailed_Requirements_K8s.pdf` (v1.0 + Kubernetes) |
| **Scope** | New §12 Sessions; amendments to §1, §2, §3, §5, §6, §8, §9, §11; three spec fixes |

## 1. Motivation

The base spec models one-shot **runs**: one input, one graph execution, one answer. We want users to **chat** with an agent:

- A conversation is a **session** with its own id, and it holds many turns.
- Every message in the session is stored: user and assistant messages, tool calls, tool results, interrupts and approvals.
- A user can open many sessions, and each one runs in the same durable runtime (the "harness").
- The chat UI receives events from the harness in real time.

The runtime keeps all its guarantees (checkpointing, leases, fencing, reclaim and graceful hand-off), and sessions inherit them. A worker crash in the middle of a turn must not lose a message or duplicate one.

## 2. Decisions

### D1 — Agent framework: keep LangGraph *(accepted)*

Considered: LangGraph 1.x vs. GitHub Copilot SDK.

| | LangGraph | GitHub Copilot SDK |
|---|---|---|
| Where the agent loop runs | In our worker process, step by step | Inside the Copilot CLI (a separate process the SDK talks to over JSON-RPC) |
| Checkpoint after every step in *our* Postgres | Yes, via the Postgres checkpointer (R1.2) | No. The CLI owns the loop and session state |
| Fencing writes with `epoch` (R2.3) | Possible, by wrapping the checkpointer | Not possible: the writes happen inside the CLI |
| Resume on another pod after a crash (R2.4) | Yes, from the last checkpoint | Not under our control |
| Model choice | Any provider via `ModelProvider` (OpenAI, Ollama) | Copilot models; needs a Copilot subscription and an authenticated CLI |
| Learning value for this project | High: we build the durability ourselves | Low: it *is* a finished harness, which hides what we want to learn |

**Decision:** keep LangGraph. The project's goal is to build the durable, distributed harness ourselves. The Copilot SDK already is a harness, with its own loop and session store, so adopting it would replace exactly the parts this project exists to teach. It is added to the roadmap as an optional *external agent adapter* (a graph node that delegates to a Copilot session), not as the core.

### D2 — Message storage: Postgres (JSONB), not a separate NoSQL database *(accepted)*

**Decision:** store sessions and messages in Postgres, with a `JSONB` column for each message's type-specific content.

**Why:**

1. **Fencing needs one transaction.** A message written by a zombie worker must be rejected exactly like its checkpoint (R2.3). That only works if the epoch check and the message insert happen in the **same transaction** as the checkpoint. A second database would turn every turn into a dual write: if one database commits and the other doesn't, messages are lost or duplicated.
2. **The base spec's rule is "Postgres is the only source of truth"** (§2). A second source of truth weakens every guarantee in §2.
3. **JSONB gives the flexibility of a document store.** Each message type (`user`, `tool_call`, `tool_result`, …) has a different shape. JSONB stores each shape as-is and can still be indexed and queried.

**If you still want to learn a NoSQL database,** the correct pattern is a *read model*. Postgres stays the source of truth, and a transactional **outbox** projects messages into MongoDB/DynamoDB for search or analytics. That is a good distributed-systems lesson (outbox, eventual consistency, idempotent consumers), so it is on the roadmap (§10 of this CR) rather than in v1.0.

### D3 — Transport: SSE for server → client, HTTP POST for client → server *(accepted)*

| | SSE | WebSocket |
|---|---|---|
| Direction | Server → client (client sends with normal `POST`) | Both ways |
| Resume after disconnect | Built in: `id:` field + `Last-Event-ID` header, which maps 1:1 to our `seq` | Hand-rolled (`{after_seq}` message) |
| Through Ingress / proxies | Plain HTTP; only needs buffering off | Upgrade handshake, longer timeouts |
| Chat fit | A chat turn is "POST a message, then watch the reply stream", which is exactly SSE | Bidirectional power we don't need |

**Decision:** SSE is the primary transport for both the session stream and the run stream. The UI uses a fetch-based SSE client (not the browser's `EventSource`, which cannot send auth headers) and resumes with `Last-Event-ID`. `WS /ws/runs/{id}` drops from MUST to **SHOULD**.

### D4 — Session = LangGraph thread; turn = run *(follows from D1)*

LangGraph already has this concept: a **thread** holds conversation state across invocations, and messages accumulate in state through the `add_messages` reducer. So:

- `thread_id = session_id` for chat runs. The checkpointer keeps the agent's full context across turns.
- Each user message starts a **new run** on that thread. Every run-level guarantee (lease, fencing, reclaim, cancel, limits) therefore applies per turn with no new mechanism.

```
Session (thread_id = session_id)
 ├── message seq 1  user          "Compare Redis Streams and Kafka"
 ├── run A (turn 1) ───────────────────────────────┐ lease, epoch, events
 │    ├── message seq 2  tool_call    search(...)   │
 │    ├── message seq 3  tool_result  [...]         │
 │    └── message seq 4  assistant    "Redis ..."   ┘
 ├── message seq 5  user          "Which one for us?"
 └── run B (turn 2) ...
```

## 3. New section — §12 Sessions

### R12.1 Session identity & lifecycle — MUST
Each session has a UUIDv7 `session_id`, a `graph_name` fixed at creation, an optional `title`, a `status` (`active | archived`), `created_at` and `last_activity_at`. Archiving is a soft delete: the transcript is kept, and no new turns are accepted (`409`). There is no authentication in v1.0 (see §10); every session is visible to every client.

### R12.2 Turns — MUST
`POST /sessions/{id}/messages {content, options?}` does three things in **one transaction**: it inserts the `user` message, creates a run with `session_id` set and `thread_id = session_id`, and records the run for enqueueing. The response is `202 {message_id, run_id}`.
**At most one non-terminal run per session**, enforced by a partial unique index on `runs(session_id) WHERE status NOT IN (completed, failed, cancelled)`. A message sent while a turn is active returns `409` with the active `run_id`. Backpressure (R2.9) applies: `429` when the queue is over threshold.

### R12.3 Message transcript — MUST
Table `session_messages`. Message types and their `content` shapes:

| `type` | `role` | `content` (JSONB) |
|---|---|---|
| `user` | user | `{text}` |
| `assistant` | assistant | `{text, model, tokens, cost}` |
| `tool_call` | assistant | `{tool_call_id, tool, args}` |
| `tool_result` | tool | `{tool_call_id, tool, result \| error, duration_ms, cached}` |
| `interrupt` | system | `{interrupt_type, payload}` |
| `approval` | user | `{decision, edits?, reason?}` |
| `error` | system | `{reason, detail}` — the turn failed (`timeout`, `step_limit`, `max_reclaims`, …) |

Rules:
- **Append-only.** Messages are never edited. `seq` is strictly increasing per session.
- **Deterministic ids.** `message_id = sha256(run_id · node · message_index · type)`. The insert uses `ON CONFLICT (message_id) DO NOTHING`, so a reclaimed worker re-producing the same superstep writes nothing new. This is the same idea as R2.6.
- **Fenced.** Every insert carries the worker's `epoch`, and an insert with an epoch below the run's current epoch is rejected (R2.3).
- **Committed with the checkpoint.** The messages produced by a superstep are committed in the same transaction as that superstep's checkpoint. The epoch-aware checkpointer wrapper (see Fix F1) does both.
- **Tokens are not messages.** Streaming deltas are published as `token` events (pub/sub only, as in R1.5). The `assistant` message is written once, when complete.

### R12.4 Transcript vs. checkpoint — MUST
The **checkpoint** is the source of truth for the *agent's* context (what the model sees next turn). `session_messages` is the source of truth for the *user-facing* transcript. They are written together (R12.3) and must agree. A unit test replays a session's checkpoints and checks that their messages match the transcript.

### R12.5 Session stream — MUST
`GET /sessions/{id}/stream` (SSE) streams everything for the session across all of its turns:
- **Persisted messages,** sent with `id: <seq>`. They can be replayed: on connect, the server reads `Last-Event-ID` (or `?after_seq=`) and replays the messages after it.
- **Transient events,** sent without `id:`. These are `token`, `node.started` / `node.completed` and `run.status` for the active turn. They are not replayed.

Workers publish to the Redis channel `session:{session_id}` after committing. The serving API replica follows the R2.5 algorithm: subscribe first, then replay, then relay live events with dedup by `seq` and back-fill of gaps from Postgres. Any replica can serve any session. The stream sends a heartbeat comment every 15 s and a `reconnect` event on graceful API shutdown (R10.7).

### R12.6 HITL inside a chat — MUST
When a turn's graph calls `interrupt()`, R1.4 applies unchanged. In addition, an `interrupt` message is appended to the transcript. `POST /sessions/{id}/approve` forwards to the active run's approve (R1.4) and appends an `approval` message. A new user message while the turn is `waiting_approval` returns `409`.

### R12.7 Cancel a turn — MUST
`POST /sessions/{id}/cancel` cancels the active run cooperatively (R1.6). The session itself stays `active`. If tokens were already streamed for an unfinished assistant reply, the partial text is persisted as an `assistant` message with `content.interrupted = true`.

### R12.8 Context window — SHOULD
When the thread's messages exceed a configurable token budget (`SESSION_CONTEXT_TOKENS`), older messages are summarised into a `system` message in state before the model call. The transcript is not changed; only the agent's context is.

### R12.9 Chat agent — `examples/chat` — MUST
A `create_agent` graph with the tools `search`, `retrieve` and `save_note`. `save_note` is the side-effecting tool, used to exercise R2.6 in a chat. Tools go through the registry (R3.4), so they get policy, idempotency, tracing and transcript writes automatically. Uses `MODEL_CHAT`.
**SHOULD:** a `deep_research(question)` tool that starts the research graph (§4) as a **child run** (R2.8). The chat turn waits in `waiting_children`, and the research plan approval appears in the chat as an `interrupt` message.

### R12.10 Session API — MUST

| Endpoint | Purpose | Notes |
|---|---|---|
| `POST /sessions` | Create | `{graph, title?}` → `{session_id}` |
| `GET /sessions` | List | Paged, newest activity first; `?status=` |
| `GET /sessions/{id}` | Detail | Status, title, active `run_id` and its status, totals (tokens, cost) |
| `PATCH /sessions/{id}` | Rename / archive | `{title?, status?}` |
| `GET /sessions/{id}/messages?after_seq=` | Transcript page | For the initial load and catch-up |
| `POST /sessions/{id}/messages` | Send a turn | R12.2; `409` if a turn is active |
| `GET /sessions/{id}/stream` | SSE | R12.5 |
| `POST /sessions/{id}/approve` | HITL | R12.6 |
| `POST /sessions/{id}/cancel` | Cancel turn | R12.7 |

### R12.11 Chat UI — MUST
- A sidebar listing sessions, a "New chat" button, rename and archive.
- A chat view: user and assistant bubbles (markdown); tool calls rendered as collapsible cards that pair each `tool_call` with its `tool_result` (args, result, duration, `cached` badge); interrupts rendered as an inline approval card.
- Streaming tokens, a "stop" button (R12.7), and an input that is disabled while a turn is active.
- State is rebuilt from `GET /sessions/{id}/messages` after a refresh. The SSE hook reconnects automatically with `Last-Event-ID`.
- A pure reducer `messages + events → chatState`, unit-tested with Vitest. Same engineering standard as R6.5.
- **SHOULD:** a side panel with the active turn's live graph view (R6.1).

## 4. Amendments to existing requirements

| Req | Change |
|---|---|
| **R1.1** | A run gains an optional `session_id`. Runs without one (standalone research runs, child runs) behave exactly as before. |
| **R1.2** | `thread_id = session_id` for session runs; `thread_id = run_id` for standalone and child runs. |
| **R1.5** | Adds event types `message.created` and `run.status`. `run.status` is transient (pub/sub only) and drives the chat UI's "thinking / tool / waiting" indicator. |
| **R2.5** | Generalised: the same subscribe → replay → dedup → back-fill algorithm serves both `run:{id}` and `session:{id}` channels. Implement it once and reuse it. |
| **R3.1** | Adds `MODEL_CHAT`. Adds `embed(texts) → list[vector]` to `ModelProvider` (Fix F3). |
| **R3.4** | The tool wrapper also appends `tool_call` and `tool_result` messages when the run belongs to a session. |
| **§5 API** | Adds the session endpoints (R12.10). `GET /runs/{id}/stream` honours `Last-Event-ID`. `WS /ws/runs/{id}` drops from MUST to **SHOULD** (D3). |
| **R6.1** | "WebSocket hook with automatic reconnect" becomes "**SSE** hook with automatic reconnect via `Last-Event-ID`". |
| **R6.4** | The start form becomes optional; "New chat" (R12.11) is the main entry point. |
| **R7.2** | Adds the metrics: active sessions, turns by status, turn latency (user message → final assistant message), and transcript writes rejected by fencing. |
| **R7.3** | Adds **≥ 5 multi-turn chat cases** (`evals/cases/chat/*.yaml`), where turn 2 refers to turn 1, to check that context carries over. |
| **R10.3** | Ingress: SSE buffering off for `/api/sessions/*/stream` too. The WebSocket annotations stay only while the SHOULD WS endpoint exists. |

## 5. Spec fixes (gaps found in the base document)

| # | Gap | Fix |
|---|---|---|
| **F1** | The LangGraph Postgres checkpointer doesn't know about `epoch`, so R2.3's promise to fence "checkpoint metadata" has no mechanism. | **New R2.10 (MUST): epoch-aware checkpointer.** Wrap the Postgres checkpointer so that each `put` / `put_writes` runs in a transaction that first checks the run's current epoch, then writes the checkpoint and that superstep's transcript messages (R12.3). A stale epoch raises `FencedError`, and the worker abandons the run without acknowledging it. This is prototyped first, because everything else builds on it. |
| **F2** | Two recovery paths can race: the reaper (R2.4) and `XAUTOCLAIM` (R2.1). | **Amend R2.4:** whichever path finds the run first, the lease acquisition `UPDATE` (R2.3) is the only arbiter, and the loser treats its claim as a no-op and acknowledges its message. Covered by a unit test that races both paths. |
| **F3** | `runs` lacks columns that R1.3, R1.6 and R1.7 need. Embeddings (R4.5) have no provider. R1.3 mentions "explicitly paused", but no pause endpoint exists. | Add `runs.session_id`, `runs.cancel_requested`, `runs.reason` and `runs.thread_id`. Add `embed()` to R3.1 (Ollama: `nomic-embed-text`; OpenAI: `text-embedding-3-small`). R1.3: replace "explicitly paused" with "gracefully released"; a pause endpoint goes on the roadmap. |

## 6. Storage additions (§9)

| Table | Key columns |
|---|---|
| `sessions` | `id` PK, `graph_name`, `title`, `status`, `last_seq`, `created_at`, `last_activity_at`, `tokens`, `cost` |
| `session_messages` | `session_id`, `seq`, `message_id` UNIQUE, `run_id`, `epoch`, `type`, `role`, `content` JSONB, `created_at`. PK `(session_id, seq)` |
| `runs` (amended) | adds `session_id` FK nullable, `thread_id`, `cancel_requested`, `reason`. Partial unique index for one active run per session (R12.2) |

`seq` is assigned with `UPDATE sessions SET last_seq = last_seq + 1 … RETURNING last_seq` inside the same transaction as the insert. A row lock on the session serialises writers, which is cheap because only one turn per session is active at a time.

## 7. Test additions (§8)

**Unit:** a second turn is rejected while one is active; a re-inserted message with the same `message_id` is a no-op; a stale-epoch message insert is rejected; checkpoint messages match the transcript (R12.4); the session reducer works from recorded event logs; the reaper and `XAUTOCLAIM` race (F2).

**Integration (Compose):** `SIGKILL` the worker in the middle of a turn → the turn completes elsewhere, and the transcript has no duplicate `tool_call`, `tool_result` or `assistant` rows. Two sessions chat at the same time and their turns land on different workers. An SSE client on the non-hosting replica receives every persisted message in order.

## 8. New acceptance criteria (§11)

- **AC18 · Multi-session.** Three sessions are created and each gets 3 turns, interleaved across 2 workers. Every transcript is complete and in order, and turn 3 of each session correctly refers to turn 1 of that session.
- **AC19 · Crash mid-turn.** `make demo-chat-crash`: the owning worker is `SIGKILL`ed during a tool call. The turn completes on the other worker, there is exactly one `run.reclaimed`, and the transcript has zero duplicate messages.
- **AC20 · Resume the conversation.** Refresh the page and kill the API replica serving the stream in the middle of a reply. The UI reconnects to another replica with `Last-Event-ID`, and the transcript is identical to a run with no disruption.
- **AC21 · K8s.** `make k8s-demo-podkill` and `make k8s-demo-upgrade` also pass for an active chat turn.

## 9. Impact on the phase plan

Sessions are built on phases 1–5 (durable runs, workers, streaming, tools, HITL). The chat agent is simpler than the research agent and gives an interactive demo sooner, so it goes **first**:

| # | Phase | Change |
|---|---|---|
| 0 | Foundations | The schema includes `sessions` and `session_messages` from the start |
| 1–2 | Durable runs, distributed workers | **F1 (epoch-aware checkpointer) is prototyped first in phase 1**; F2 is handled in phase 2 |
| 3 | Streaming | Stream code is generic over run and session channels; SSE `Last-Event-ID` |
| 4–5 | Tools & HITL, sub-runs | The tool wrapper writes transcript messages |
| **6** | **Chat sessions + chat agent (new)** | R12.1–R12.10, AC18, AC19 |
| 7 | Research agent | Was phase 6; `deep_research` tool (SHOULD) |
| 8–10 | Observability, evals, UI | UI adds the chat view (R12.11), AC20 |
| 11–12 | Kubernetes, release | AC21 |

Estimated additional effort: **~15–20 focused hours**.

## 10. Out of scope / roadmap

- Authentication and multi-user ownership of sessions (`user_id` on `sessions`)
- Editing a message or branching a conversation (LangGraph supports forking a thread from a checkpoint)
- Queueing a second message while a turn is active, instead of returning `409`
- A NoSQL read model via a transactional outbox (D2)
- An external agent adapter: a graph node that delegates to a GitHub Copilot SDK session (D1)
- A pause endpoint (F3)
