# Phase H4 — Honest and resilient

**Completed:** 2026-11-09 · **Branch:** `feat/h4-honest-resilient` · **Plan:** [plans/phase-H4.md](../plans/phase-H4.md) · **Tests:** backend 816 (+56 since H3) · container e2e +2 scenarios (`outage`, `notify`) · UI unit 77 · browser 59 (+1)

Found by the platform review of 2026-11-08, findings 14, 16 and 17: a database blip ended a run for good, a notification was queued and never sent, notes couldn't be read back, three of the nine hook points never ran, and helpers' results reached the main agent as unmarked text.

## What we built

**A database or queue failure doesn't end a run** (`runs/failures.py`, an error classifier).
- `is_transient` looks through the error, its cause or context, and exception groups. psycopg `OperationalError` (which includes `PoolTimeout`) and Redis connection and timeout errors count; a bug doesn't.
- The executor **releases** the run instead of failing it. It resumes from its last checkpoint once the relay re-sends it, about 30 s later (that delay is the backoff), and the ledger keeps done tool calls from running again.
- **Bounded:** after 5 releases (`runs.infra_retries`) it ends `failed(infrastructure)`. If the database is still down, the release fails too; the lease then expires and the reaper reclaims the run.
- **The pool checks each connection before handing it out,** so after a Postgres restart it reconnects instead of failing the next query.

**Try again** (a dead letter and a redrive).
- `POST /runs/{id}/redrive` and **Try again** in the chat: `failed → queued`, from the last checkpoint.
- Offered only for failures that might not happen again: `error`, `infrastructure`, `max_reclaims` and `timeout`. Never for a budget, a loop or a refusal.
- **Limits:**
  - only a top-level run, and in a chat only the latest turn, checked under the run's and the chat's row locks;
  - the budgets already used still count;
  - like any new work, it goes through admission control and the agent's kill switch.
- The chat shows the error, then "Tried again", then the answer. A second identical failure gets a new row.
- **Audited.** Workers can never do it: it isn't in the state machine's table, it is one guarded `UPDATE`.

**Notifications are delivered** (`notifications/delivery.py`, a transactional outbox with a relay).
- A trigger gives each `notify` row exactly one delivery row. Every worker relays them:
  1. claim with `SKIP LOCKED` and a claim token;
  2. renew the claim just before sending, inside a 30 s deadline;
  3. check the address with the outbound guard;
  4. POST in the Standard Webhooks format, signed with `NOTIFY_WEBHOOK_SECRET`, which setup generates;
  5. settle, only if the claim is still its own.
- A 5xx or a timeout is retried with exponential backoff, for about 21 h. A 4xx is final. A name that doesn't resolve is retried.
- **At least once, with one `webhook-id` per notification,** so a receiver that keeps the ids it has seen acts exactly once.
- Settings → Tools → Notifications shows where they go and how each went. With no webhook set, `notify` says the notification was kept, not sent.
- An upgrade sends nothing old: notifications from before H4 are marked `skipped`.

**Notes can be read back.** `recall_notes` comes with Notes. It returns what this agent saved, in any chat, newest first, filtered by words. A helper's notes are its own (`notes.author`).

**The missing hook points run.**
- `pre_model` runs before each of a main agent's model calls, including the empty-reply nudge and the call after waiting for helpers. It can deny the turn.
- `post_model` can change the reply's text (other content blocks are kept) or deny the turn. A new protection, **Hide secrets in its replies** (`redact_secrets_in_reply`), uses it. With a `post_model` hook, tokens aren't streamed, so nothing reaches the screen before the hooks have seen it.
- `on_error` sees every failed turn, including one that ran out of reclaims.

**Helpers' results are data.** When the runtime waits for helpers before the final answer, their outcomes are marked like any tool output and truncated.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | Postgres restart mid-step | ✅ Container e2e `outage`: `docker restart postgres` during a turn's tool call; back in 1.5 s; the turn completed, no `run.failed`, the note saved once, no duplicate messages. Integration: every connection terminated (`pg_terminate_backend`) mid-tool → completed |
| 2 | Bounded, and bugs still fail | ✅ A transient error → released `infrastructure`, then completed, tool once; never healing → `failed(infrastructure)` after the retries, `can_retry`; a `ValueError` fails at once |
| 3 | Redrive | ✅ From the checkpoint, nothing done twice, audited; a loop or budget failure → 409; not the latest turn → 409; through admission control (paused → refused); clears an earlier Stop; a repeated failure is written again. Browser: a reply out of time → **Try again** → the answer, 2 tool runs in all |
| 4 | Webhook exactly once | ✅ Real HTTP receiver: one POST, signed and verified; two relays at once → one POST; 500 then 200 → same `webhook-id`; 404 → not retried; a sender dying after the POST → resent with the same id; a lost claim → no send; metadata address → refused; an unresolvable name → retried. Container e2e `notify`: nothing before approval, `[500, 200]`, one id, signature verified, Settings says delivered (2 attempts) |
| 5 | recall_notes | ✅ Saved in one chat, recalled in another by the same agent, filtered, marked as data; not by another agent; a helper's notes are its own |
| 6 | Hooks | ✅ `pre_model` deny → `turn_denied`, seen by `on_error`; `post_model` masks a key in the stored reply; a broken `post_model` hook fails closed and the reply is withheld |
| 7 | Helper outcomes | ✅ The turn guard's message carries `<data source="subagents">` |
| 8 | Quality | ✅ Backend 816 passed; e2e `all` × 5: 75/75; container e2e 8/8; browser 59/59; UI lint, types, 77 tests, build; mypy `--strict` |

## Review

A separate reviewer read the change before the final runs. All ten findings were fixed and tested:
- redrive skipped admission control and the agent's kill switch, and kept an earlier Stop;
- a slow sender could POST after its claim expired, while another worker sent the same notification;
- a DNS blip failed a notification for good;
- the chat could miss stream updates when you clicked **Try again**;
- the documented retry window was longer than the code's;
- `pre_model` didn't run before every model call;
- two failure paths skipped `on_error` and the chat's error row;
- a helper and its main agent shared notes;
- the plan's wording, and a reply's non-text content dropped by a `post_model` change.

## Testing environment note

The first browser runs for H3 and H4 timed out on many tests. A local kind cluster had been crash-looping for days (its controller manager, scheduler, KEDA and in-cluster workers had restarted about 100 times each). It used about 3 of Docker's 8 CPUs, so every commit on the test stack was slow: an agent draft took 21.6 s instead of 0.3 s. With the cluster stopped, H2, H3 and H4 each passed every browser test, back to back on the same stack. The cluster needs recreating (`./setup.sh --kubernetes`) before the next Kubernetes run.

## Design notes

- **Why release, not retry in place:** a release goes through the same path as a graceful shutdown. A fresh execution resumes from the checkpoint, with a new lease and a backoff, and the code needs no special retry state.
- **Why redrive is outside the state machine:** workers must never move a run out of `failed`. Keeping it a single, guarded, person-only `UPDATE` makes that true by construction.
- **Why at least once with a stable id, not "exactly once":** a crash between the POST and recording it can't be closed from our side. Standard Webhooks' `webhook-id` is how receivers deduplicate, and saying so is the honest promise.
