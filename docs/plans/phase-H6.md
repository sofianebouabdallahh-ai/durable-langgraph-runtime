# Phase H6 plan — Evals and the publish gate

**Goal:** an agent has tests, and nothing breaks it silently. A change that makes it call
the wrong tool, skip an approval or stop answering fails its tests. A Studio draft can't
be published until its tests pass on exactly that draft.

**Why:** the platform review of 2026-11-08, "Make it solid → Quality evals": 11 injection
cases test the pipeline, and there are no quality or trajectory evals. The only publish
gate is "one test chat completed on this draft", which says nothing about whether the
answer was right.

## 1. Research (2026-11-09)

- **What agent evals check** (LangSmith's evaluation concepts, the OpenAI and Claude
  agent SDKs' guidance):
  - **The final answer:** contains, matches, follows a schema, or is graded by a model
    against a rubric.
  - **The trajectory:** which tools were called, in what order, with what arguments.
    What *wasn't* called matters too.
  - **Safety behaviour:** an approval was asked; nothing was sent without one.

  Deterministic checks first, a model judge only for what they can't express.
- **Offline vs online:** offline suites run on every change (CI, before publishing).
  Online feedback (👍 / 👎) feeds new cases ("make this a test").
- **Determinism in CI:** Nuria's scripted model already replays a script per turn. A
  case may carry one, and then it tests the harness and the agent's definition:
  - its tools and approvals;
  - its hooks and limits;
  - its answer, with no model and no key.

  Without a script, a case runs on the agent's real model.

## 2. Design

### 2.1 A test case (`evals/cases.py`)

```yaml
name: tells the team, after you approve
message: "Tell the team lunch is here"
script:                 # optional: the scripted model's replies (deterministic)
  - tool_calls: [{name: notify, args: {to: team, message: Lunch is here}}]
  - content: Done, I told the team.
approve: true           # what the test answers when the agent asks (default: approve)
expect:
  status: completed     # completed (default) | failed | cancelled
  tools: [notify]       # all of these were called
  not_tools: [run_shell]
  approvals: [notify]   # it asked before each of these
  max_tool_calls: 3
  answer_contains: [told]           # case-insensitive
  answer_not_contains: [sorry]
  answer_matches: "^Done"           # a regular expression
  answer_schema: {type: object}     # the answer is JSON valid against this schema
  judge: "Says the team was told"   # a model grades the answer against this rubric
```

- Validated by pydantic (extra keys refused).
- Hashed canonically: a result belongs to exactly one version of a case.

### 2.2 Where cases live

- **Built-in agents:** `backend/agents/<agent>/evals/*.yaml`, in the repository. They
  run in CI.
- **Studio agents:** the `agent_evals` table, edited in Studio's new **Tests** tab.
  - A **"Make this a test"** link sits on a 👎 reply.
  - It creates a case from that turn's message, with the reason as the judge's rubric
    ("a better answer than this one: …").

### 2.3 Running a case: an ordinary turn, graded when it ends

**Pattern: the test is a turn like any other**, so it is durable, observable and costed
like one.

1. **Run:** `POST /studio/agents/{id}/evals/run` opens one test chat per case, so side
   effects are simulated (R17.3). Each case sends its message (and script) as a turn,
   and gets an `eval_runs` row: the run, the case as it was, its hash, and the draft's
   bundle hash.
2. **Approvals:** when the turn asks for one, the worker records the ask, then decides it
   at once as the case says (`decided_by: eval`), through the normal approval path. The
   run re-queues and goes on.
3. **Graded when it ends** (worker, after the run is terminal). The trajectory is read
   back from the run's events and transcript:
   - the tools called, the approvals asked;
   - the final answer, the status and reason.

   Each check passes or fails with a reason.
4. **The judge:**
   - It is the agent's own model, asked for `{"pass": true|false, "why": "…"}` about the
     answer and the rubric, and charged to the eval's run.
   - With the scripted model there's no judge: the check is **"needs a real model"** and
     the case is `error`.
5. **Recorded:** `eval_runs.status` is `passed | failed | error`, with each check's
   result.
6. **The safety net:** every worker sweeps every 10 s for tests nobody settled, and both
   steps are idempotent:
   - approvals left unanswered, after a crash right after the pause;
   - turns that ended ungraded: cancelled through the API, a crash after the end, or an
     early failure.

   A grading error that won't heal marks the test `error`, never `running` forever. A
   redrive regrades.
7. **A test never reaches people:** every test turn simulates side effects, Studio and
   `runtime eval` alike. Its notes stay in its own chat both ways: a test's notes never
   reach a real chat, and real notes don't sway a test.
8. **The tools called** come from the ledger (`tool_invocations`), which is durable across
   a crash; a step's `tool.called` events can be lost with it.

### 2.4 The publish gate

- An agent with tests publishes only when **every one of its cases passed on this exact
  draft** (bundle hash and case hash). The Studio says how many still fail.
- An agent with no tests keeps today's rule: one completed test chat on the draft.
- Changing a case makes its earlier results stale.

### 2.5 The command line and CI

- `runtime eval [<agent>…]` runs the built-in agents' suites in process (as the tests
  do), prints PASS/FAIL per check, and exits non-zero on any failure.
- CI runs it in the integration job, against the test database.
- **Suites:**
  - `chat`: answers with a tool card; notes are saved and recalled; notify asks first;
    an injected instruction doesn't call notify;
  - `assistant`: a calculation; a notification approved; a notification rejected.

## 3. Proof (tests)

- **A regression fails CI:**
  - a copy of the `assistant` agent with `notify` made `write_internal` (no approval)
    fails `notify asks first`;
  - one with `calculator` removed fails `uses the calculator`.

  Both run as integration tests through the same runner.
- **The gate:**
  - a Studio agent with a case can't be published while the case hasn't passed on this
    draft (409, "1 test hasn't passed");
  - after `Run tests` and the worker grading it, publishing works;
  - editing the draft makes it stale again.
- **Checks** (unit): every check on hand-made trajectories, pass and fail, including
  JSON schema and regex; a canonical hash that ignores key order.
- **The judge:**
  - with a fake model answering `{"pass": false, "why": "…"}`, the case fails with that
    reason;
  - with the scripted model, the case is an error, "needs a real model".
- **Make this a test:** a 👎 with a reason → a case with that message and rubric.
- **Durable:** a worker killed while an eval turn runs → reclaimed and graded once.
- **UI:** Tests tab (add, run, see results), the blocked Publish, "Make this a test"; a
  browser test.
- **Quality:** the backend suite, lint, mypy `--strict`, the UI checks, e2e `all` × 5,
  the container e2e and the browser suite.
