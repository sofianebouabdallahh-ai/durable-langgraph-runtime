# Phase H1 plan — Approvals you can trust

**Goal:** a tool that needs your approval runs only after **you** approved **that exact call**:
not after a crash, not with an earlier decision, not with arguments you didn't see, and not
when two of them were asked in the same step.

**Why:** the platform review of 2026-11-08 found that approvals, the guardrail Nuria leads
with, can be skipped or break:

| # | Finding | Severity |
| --- | --- | --- |
| 1 | `resume_value` is never cleared. If a worker dies between a tool's `interrupt()` and the pause commit, the reclaimed run resumes that tool with the **previous** approval (or crashes with `UnboundLocalError` when there was none). | Critical |
| 2 | Two ask-first calls in one model step: only the first is shown, and approving it fails the run (`RuntimeError: … must specify the interrupt id`). | High |
| 3 | The decision isn't tied to the call: no call id or args hash; edited args skip `pre_tool` hooks and policy. | Medium |
| 4 | The first hook that says "ask" stops the chain, so a later deny or redact hook never runs. | Medium |

**Requirements:** R1.4 (durable human approval), R14.9–R14.10 (deny by default, risk
classes), R15.5–R15.8 (hooks only tighten, fail closed), R14.17 (audit), R12.6 (approve in
chat).

---

## 1. Research (2026-11-08)

