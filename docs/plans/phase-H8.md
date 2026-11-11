# Phase H8 plan — Memory across chats

**Goal:** what you asked an agent to remember is there in every later chat with it,
without the model having to think of looking. You can see what it remembers, and make it
forget.

**Why:**
- **The walkthrough of 2026-11-10** (`docs/progress/walkthrough-2026-11-10.md`). With the
  default local model, a note saved in one chat was rarely found in the next: "What is my
  locker code?" → "I don't have access to that". The note was in the database, but the
  model only sees notes when it calls `recall_notes`, and qwen2.5:7b seldom does.
- **The platform review's "make it competitive" list**, and L7's ranked list (#5: "long-term
  memory, per user, across chats, viewable and deletable").

| Gap | Today |
| --- | --- |
| Recall depends on the model | Notes reach the model only through `recall_notes`. Asking it to call that more firmly changed little. |
| No way to see or remove memory | Notes are only visible in a chat's tool cards. Nothing deletes one, and an agent told to "forget that" can't. |
| Memory is tied to runs | A note finds its agent through `runs` (`ON DELETE CASCADE`), so clearing old runs (the retention item) would erase memory. A test chat's notes are told apart by joining sessions and evals on every read. |
| Anything is stored | A key or a card number can be saved, and would then be sent to the model provider with every chat. |

**Requirements:** CR-004 R15.6 (session_start context, "e.g. memory"), CR-002 T2 (no
memory leaks across agents), R14.15 (untrusted text stays data), R14.17 (audit).

---

## 1. Research (2026-11-10)

- **Load memory at session start, deliberately and visibly** [AI Under Attack ch7; AI
  Agents: The Definitive Guide ch10; Build an AI Agent From Scratch ch6]. The same memory
  serves two ways: injected before each call, and fetched on demand by a tool. ChatGPT's
  and Claude's memories work this way: saved facts go in the system prompt, and the user
  can view and delete them.
- **Memory poisoning is its own threat** [DG ch10, AUA ch7]. Text a page planted and the
  model saved comes back later as if it were trusted. So:
  - memory reaches the model **as data**, never as instructions;
  - the harness, not the prompt, still enforces grants, approvals and the page-address
    check;
  - every write is validated;
  - the person can see and remove everything.
- **Validate before persisting** [DG ch10]: refuse secrets (API keys, private keys, card
  numbers), skip duplicates, keep the newest when facts disagree.
- **Scope by verified identity, never by what the model says** [DG ch10, AUA ch7]. The
  scope comes from the run row: the agent, the helper (`author`), and whether the run is a
  test. Nuria has no accounts yet, so "per user" means per install. Accounts add the user
  to the scope later.
- **Service layer** [DG ch10]: one implementation of memory, used by the tools, the prompt
  and the API, so the three can't drift apart.
- **Bounded:** inject the newest notes up to a token budget, and say how many more there
  are and how to search them [DG ch10: cap facts; BAA ch6: optimise well below the
  window].
- **Why not a session_start hook:** hooks get only the session id and the agent's name,
  and their text lands in the thread. Memory must be read from the database, scoped by the
  run row, current on every turn and kept out of the thread, so it is built into the
  runtime instead.

## 2. Design

### 2.1 Notes become memory rows (migration 0028)

- **`notes` gains its scope, fixed when the note is written:**
  - `agent` (text, not null): the run's agent;
  - `test_session` (uuid, null): set for a Studio test chat or an eval turn, which keep
    to their own chat (H6).

  Both are backfilled from `runs`, `sessions` and `eval_runs`. Reads no longer join
  `runs`.
- **`run_id` becomes nullable, `ON DELETE SET NULL`:** clearing a run keeps what it
  remembered. The epoch fence passes a null `run_id`.
- **Forgetting is an insert, not an update: `note_forgets`**
  (`note_key` PK → notes ON DELETE CASCADE, `run_id`, `epoch`, `forgotten_at`).
  - **Why:** the epoch fence fires on every update to `notes`. Once a note's run has
    been taken over, its epoch is old, so a later run that updated the note to forget it
    would be fenced.
  - **How:** a forget is one fenced insert by the run doing it, idempotent by its key
    (`ON CONFLICT DO NOTHING`), like `save_note`.
  - **Roles:** the worker keeps `SELECT, INSERT` only. The API gets `SELECT, DELETE` on
    `notes` and `SELECT, INSERT, DELETE` on `note_forgets`, for deleting a note and for
    restoring one.
- **Index** `(agent, author, created_at DESC)`, for the per-turn read.

### 2.2 One memory service (`agent_runtime/memory/`)

Pattern: **Service Layer** + **Value Object** (`MemoryScope`).

- `MemoryScope(agent, author, test_session)` is resolved from the run id, never from the
  model's arguments.
- **Operations:**
  - `save`: validates, then inserts;
  - `recent`: what the prompt shows;
  - `search`: what `recall_notes` uses;
  - `forget`: what the model can do;
  - for people, through the API: `list`, `delete`, `restore`, `delete_all`.
- **Validation on save** (a Specification):
  - **refused:** text matching the secret patterns `redaction.py` already masks, private
    keys, and 13–19-digit runs that pass Luhn (card numbers). The tool says why, so the
    model can tell the person;
  - **duplicates:** the same text (case and spacing ignored) already in the scope isn't
    saved twice. The existing note's id comes back with "already remembered".

### 2.3 Memory in every turn's prompt

- **When:** at the start of each turn, `abefore_agent` (a node, so its result is
  checkpointed) records which notes the scope holds, newest first, in the state
  (`RuntimeState.memory`: their keys; each model call reads their text as it stands, so
  a forgotten or deleted note is gone at once, and no checkpoint keeps a note's text).
  - **For whom:** every agent and helper granted `save_note`, the same grant as
    `recall_notes`. An agent without notes gets no memory: least privilege.
  - **Why checkpointed:** a turn taken over after a crash sees the memory it started
    with, and a note saved in another chat meanwhile appears on the next turn.
- **Where:** each model call's system message gets a **"What you remember"** section,
  built from that snapshot.
  - It goes before the data rule, so "Always use" skills stay last (H-finding: a small
    model follows what it reads last).
  - It is never written to the thread, so it doesn't pile up turn after turn, and
    compaction has nothing to keep.
- **How it reads:** the notes are one `<data source="memory">` block, newest first, each
  as `[id] date: text`. Before the block: "Things you saved in earlier chats with this
  person. Use them to answer; when two disagree, the newer one is right."
- **Bounded:** the newest notes up to `min(1,500 tokens, 5% of the context window)`.
  Beyond that it says "N older notes aren't shown: search them with recall_notes".

### 2.4 The model can forget: `forget_note`

- **The tool:** `forget_note(note_id)`, granted wherever `save_note` is.
  - Ids are the ones shown in memory and returned by `save_note`.
  - Only a note in the run's own scope can be forgotten: an id from another agent is
    "no such note", the same as an unknown one.
  - Risk class `write_internal`, no approval, idempotent, retried after a crash.
- **Forgotten notes leave memory and `recall_notes` at once.** The person can restore
  one, or delete it for good, from the agent's page. It is a quarantine before deletion
  [AUA ch7]: a page that tricks the agent into forgetting can't destroy anything.
- **The claim check (walkthrough fix) covers it:** "I've forgotten that" with no
  `forget_note` call is asked again, like `save_note`.

### 2.5 You can see and remove it

- **API** (audited, R14.17):
  - `GET /agents/{name}/memory`: notes and forgotten notes, with the chat each came from;
  - `DELETE /agents/{name}/memory/{id}`: delete one for good;
  - `POST /agents/{name}/memory/{id}/restore`;
  - `DELETE /agents/{name}/memory`: forget everything, confirmed in the UI.

  Test chats' notes are left out: they're the test's own.
- **UI:** a **"What it remembers"** panel on the agent's page, with:
  - each note, its date and a link to its chat;
  - Delete;
  - a **Forgotten** list with Restore;
  - **Forget everything**.

  A saved note's card links to the panel.

### 2.6 The chat agent's instructions (agent.md v6)

- **It is told:**
  - "What you remember" holds what was saved before: answer from it;
  - `recall_notes` searches beyond it;
  - when a fact changes, save the new one and forget the old;
  - when asked to forget something, call `forget_note`.
- **The eval case stays:** `keeps-a-note` saves and reads back in one turn. Memory is the
  snapshot taken when the turn starts, so the note it just saved is found with
  `recall_notes`, as before.

## 3. Tasks

1. Migration 0028 (scope columns, backfill, `note_forgets`, `SET NULL`, roles); the
   downgrade restores 0027.
2. `memory/` service, scope, validation; `save_note` and `recall_notes` use it.
3. `forget_note` tool, its grant, its card wording, the claim check.
4. The memory snapshot (`abefore_agent`) and the prompt section (`awrap_model_call`), with
   its budget.
5. API endpoints, audit entries, the OpenAPI types.
6. The "What it remembers" panel and card links.
7. `agent.md` v6.
8. Docs: README, `docs/design.md` patterns, ADR 0006 (memory), the CHANGELOG.

## 4. Success criteria

| # | Criterion | Measured by |
|---|---|---|
| 1 | **Recall in a new chat:** "What's my locker code?" after it was saved in another chat. **qwen2.5:7b, through the app, ≥ 4 of 5** (before: measured at the start of the phase) | Playwright, real model, 5 runs |
| 2 | **Forget:** "Forget my locker code" removes it from the next chat's memory, ≥ 4 of 5; deleting from the panel removes it from the very next turn | Playwright, real model; integration |
| 3 | **No leaks:** another agent, a helper, a test chat and an eval turn never see each other's memory, in the prompt, in `recall_notes`, or in the API | integration |
| 4 | **A secret isn't stored:** an API key or a card number is refused, and the model is told why | unit, integration |
| 5 | **Bounded:** with 500 notes, the memory section stays within its budget and names the count left out | unit |
| 6 | **Durable:** a turn taken over after a crash sees the memory it started with; a note saved meanwhile shows on the next turn | integration |
| 7 | **Retention-safe:** deleting a run keeps its notes; forgetting by a later run works after the note's run was taken over (the fence) | integration |
| 8 | **Upgrade:** notes from before 0028 keep their agent and test scope; downgrade and upgrade again work | migration test |
| 9 | **Quality:** the backend suite, ruff, mypy `--strict`, the UI checks, e2e `all` × 5, the container e2e, the browser suite (a new memory spec) | CI and locally |

## 5. Out of scope

- **Per-user memory:** waits for accounts. The scope's shape lets a user be added.
- **Memory shared across agents, and memory the agent writes without being asked**
  (automatic extraction): both widen what can be poisoned, and the second costs a model
  call per turn [DG ch10]. Later, if wanted.
- **Semantic search over notes** (pgvector): `recall_notes` stays a text search. That
  belongs with "search over your documents".
