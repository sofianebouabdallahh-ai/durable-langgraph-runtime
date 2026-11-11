# Walkthrough — a fresh install, used for real

**Done:** 2026-11-10 · **Branch:** `fix/walkthrough-gaps` (on H7) · **Model:** qwen2.5:7b via native Ollama · **Tests:** backend 935 (+55 since H7) · UI unit 81 · browser 61 (+1, `console.spec.ts`)

H1–H7 were each tested against their own plan. This pass tested the product the way a person meets it: a fresh clone, `./setup.sh --non-interactive --build`, the default local model, and every screen driven in a browser (Playwright). Each gap was fixed and tested, then the fixes were reviewed twice by a separate reviewer.

## What was exercised

- **Setup and screens:** a fresh setup (ports picked around another stack; setup's own chat check). Every route in light and dark, at desktop and phone width.
- **Chat:** arithmetic with Python, notes saved and recalled across chats, an approval approved and one rejected, helpers, web search, Stop, the chat download and 👎.
- **Studio:** Get started → "Describe it" → the draft → the Studio editor → a test chat with a helper.
- **Activity and safety:** Activity, a turn's detail, the audit trail, the kill switch.
- **A crash:** the worker holding a real-model turn was killed mid-turn. The other worker took it over (epoch 2), and it finished with the right answer.

These worked as built and need nothing: approvals (exact arguments, approve, reject, the honest "not sent: no webhook set"), crash takeover, Stop, the download, drafting and the test chat, Activity and the audit trail.

## Gaps found and fixed

| # | Gap | Cause | Fix |
|---|---|---|---|
| 1 | "Remember that…" → "I've saved that", and nothing was saved | Three causes, below | Below |
| 2 | Web search said "no results" for common queries | SearXNG's three default web engines refused the home connection (rate limits, a CAPTCHA) | Yahoo joins the engines. An empty result now says which engines didn't answer, in the tool and in Settings → Tools "Test search" |
| 3 | A failed save's card read "Saved a note"; a rejected call's card, "didn't finish" | The card's title didn't depend on the outcome | "Couldn't save the note", "not done: you said no" |
| 4 | Every page had a console error | Vite inlined a small font file as a `data:` URL, which the CSP (`font-src 'self'`) refuses | Fonts are never inlined. A browser test now fails on any console error |
| 5 | A drafted agent could search but not read pages | The builder's choice; `web_search` tells the model to read before relying | The builder's repair adds Read web pages to Search the web, and says so |
| 6 | The Home guide card squeezed its text on a phone | No minimum width before wrapping | The buttons wrap below |

**Gap 1, in detail.** The default local model doesn't reliably use the notes tool. Seen, in order:

- **A test-only argument the model could see.** `save_note` showed it `linger_s`, a knob the crash test uses to hold the worker. The model read it as "how long to keep the note" and sent 86400. The call failed validation, and the model said it had saved the note anyway. The knob is now hidden from the schema. Invalid arguments now say "it did not run, so nothing was done".
- **A call written as text.** About half the time the model writes `save_note({"text": …})`, or a `<tool_call>` block, as its reply instead of making the call. The harness now makes it, through the pipeline (grants, approvals, the ledger), and the streamed text leaves the screen.
- **A claim with no call.** Often it just says "I've saved that". When the person asked to remember (or send) something, and no such tool succeeded in that turn, the harness asks once more, naming the tool. It doesn't ask near a budget limit or while helpers work, and asking never fails a turn that has its answer.
- **Measured** (15 "remember…" messages, qwen2.5:7b, before → after):

| | Before | After |
|---|---|---|
| Notes saved, through the app | 1 of 5 | 3 of 5 |
| Notes saved, against the model directly | 9 of 15 counting calls written as text | 13 of 15 |

- **The nudge's wording matters.** A note that left the model a way out ("if they asked you to…") got none of the 8 asked again saved; a direct "it isn't saved yet: call save_note now" got 6.

## Review

**First review**:
- **Serious:** a JSON answer whose `"name"` is an object (`{"name": {"first": "Ada"}}`) crashed the turn. It's now an answer.
- **Medium:**
  - the claim check fired on ordinary sentences ("Nothing has been saved yet", "As I noted", "has been recorded in Death Valley"), and on later questions about earlier saves. That would have saved duplicate notes and raised a second approval;
  - discarded drafts stayed on screen.
- **Small:**
  - a second ask that fails (a budget, the provider) failed the turn; it now keeps the first reply;
  - script drift in the scripted model after a repair (now documented);
  - helpers running during the check;
  - call ids;
  - `<tool_call>` inside arguments, `name()`, and the guard's reply;
  - SearXNG raising on a genuine empty result.

  All fixed and tested.

**Second review** (of those fixes):
- **Medium (a regression):** pressing Stop during the second ask was caught as a failed call, so the turn completed with the false claim. Stop, a takeover and a hand-over now propagate.
- **Medium:** "Did you save that?" / "Yes, I saved it" still triggered the check. Questions about what was done before are no longer claims.
- **Low:**
  - "send me…" / "tell me…" counted as asking for a notification;
  - "Test search" still said "no results";
  - missed claims after a dash, after "No problem,", with an adverb, "recorded", and the notify forms;
  - an unclosed `<tool_call>`;
  - reading notes back exempted `notify` too.

  All fixed and tested.

## Results (on `1e60cab`)

| Check | Result |
|---|---|
| Backend unit + integration | 935 passed, 3 skipped |
| Runtime e2e, `all` × 5 | 75/75 |
| Container e2e, on images built from this commit | 8/8 |
| Browser suite | 61 passed (with the new console check), 1 skipped |
| UI | lint, types, 81 tests, build |
| ruff, mypy `--strict` (src + tests) | clean |
| The walkthrough again, on the final build | the CSP error is gone; cards say what happened; web search finds results while three engines are blocked; 3 of 5 "remember…" saved (1 of 5 before) |

## Not fixed: recall

In a new chat the model rarely calls `recall_notes` on its own ("What is my locker code?" → "I don't have access to that"), even with the note saved. Asking it more firmly changed little. The reliable fix is to give the agent its notes when a chat starts. That's "memory across chats" on the review's list, and the start-of-chat hooks can't read the database today, so it's left for its own phase.

## Found on the way (not product bugs)

- **The disk filled during the walkthrough.** Repeated image rebuilds filled the Mac's disk, Docker's own disk went read-only, and only a restart of Docker Desktop recovered it. Pruning the build cache and old validation images freed about 17 GB. All Postgres instances recovered cleanly.
- **`./setup.sh` always names its Compose project `agent-runtime`.** A second checkout on the same machine shares the first one's containers and volumes unless `COMPOSE_PROJECT_NAME` is set (the walkthrough used `fresh`). This is fine for one install per machine; worth a note in the setup guide.
