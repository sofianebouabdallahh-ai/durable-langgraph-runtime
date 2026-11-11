# Phase H8 — Memory across chats

**Completed:** 2026-11-10 · **Branch:** `feat/h8-memory` (on `fix/walkthrough-gaps`) · **Plan:** [plans/phase-H8.md](../plans/phase-H8.md) · **Decision:** [ADR-0006](../adr/0006-memory-across-chats.md) · **Tests:** backend 991 (+56 since the walkthrough) · UI unit 85 · browser 62

Found by the walkthrough of 2026-11-10. An agent could save notes and read them back in a later chat, but only if the model thought of calling `recall_notes`, and the default local model rarely did. In 5 new chats, "What is my locker code?" got 0 right answers, although the note was saved. On top of that:
- nothing could see or remove a note;
- clearing old runs would have erased memory;
- anything could be saved, a key included.

## What we built

**Memory in every chat** (`memory/`, `tools/middleware.py`).
- **When a turn starts,** an agent or helper that can save notes gets a snapshot of the notes it holds, newest first. The snapshot is checkpointed with the turn: a turn taken over after a crash shows the same notes.
- **Every model call** reads those notes' text as it stands and puts it in the system message, under "What you remember".
  - A note forgotten or deleted in the meantime, even earlier in the same turn, is gone at once.
  - The snapshot holds the notes' keys only, so no checkpoint keeps a note's text.
- **As data:** the notes are one `<data source="memory">` block, never instructions. Each note is one line, so a planted note can't pass for several newer ones. Grants, approvals and the page-address check don't depend on the prompt.
- **Bounded:**
  - up to 1,500 tokens, or 5% of a smaller window;
  - set again for each call, so when a provider states a smaller window mid-turn, memory shrinks with it;
  - a long note is shortened, and never hides the others;
  - the rest are counted, and `recall_notes` searches them.

**The scope comes from the run, never the model** (migration 0028).
- **One rule:** `run_memory_scope(run)` gives a note's scope: the agent, and for a Studio test chat or an eval turn, the chat it keeps to. The helper (`author`) comes from the definition.
- **Stamped by the database:** a BEFORE INSERT trigger sets the scope on every note, so a worker of the release before writes scoped notes too. Every read uses the same function.
- **Notes outlive their runs** (`ON DELETE SET NULL`). A test's notes still go with their run.

**The agent can forget** (`forget_note`, granted with `save_note`).
- **An insert, not an update:** forgetting adds a row to `note_forgets`, fenced by the forgetting run's own epoch. An update of the note would be refused once the note's own run had been leased again.
- **Undoable:** the person can restore a forgotten note.
- **The claim check covers it:** "I've forgotten that" with no such call is asked again, like "I've saved it". It is tied to remembered things ("my locker code", "that note"), so "forget the onions" never makes it forget a note.

**What isn't kept** (`memory/rules.py`).
- **Refused, with a reason the model passes on:** keys, tokens, private keys, card numbers (Luhn-checked) and text a hook already masked.
- **Kept once:** the same note saved twice.

**Yours to see and remove.**
- **The page:** "What it remembers" on the agent's page (`#/agents/<name>/memory`). It shows each note with its date and its chat. You can:
  - delete a note for good (after confirming);
  - restore one it was asked to forget;
  - forget everything.
- **From a chat:** a note's card links there. A Studio test chat's cards don't, since its notes are the test's own.
- **API and audit:** `GET`/`DELETE /agents/{name}/memory`, `DELETE …/{id}`, `POST …/{id}/restore`. The audit trail records the note's id only, so a deleted note's text doesn't live on there.

**It points out notes about the same thing.** `save_note` lists older notes that look like the same thing (a fact that changed), and `forget_note` lists the ones it left. Both tell the model to forget them now.

**The chat agent's instructions** (version 6): answer from "What you remember"; when a fact changes, save the new one and forget the old one.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | Recall in a new chat ≥ 4 of 5 (qwen2.5:7b, through the app) | ✅ **5 of 5** for each of three facts, 15 of 15 (before: 0 of 5) |
| 2 | Forget removes it from the next chat's memory ≥ 4 of 5; deleting from the page removes it at once | ✅ **5 of 5** saved, then forgotten; the page: `test_a_person_sees_restores_deletes_and_clears_memory` and the browser spec |
| 3 | No leaks between agents, helpers, test chats and evals | ✅ `test_another_agent_does_not_see_it`, `test_a_tests_notes_stay_in_the_test`, `test_a_helper_remembers_its_own_notes_and_only_it`, `test_forgetting_another_agents_note_finds_nothing` |
| 4 | Secrets and card numbers aren't kept, and the model is told why | ✅ unit (keys, AWS, private keys, cards incl. 2-series, masked text; "risk-management…" kept) and `test_a_card_number_is_not_kept_and_the_model_is_told_why` |
| 5 | Bounded with 500 notes; the count left out is named | ✅ `test_memory_stays_within_its_budget_and_counts_the_rest`; a long note: `test_a_long_note_is_shortened_and_never_hides_the_others` |
| 6 | A turn taken over after a crash shows what it started with; a note saved meanwhile shows next turn | ✅ `test_the_snapshot_is_checkpointed_with_the_turn`, `test_memory_is_the_turns_snapshot_and_the_next_turn_sees_what_it_saved` |
| 7 | Deleting a run keeps its notes; forgetting works after the note's run was taken over | ✅ `test_deleting_a_run_keeps_what_it_remembered`, `test_forgetting_works_after_the_notes_run_was_taken_over` |
| 8 | Notes from before 0028 keep their scope; downgrade and upgrade work | ✅ `test_notes_from_before_memory_keep_their_agent_and_test_scope`, with notes whose run was leased again since |
| 9 | Quality bar | ✅ backend 991 passed, 3 skipped · e2e `all` × 5 75/75 · container e2e 8/8 · browser 62 passed, 1 skipped · UI lint, types, 85 tests, build · ruff, mypy `--strict` |

