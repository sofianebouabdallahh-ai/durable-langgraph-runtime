# ADR-0006 — Memory across chats: the runtime puts it in the prompt, scoped by the run

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-11-10 |
| **Related** | CR-004 R15.6, CR-002 T2, R14.15, R14.17, [phase H8 plan](../plans/phase-H8.md), [walkthrough of 2026-11-10](../progress/walkthrough-2026-11-10.md) |

## Context

Since H4, an agent can save notes (`save_note`) and read them back in any later chat
(`recall_notes`). The walkthrough showed the gap: the default local model (qwen2.5:7b)
rarely thinks of calling `recall_notes`. In 5 new chats, "What is my locker code?" was
answered 0 times, although the note was saved. Firmer instructions changed little.

The notes also had other problems:
- they found their agent through `runs` (`ON DELETE CASCADE`), so clearing old runs would
  erase memory;
- anything could be saved, a key included;
- nothing could remove a note.

## Decision

1. **The runtime puts memory in the prompt.**
   - **When:** at the start of every turn, for every agent or helper granted `save_note`,
     the runtime records which notes it holds (their keys, newest first) in the turn's
     state, a checkpointed snapshot.
   - **Where:** each model call reads those notes' text as it stands and puts it in the
     system message as a "What you remember" section. A note forgotten or deleted meanwhile,
     even earlier in the same turn, is gone at once, and no checkpoint keeps a note's text.
   - **Each note is one line**, shortened past 400 characters; a long one never hides the
     others.
   - **Budget:** up to 1,500 tokens (5% of a smaller window). The rest are counted, and
     `recall_notes` searches them.
2. **As data, never instructions.** The notes are one `<data source="memory">` block. A
   note a planted page made the model save comes back as information. Grants, approvals
   and the page-address check never depend on the prompt.
3. **The scope comes from the run row, in the database.**
   - `run_memory_scope(run)` gives the agent, and for a test chat or an eval turn the
     chat it keeps to.
   - A BEFORE INSERT trigger stamps every note with it, and every read uses the same
     function.
   - The helper (`author`) comes from the definition, never from the model's arguments.
4. **Forgetting is a fenced insert.**
   - **How:** `note_forgets` gets one row per forgotten note, written by the forgetting
     run under its own epoch.
   - **For the model:** `forget_note` is granted with `save_note`.
   - **For the person:** they restore a note (the row is deleted) or delete it for good.
5. **Notes outlive their runs:** `run_id` is `ON DELETE SET NULL`. A test's notes (a
   Studio test chat, an eval turn) still go with their run: they belong to the test.
6. **What may be kept is one Specification:**
   - **refused:** keys, tokens, private keys and card numbers, with a reason the model
     passes on;
   - **kept once:** the same note saved twice.

## Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **In the system message, per call, from a turn snapshot** (chosen) | The model can't miss it; deterministic within a turn (checkpointed); doesn't grow the thread; re-fitted when the window shrinks | Tokens on every call (bounded); the system prompt changes when memory does, which costs a provider's prompt cache | Chosen. The budget bounds the cost, and memory changes rarely |
| **Only on demand (`recall_notes`), with firmer instructions** | No tokens unless used | Measured: 0 of 5. A small model doesn't know it should look | Rejected: it's what failed |
| **A `session_start` hook adds the notes** (CR-004's `load_session_context`) | No runtime change | Hooks get only the session id and agent name, not the database; the text lands in the thread once per chat, so a note saved in another chat never shows in an open one | Rejected |
| **A SystemMessage added to the thread each turn** | Simple | Piles up turn after turn; compaction must keep or drop it; replays see stale copies | Rejected |
| **Retrieval by similarity (pgvector) per turn** | Scales to many notes | An embedding model and a call per turn; misses when the wording differs; more than a local install needs now | Later, with document search |
| **Soft-delete by updating `notes`** | One table | The epoch fence checks the note's own run, which may have been taken over: the update would be refused. An update also needs the worker to have UPDATE | Rejected for the insert-only `note_forgets` |
| **Scope computed in application code** | No SQL function | Three places (trigger, prompt, tools) to keep identical; a worker of the release before writes unscoped notes | Rejected |

## Consequences

- **Every turn of an agent with notes makes one more query and sends up to 1,500 more
  tokens.** Bounded, and the budget shrinks with a smaller window (H5's refit renders it
  again).
- **Rolling deploys work.** A worker of the release before inserts notes through the
  trigger, so they are scoped. It doesn't see `note_forgets`, so during a rollout it may
  still show a forgotten note to the model.
- **A downgrade to 0027 deletes notes whose run was deleted** (they have no run to belong
  to there) **and forgotten notes** (0027 would show them to the model again).
- **The snapshot is keys, not text:** one more primary-key query per model call, so a
  deletion takes effect on the very next call and a deleted note's text isn't kept in
  any chat's checkpoint.
- **Known limits:** two identical `save_note` calls in the same model step can both pass
  the duplicate check (a rare double, harmless); the memory index serves the agent prefix
  only (`author IS NOT DISTINCT FROM` can't use the rest), fine at a person's scale.
- **"Per user" means per install until accounts exist (P7).** The scope then gains the
  user, from verified identity.
- **Tests that count tokens, or find a note by its run, start from no notes** (the
  `no_memory` fixture). Memory is shared state by design.
