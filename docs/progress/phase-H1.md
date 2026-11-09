# Phase H1 — Approvals you can trust

**Completed:** 2026-11-08 · **Branch:** `feat/h1-approvals` · **Plan:** [plans/phase-H1.md](../plans/phase-H1.md) · **Tests:** backend 685 (+13) · UI unit +1 · browser 57 (+1) · runtime e2e 15 scenarios (+1)

Found by the platform review of 2026-11-08: approvals, the guardrail Nuria leads with, could be skipped after a crash and broke when two were asked at once.

## What we built

**One row per approval** (`run_approvals`, migration 0022).
- Each row is bound to the LangGraph interrupt that asked (`Interrupt.id`) and to the sha256 of the call's **real** arguments.
- Status: pending → approved | rejected | cancelled | superseded. A CHECK constraint guards it, and only compare-and-set updates change it, so deciding twice is a 409.

**The worker resumes only with decisions bound to what is pending.**
- On every (re)execution it builds `Command(resume={interrupt_id: decision})` from approved rows whose interrupt id **and** args hash match.
- If anything is missing, it pauses and asks. This covers a crash before the pause committed, a call that changed, and a run paused before the upgrade.
- `resume_value` is no longer read. Fan-out resumes by interrupt id too.

**Several approvals in one step.** Each gets its own row, chat card and decision. Nothing runs until all are approved; rejecting one cancels the turn and the rest.

**In the tool pipeline:**
- A call whose arguments differ from the approved hash isn't run.
- Approved edits go through validation, the `pre_tool` hooks (a deny or redaction applies) and the policy.

**Hooks only tighten.** An "ask" no longer ends the chain: a later deny wins, and a later modify still applies (R15.7).

**API and UI:**
- `approve` takes `approval_id`. Without it, it works only when exactly one approval is pending.
- `interrupt_payload` is the next pending approval, with its id.
- The chat pairs each decision with its card by id, and marks the waiting call by its call id.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | A crash between the interrupt and the pause never reuses an earlier approval | ✅ Integration: A approved, B asked, the worker dies before the pause commits → reclaimed run asks for B; B is sent only after its own approval. **Mutation check:** with the old "whatever was approved" rule the test fails (B ran unapproved) |
| 2 | A crash before the first pause asks instead of failing | ✅ Integration |
| 3 | Two approvals in one step | ✅ Integration (approve both, reject one); **e2e 5/5** with every worker killed before each decision; **browser** card test in all 4 completed runs |
| 4 | Binding by id | ✅ Integration/API: no id with two pending → 409; unknown or decided id → 409 |
| 5 | A call that changed isn't run | ✅ Pipeline: hash mismatch → not run; executor: changed hash → superseded and asked again |
| 6 | Edits are checked | ✅ Pipeline: hook deny, hook modify and policy deny all apply to edits |
| 7 | Runs paused before the upgrade | ✅ Integration: decided once → asked again bound to the id → done exactly once |
| 8 | Quality | ✅ Backend 685 passed; lint, mypy --strict, agent validation clean; UI lint/types/tests/build; all 15 runtime e2e scenarios; the original approval e2e 5/5 |

**Browser suite against a stack built from this branch:**
- 57/57 in run 1.
- Runs 2–4: 56/57. The one failure each time was the observability test (a trace in Tempo, logs in Loki). In that hour, the local stack's two-week-old Tempo and Loki were timing out: trace queries returned 500 after 10 s, Loki returned 503, and the collector retried its exports. Nothing in H1 touches tracing or logging.
- CI runs the suite on a fresh stack.

## Found while testing

- **A race in an existing test.** The test waited for the notification row, not for the ledger to record the call as done. If the cancel landed in between, the next worker took the call over instead of replaying it; that is still correct, but not what the test checks. It now waits for the ledger, as its comment said.

## Design notes

- **Why a table, not a list in `interrupt_payload`:** a row per approval gives compare-and-set decisions and a database-checked state machine, and it is the base for an approvals inbox and approval expiry later.
- **Fail closed on upgrade:** a run paused before 0022 has no interrupt id, so after you decide it, it asks once more. At worst you approve twice, never zero times.
- **`resume_value`:** expand now, drop in a later release (contract).