Checked against the installed LangGraph 1.2.12 with a small graph (two `Send` tasks, each
calling `interrupt()`, like `create_agent`'s tool node):

- Each pending interrupt has a stable `Interrupt.id`. Re-reading the state, which is what a
  reclaimed worker does, gives the same ids.
- `Command(resume=value)` with two pending fails:
  `RuntimeError: When there are multiple pending interrupts, you must specify the interrupt id`.
- `Command(resume={id: value})` resumes exactly those interrupts. With a subset, the others
  stay pending with the **same** ids.

So the fix is to make the **interrupt id** the unit of approval, and never resume with a
value that wasn't decided for that id.

## 2. Design

### 2.1 One row per approval: `run_approvals` (new table)

| Column | Meaning |
| --- | --- |
| `id` uuid | the approval's public id (API, UI, audit) |
| `run_id` | the run it belongs to |
| `interrupt_id` | LangGraph's `Interrupt.id`; NULL for approvals asked before H1 |
| `call_id`, `tool`, `reason` | what is asked |
| `args` | the arguments as shown to you (secrets redacted) |
| `args_hash` | sha256 of the canonical **real** arguments (NULL before H1) |
| `status` | `pending` → `approved` \| `rejected` \| `cancelled` \| `superseded` |
| `edits`, `comment`, `decided_by`, `decided_at` | the decision |
| `asked_epoch`, `created_at` | when it was asked |

At most one live row per `(run_id, interrupt_id)` (a partial unique index over `pending` and
`approved`). The API role may read it and decide pending rows; the worker role may insert and
supersede rows.

**Pattern:** a small state machine per approval, checked in the database (`CHECK` on the
status, compare-and-set `UPDATE … WHERE status = 'pending'`). The run's own state machine is
unchanged: it stays `waiting_approval` until **every** pending approval is decided.

### 2.2 Asking (worker, `_pause`)

`_pause` gets **all** pending interrupts, not only the first. In one fenced transaction, for
each tool-approval interrupt:

- no live row yet → insert a `pending` row, write an `interrupt` transcript message and an
  `interrupt.raised` event carrying the `approval_id`;
- a live row whose `args_hash` differs (the call changed) → mark it `superseded` and ask anew;
- an unchanged live row → leave it alone (a re-pause after a crash doesn't ask twice).

It also clears `resume_value`, which is no longer read. The column is dropped in a later
release (expand, then contract).

### 2.3 Resuming (worker, `_drive_graph`)

On every (re)execution with pending interrupts:

1. Spawn interrupts (fan-out) keep today's logic, but resume **by id**.
2. For approval interrupts, load the `approved` rows whose `interrupt_id` **and** `args_hash`
   match the pending interrupt.
3. Every pending interrupt has one → `Command(resume={interrupt_id: decision, …})`.
4. Any is missing → pause again, which asks for the missing ones. **A crash can never turn
   into an approval.**

This removes finding 1 (no stale value can be used) and finding 2 (all interrupts resume
together, by id).

### 2.4 Running the approved call (pipeline, stage 6)

- The interrupt carries `approval_id` (filled in by the worker), `call_id`, `args_hash`,
  `tool`, redacted `args` and `reason`.
- The resume value carries the decision **and the `args_hash` that was approved**. The
  pipeline recomputes the hash of the arguments it is about to run. If they differ, the call
  is **not** run (`Deny(not_approved)`: "the call changed after you approved it").
- **Edited arguments** go through the `pre_tool` hooks (an "ask" is ignored, since you just
  decided; deny and modify apply), are validated again, then go through `policy.check`
  (a deny applies).

### 2.5 Hooks: tightening only (finding 4)

`run_hooks` no longer returns at the first "ask". It runs every hook. A **deny** anywhere wins;
otherwise, any "ask" means ask. A **modify** after an "ask" still applies. Each decision is
audited.

### 2.6 Deciding (API)

- `POST /sessions/{id}/approve` and `POST /runs/{id}/approve` take a new **`approval_id`**.
  It's optional for compatibility: omitted, the request applies only when **exactly one**
  approval is pending, and returns 409 when several are. Our UI always sends it.
- **Approve:** the row becomes `approved` (compare-and-set: deciding twice → 409). When no
  pending row is left, the run is re-queued.
- **Reject:** as today, the turn is cancelled (`rejected`). Other pending rows → `cancelled`.
- `interrupt_payload` is now **the next pending approval**, carrying its `approval_id`.
  Once it is decided, the next one shows there. That's enough for a client to decide
  several approvals one by one, so no new field is needed.
- The `approval` transcript message and the audit entry carry the `approval_id`.

### 2.7 Chat UI

- Interrupt and approval messages are paired by `approval_id`, falling back to order for
  older messages.
- Every undecided approval in the waiting turn shows a live card. Each card sends its own
  `approval_id`. The composer waits until all are decided.
- A tool call is marked "waiting for you" by its `call_id`, not by its tool name.

### 2.8 Runs paused across the upgrade

The migration backfills one `pending` row (with `interrupt_id` NULL) for each run already
`waiting_approval`, from its `interrupt_payload`. After you decide it, the worker finds no row
matching the interrupt's id and asks again, now bound to the id. **Fail closed:** at worst
you approve twice, and never zero times.

## 3. Proof (tests)

Integration tests with the scripted model:

1. **Crash in the window.** A then B, each needing approval. A is approved and runs. The worker
   "dies" after B's interrupt is written but before the pause commits (the pause raises). The
   lease expires and another worker reclaims the run → `waiting_approval` for B. **B was not
   sent.**
2. **Crash before the first pause** → `waiting_approval`, not `failed(error)`.
3. **Two approvals in one step.** Both are shown. Approving one sends nothing. Approving the
   second sends both. Rejecting either cancels the turn and sends neither.
4. **Binding.** A wrong, already-decided or unknown `approval_id` → 409. Omitting the id with
   two pending → 409; with one pending → it works.
5. **The call changed.** A non-deterministic `pre_tool` hook changes the args on resume → the
   tool doesn't run.
6. **Edits are checked.** An edit to a recipient a `pre_tool` hook denies → nothing is sent.
7. **Upgrade.** A run left `waiting_approval` with a legacy payload → decide → asked again →
   approve → done exactly once.

Unit tests:

- `run_hooks`: `[ask, deny]` → deny; `[ask, modify]` → ask with the modified args; both
  audited.
- UI selectors: pairing by id; two live cards; each decision sends its own id.

End to end: the existing approval scenario (kill every worker while waiting) plus a new
**"two approvals in one step, killing workers between the decisions"**, each run 5 times.

## 4. Out of scope (later phases)

- "Edit and approve" in the card. The backend path is fixed here; the form comes with the
  approval UX work.
- Approval expiry (durable timers).
- An inbox of approvals across chats.
- Real identities in `decided_by` (H3 and tenancy).
