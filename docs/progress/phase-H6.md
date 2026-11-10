# Phase H6 — Evals and the publish gate

**Completed:** 2026-11-09 · **Branch:** `feat/h6-evals` · **Plan:** [plans/phase-H6.md](../plans/phase-H6.md) · **Tests:** backend 864 (+21 since H5) · UI unit 78 · browser 60 (+1)

Found by the platform review of 2026-11-08 ("Quality evals"): 11 injection cases tested the pipeline, but nothing tested whether an agent still did its job. The only publish gate was "one test chat completed", which says nothing about the answer.

## What we built

**A test case** (`evals/cases.py`). A case is:
- a message, and optionally the scripted model's replies, which make it deterministic;
- what the test answers when the agent asks for approval;
- what's expected:
  - the tools called, or never called;
  - the approvals asked;
  - the most tool calls;
  - words the answer contains or doesn't, a pattern, or a JSON schema it follows;
  - a rubric graded by the agent's own model.

Cases are validated strictly (a misspelt expectation is an error, never a skipped check) and hashed canonically, so editing a case makes its old results stale.

**A test is an ordinary turn.** So it's durable, observable and costed like one.
- **Its own chat:** each case runs in its own test chat, and every test turn simulates its side effects, Studio and `runtime eval` alike. Its notes stay in that chat in both directions.
- **Known before a worker sees it:** the `eval_runs` row is written in the turn's own transaction.
- **Approvals:** when the turn asks, the worker records the ask, then gives the case's answer through the normal path, written to the test chat like a person's.
- **Grading:** when the turn ends, the worker grades it once: tools from the ledger, approvals from the events, the answer from the result.
- **The safety net:** every worker sweeps every 10 s for tests nobody settled, after a crash or a cancel through the API.

**Studio → Tests.**
- Add a test, **Run tests**, see each result, what failed and why, and open its test chat.
- **The publish gate:** a draft with tests publishes only once every test passed on exactly that draft and that version of the test.
- **Make this a test:** on a 👎 reply of your own agent. Its message becomes a test, and your reason and the answer you didn't like become the rubric.

**`runtime eval`** runs the built-in agents' suites (`backend/agents/<name>/evals/*.yaml`):
- `assistant`: uses the calculator; notify asks first; a rejected notification is never sent.
- `chat`: keeps a note and reads it back; notify asks first; an injected instruction can't send anything.

CI runs them through the integration tests.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | A regression fails CI | ✅ With a policy that no longer asks, "notify asks first" fails with "notify ran without asking". With the calculator removed from `assistant`, "uses the calculator" fails |
| 2 | The gate | ✅ A draft with a test: publish → 409 "1 test hasn't passed on this draft". After Run tests and grading: published. An edited draft: blocked again (the result was on another bundle) |
| 3 | Checks | ✅ Unit: every check passes and fails on hand-made trajectories, with the reason; a JSON schema (fenced, wrong type, not JSON); a bad pattern or schema is an *error*, not a failure; strict cases; the hash ignores key order; a bad YAML file is named |
| 4 | The judge | ✅ A fake model's `{"pass": false, "why": …}` fails the case with that reason; only a real `true` passes (`"false"`, `1`, `"yes"` don't); with the scripted model, the case is an error, "needs a real model" |
| 5 | Make this a test | ✅ A 👎 with a reason → a case with the message, the reason and the bad answer in its rubric; a built-in agent's reply → 409 |
| 6 | Durable | ✅ The worker dies right after the pause → the sweep answers the approval and the test passes. A test turn cancelled through the API → the sweep grades it (failed). A crash that lost a step's `tool.called` events → the ledger still shows the call |
| 7 | Nothing reaches people | ✅ Both built-in suites leave `outbox_notifications` unchanged, and a real chat's `recall_notes` doesn't see a test's note |
| 8 | UI | ✅ Browser: add a test in the Tests section; publish is blocked; Run tests → Passed, "1 of 1 passed"; published |
| 9 | Quality | ✅ Backend 864 passed; e2e `all` × 5: 75/75; container e2e 8/8 on H6 images; browser 60/60; UI lint, types, 78 tests, build; mypy `--strict`. `runtime eval` on a fresh database: 6/6 |

## Review

A separate reviewer read the change before the final runs. Its findings, all fixed and tested:

**Serious**
1. **A test could stay "Running…" forever.** A crash right after the pause, a cancel through the API, an early failure, or a grading error left it unsettled. The worker's sweep now answers and grades those, and a grading error that won't heal marks the test `error`.
2. **`runtime eval` had real side effects.** It queued notifications, and its notes, including a planted instruction, reached real chats' `recall_notes`. Every test turn now simulates its side effects, and its notes stay in its chat.

**Medium**

3. **A crash could hide a tool call from the grade.** A step's `tool.called` events can be lost with it, so the tools now come from the ledger.
4. **The auto-decided approval looked undecided in the test chat.** It's now written and published like a person's.
5. **The judge passed on `{"pass": "false"}`.**
6. **The Publish button stayed stale after the tests passed.**

**Small**: the "1 test hasn't passed" grammar; "Out of date" is now checked before "Running…"; a redrive regrades a test.

**Known limits**
- Each Run tests opens one new test chat per case, and those chats aren't cleaned up.
- A case that approves a tool which asks for other reasons (a sandbox or MCP write) runs that tool in the test chat, as a person's approval would.

## Design notes

- **Why a test is a turn, not a special executor:** it gets fencing, reclaim, budgets, streaming, Activity and the "What happened?" story for free, and nothing about grading can drift from how real turns behave.
- **Why the gate checks hashes, not timestamps:** a result counts only for the exact bundle (the agent, its skills and its MCP tools) and the exact version of the case. Anything else would let a change slip through on an old pass.
- **Why the judge is the agent's own model:** it's the one connection the person has set up and paid for. A separate judge model would be a second key to manage. When there's no real model, the judge says so instead of passing.
