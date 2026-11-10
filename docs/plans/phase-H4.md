# Phase H4 plan — Honest and resilient

**Goal:** a database blip never ends a run for good, a failed turn can be tried again, a
notification really reaches someone, and nothing the README promises is missing.

**Why:** the platform review of 2026-11-08:

| # | Finding | Severity |
| --- | --- | --- |
| 14 | **Helper results reach the main agent as unmarked text.** When the turn guard waits for helpers, their outcomes go in as a `[runtime]` HumanMessage: not marked as data, not truncated. | Medium |
| 16 | **Infrastructure errors end runs for good.** A Postgres failover or a pool timeout lands in the executor's catch-all and the run ends `failed(error)`. Nothing can run it again. | High |
| 17 | **The README promises what isn't built.** Notifications are queued but never sent; notes can't be read back; 3 of the 9 hook points (`pre_model`, `post_model`, `on_error`) never run. | Medium |

---

## 1. Research (2026-11-09)

- **Transient vs. permanent errors.** Durable-execution engines (Temporal, DBOS, Restate)
  retry an activity on infrastructure errors and fail it only on errors marked
  non-retryable. A step that fails because the database went away is retried from its
  checkpoint; a bug fails. In psycopg 3, connection loss, `admin_shutdown` (57P01),
  `cannot_connect_now` (57P03), `too_many_connections` (53300), serialization failures
  (40001) and deadlocks (40P01) are all `OperationalError`s; the pool's `PoolTimeout`
  is one too. Redis's `ConnectionError` and `TimeoutError` are the same kind.
- **Bounded retries, then a dead letter.** SQS and Temporal both give up after N
  attempts and park the work where a person can **redrive** it. A redrive puts the work
  back, from where it stopped, once the cause is fixed.
- **Webhooks.** The [Standard Webhooks](https://www.standardwebhooks.com/) spec (Svix,
  Zapier, Twilio, others): `webhook-id` (the same on every retry, so the receiver
  can drop duplicates), `webhook-timestamp`, and `webhook-signature: v1,<base64
  HMAC-SHA256(secret, id.timestamp.body)>`. A secret starts with `whsec_` and is base64.
  Delivery is **at least once**; the stable id makes it **exactly once** for a receiver
  that keeps the ids it saw. Retries back off exponentially; 4xx (other than 408 and 429)
  isn't retried.