**Real model, through the app** (qwen2.5:7b on Ollama, the `fresh` install):

| | Before H8 | H8, before the review | H8, final |
|---|---|---|---|
| "What is my locker code?" in a new chat | 0 of 5 | 5 of 5 | **5 of 5** |
| "What is the budget?" | not measured | 5 of 5 | **5 of 5** |
| "When is the demo?" | 3 of 5, two of them from web search, not the note | 5 of 5 | **5 of 5** |
| "Remember…", then "Forget my gym locker number" in a new chat | — | 5 saved, 5 forgotten | **5 saved, 5 forgotten** |
| A fact that changes ("…it is now 11"), then "Forget my bike lock code" | — | — | **0 of 2**: both times the old note stayed, and "forget" took one of the two (see below) |

**Not yet solved: a fact that changes.**
- **What happened (2 runs):** the model saved the new bike lock code and kept the old one. Asked to forget the code, it forgot one of the two and offered to forget "a different code".
- **What H8 does about it:**
  - `save_note` now lists notes that look like the same thing, as possibly out of date;
  - `forget_note` lists the ones it left;
  - both say to forget them now (`Memory.related`: at least two content words in common, so "my locker code" isn't confused with "my gym locker").
- **Wording:** in those 2 runs the hints were optional ("if this replaces one…"); the model told the person instead of acting. They are now direct, the way the claim check's note had to be.
- **Not measured with the direct wording yet.** The Mac ran out of memory (16 GB, with the local model, two stacks and another project's): swap grew into the last gigabytes of disk, and both stacks' Postgres lost processes. The run is postponed to a fresh start.
- **Also found by these runs:** a note left over from an interrupted run ("gym locker 73") made a later "forget" choose between two notes: the same gap.

## Review

An independent review of the change, before it was finished:

- **Blocking: the upgrade would have failed on a real install.**
  - **Why:** the backfill updated every note, and the epoch fence refuses an update to a note whose run was leased again since, which happens after any approval or crash takeover.
  - **Why the tests missed it:** the migration test's notes and run all had epoch 0.
  - **Fix:** the backfill runs with the fence off, for that statement only.
  - **Test:** now reproduces it; it fails without the fix.
- **Medium:**
  - **One note longer than the 8k-window budget hid all of memory.** Now each note is one line, shortened past 400 characters, and a long one is skipped rather than ending the list.
  - **The forget claim check could have made the model forget a real note** ("Forget the onions…" / "I've removed the onions"). It now needs something remembered on both sides.
  - **An id copied with its brackets (`[abcd1234]`) found nothing.** Ids are read however the model copies them.
  - **"risk-management-guidelines-2026" was refused as a key**, and 2-series Mastercard numbers were kept. Fixed in the shared secret patterns, which also stops log lines over-masking.
  - **A test's notes could never be listed or deleted, and piled up.** They go with their run again.
- **Small:**
  - **Within a turn:** a note forgotten earlier in the turn still showed for the rest of it.
  - **Storage:** a deleted note's text stayed in checkpoints.
  - **Prompt honesty and forgery:**
    - a turn resumed from before H8 said "no notes";
    - a note's line breaks could forge newer entries.
  - **Audit and downgrade:**
    - restoring a remembered note, or clearing an empty memory, wrote audit rows;
    - a downgrade would have shown forgotten notes to the model again.
  - **UI:**
    - the page jumped back to the section after every change;
    - Delete was permanent with one click;
    - Restore buttons had no accessible names;
    - an agent whose helper keeps notes hid them;
    - a test chat linked to the real agent's memory.

  All fixed and tested. Each note is now one line, so the planted-text case is closed rather than just noted.

- **Left as known limits** (ADR-0006):
  - two identical saves in one model step can both pass the duplicate check;
  - the memory index serves its agent prefix only;
  - during a rolling deploy an H7 worker doesn't know `note_forgets`.

**Found by the browser test:** deleting from the page deleted the note, but the list didn't update. `unwrap` treats a 204 (no body) as a failure. `noContent` handles them, with a unit test.

**Found on the way: the Mac's memory.**
- **The machine was full:** with the local model (4.6 GB), two full stacks and another project's stack on a 16 GB Mac, swap reached 13 GB and grew into the disk.
- **Both stacks' Postgres crashed:** they lost processes in the same minutes, one of them idle.
- **What fixed it:** stopping the `validate` stack, then Ollama and `fresh`, brought RAM to 58% free and disk from 3.7 to 7.8 GB.
- **Not a product bug, but a limit for local testing:** one stack and the model at a time.

**Found by the container e2e:** its Postgres-restart scenario saved the fixed text "kept" and counted that run's notes. With duplicates kept once, a second run in the same stack saved none. That scenario, and the same one in the runtime and Kubernetes e2e, now save their own text.

## Design notes

- **Patterns** (in `docs/design.md`):
  - **Service Layer:** `Memory`, for the tools, the prompt and the API.
  - **Value Object from verified identity:** `Scope`, with `run_memory_scope`.
  - **Specification:** `rules.check`.
  - **Snapshot per turn, rendered per call.**
  - **Append, don't update, under a fence:** `note_forgets`.
- **Why the runtime and not a `session_start` hook:** hooks get only the session id and the agent's name, not the database. Their text also lands in the thread once per chat, so a note saved in another chat would never show in an open one.
- **Tests and shared state:** memory is shared state by design. Tests that count tokens, or look for a note by its run, start from no notes (the `no_memory` fixture), and the e2e scenarios save their own text.