- **Transactional outbox, delivered.** `notify` already writes `outbox_notifications` in
  its own transaction, keyed by the call's idempotency key. What's missing is the relay:
  claim with `FOR UPDATE SKIP LOCKED`, send, mark delivered. The notification row is
  epoch-fenced (a stale worker can't add one), so delivery state lives in its own table:
  updating `sent_at` on a run that was reclaimed since would trip the fence.

## 2. Design

### 2.1 Helper results are data (finding 14)

- When the turn guard waits for helpers, their outcomes reach the model like
  `wait_subagents`' output: marked with `as_data` and truncated to `max_result_chars`,
  inside the runtime's note.
- The note itself (what happened) stays the runtime's words; only the outcomes are data.

### 2.2 Infrastructure errors are retried, then parked (finding 16)

**Pattern: a classifier (`runs/failures.py`, `is_transient(exc)`) and a bounded retry.**

- `is_transient` walks the exception, its causes and exception groups. It returns true for
  psycopg `OperationalError` (which includes `PoolTimeout`), Redis connection and timeout
  errors, `QueueUnavailable`, and `ConnectionError`.
- **In the executor**, a transient error doesn't fail the run. The run is **released**
  (back to `queued`, reason `infrastructure`). The release is deferred, so the outbox
  relay re-sends it once its message is stale, which is the backoff. The next execution
  resumes from the last checkpoint, and the ledger keeps done tool calls from running again.
- The **release fails too** when the database is still down. Then the error goes up to
  the worker, which already leaves the message for the reaper. The lease expires and the
  run is reclaimed: the existing path.
- **Bounded:** each infrastructure release counts (`runs.infra_retries`). Past
  `MAX_INFRA_RETRIES` (5) the run ends `failed(infrastructure)`, so a cause that never
  heals ends the run instead of looping forever.
- The poison-run check (an unknown graph, invalid input) still fails at once. It only
  retries when the error was transient (the database went away while loading the agent).

### 2.3 A failed turn can be tried again (redrive)

- `POST /runs/{id}/redrive`: `failed` → `queued`, from the run's last checkpoint.
- **Allowed** when the failure might not happen again: `error`, `infrastructure`,
  `max_reclaims`, `timeout`.
- **Refused** (409) when it would fail the same way: a budget, `loop_detected`,
  `step_limit`, `turn_denied`, `depth_limit`, `children_failed`, or a cancel or rejection.
- **Only top-level runs**, never a child. A chat turn only if it is **the chat's latest
  turn** and nothing is running in the chat, checked under the session's lock.
- **What resets:** `reclaims`, `infra_retries`, the working time (`started_at`,
  `waited_s`) and `finished_at`.
- **What doesn't reset:** the budgets. Tokens, cost and calls already spent still count,
  so a redrive can't be used to get around a limit.
- `runs.redrives` counts the redrives. The transcript gets a `system` row, "Tried
  again", so the chat shows the error, then the retry, then the answer.
- The error row's content carries the attempt, so a second identical failure is
  written, not de-duplicated away.
- Like any new work, it goes through admission control (the global pause, the queue's
  depth, the daily cost ceiling) and the agent's own kill switch, and it clears a Stop
  pressed before the failure.
- **Audited** as `run.redriven` (the person's action). Workers can never do this: it isn't
  in the state machine's `_ALLOWED`, it is one guarded `UPDATE … WHERE status =
  'failed' AND reason = ANY(…)`.
- **UI:** the error note in the chat gets a **Try again** button, shown only when the
  turn can be redriven.

### 2.4 Notifications are delivered (finding 17)

**Pattern: transactional outbox + relay (`notifications/delivery.py`); the Standard
Webhooks wire format.**

- **Migration 0024:**
  - a new table `notification_deliveries`: key → `outbox_notifications`, status
    `pending | sending | delivered | failed | skipped`, `attempts`, `next_at`, `claim`,
    `claimed_until`, `last_status`, `last_error`, `delivered_at`;
  - an `AFTER INSERT` trigger on `outbox_notifications` creates its delivery row, so
    every notification has exactly one;
  - rows from before H4 are backfilled as `skipped`, so an upgrade never sends old
    notifications by surprise.
- **Settings:** `NOTIFY_WEBHOOK_URL` and `NOTIFY_WEBHOOK_SECRET` (`whsec_…`; setup
  generates one). With no URL set:
  - nothing is sent, and `notify`'s result says so: "kept, not sent: no webhook is set
    up";
  - Settings → Tools shows it.
- **The relay** runs in every worker, every 2 s:
  1. **Claim:** `UPDATE … SET status='sending', claim=<uuid>, claimed_until=now()+60s,
     attempts=attempts+1 WHERE key IN (SELECT … WHERE status='pending' AND next_at <=
     now() OR status='sending' AND claimed_until < now() … FOR UPDATE SKIP LOCKED LIMIT
     10)`. Two workers never claim the same row.
  2. **Check the address** with `net.Guard` (H3) at every attempt.
  3. **POST** `{"type": "notification.created", "timestamp", "data": {id, to, message,
     run_id, session_id, agent, created_at}}`, with the Standard Webhooks headers.
     `webhook-id` is the notification's key, the same on every retry. Redirects are not
     followed (an SSRF bypass). Timeout 10 s.
  4. **Settle**, guarded by the claim, so a slow sender can't overwrite a newer claim:
     - 2xx → `delivered`;
     - 4xx other than 408 and 429 → `failed`;
     - anything else → `pending`, with a backoff of 5 s · 2^(n−1), capped at 1 h;
     - after 30 attempts (about 21 h with the backoff), or 24 h, → `failed`;
     - a webhook name that doesn't resolve right now is retried, not refused.
  5. **Renew:** just before each send, the claim is renewed (a lost one is skipped), and
     each attempt has a 30 s deadline, so a claim never expires while its sender may
     still POST.
- **Exactly once, honestly:**
  - two workers never send the same notification at once;
  - a worker that dies after the POST and before the settle sends it again after its
    claim expires, **with the same `webhook-id`**;
  - SECURITY.md and the README say "at least once, deduplicated by `webhook-id`".
- `GET /notifications`: the latest deliveries and their status, for Settings → Tools.
- Metrics: `nuria_notifications_total{outcome}`.

### 2.5 Notes can be read back (finding 17)

- A new tool, `recall_notes(query?, limit≤20)`, risk `read`.
- It returns the notes this agent saved, in any chat, newest first, optionally filtered
  by words in them. A helper's notes are its own (`notes.author`): a helper and its main
  agent don't read each other's.
- Its output is marked as data like every tool's: a note can't give instructions.
- It is granted wherever `save_note` is.

### 2.6 The three missing hook points run (finding 17)

- **`pre_model`**, before each of a main agent's model calls:
  - input: the run, the agent, the latest message's text, and the tool names;
  - output: Continue or Deny;
  - a deny ends the turn `failed(turn_denied)`;
  - fail closed.
- **`post_model`**, after each model reply:
  - input: the reply's text and its tool calls;
  - output: Continue, Modify (new text, tool calls kept) or Deny;
  - fail closed.
  - A built-in `redact_secrets_in_reply` uses it: a key the model echoes is masked before
    you see it or it's stored.
- **`on_error`**, when a turn ends `failed`: observe-only like `turn_end`, with the
  reason and detail.
- They're listed in Studio's hook catalog, like the others.

## 3. Proof (tests)

- **Postgres restart mid-step** (container e2e, `outage`):
  - a turn runs a slow tool;
  - `docker restart` Postgres mid-call;
  - the turn completes, with no `failed` and the tool run once (ledger).
- **Infrastructure retries** (integration):
  - the run's connections are terminated mid-step (`pg_terminate_backend`) → released
    `infrastructure`, then completed;
  - 6 transient failures → `failed(infrastructure)`;
  - a `ValueError` still fails at once;
  - `is_transient` unit-tested on every error class and on chained causes and groups.
- **Redrive** (integration and API):
  - `failed(error)` → redrive → completes from its checkpoint, with no tool run twice;
  - a budget failure → 409;
  - a turn that isn't the chat's latest → 409;
  - a running chat → 409;
  - a second identical failure is written to the chat.
  - Browser: Try again on a failed turn → the answer.
- **Webhook exactly once** (integration, a real local HTTP receiver):
  - two relays run at once → one POST;
  - a 500, then 200 → two POSTs with the same `webhook-id`, then `delivered`;
  - a 400 → `failed`, not retried;
  - a relay that dies after the POST → sent again with the same id;
  - the signature verifies;
  - a metadata URL → refused;
  - old rows are `skipped` by the migration.
  - **Container e2e:** an approved `notify` reaches the fake receiver exactly once, with
    a signature that verifies.
- **recall_notes:** saved in chat A, recalled in chat B by the same agent; not by
  another agent; filtered by words; output marked as data.
- **Hooks:**
  - a `pre_model` deny → `turn_denied`;
  - a `post_model` modify → the stored and shown reply is the modified one;
  - a raising hook → denied (fail closed);
  - `on_error` sees a failed turn;
  - `redact_secrets_in_reply` masks `sk-…`.
- **Helper outcomes:** the turn guard's message carries `<data source="subagents">`, and
  a long outcome is truncated.
- **Quality:**
  - the backend suite, lint, mypy `--strict`;
  - the UI checks;
  - e2e `all` 5×, the container e2e, the browser suite.
