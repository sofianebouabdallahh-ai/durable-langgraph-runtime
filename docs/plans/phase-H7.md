# Phase H7 plan — Safe across deploys and side effects

**Goal:** a deploy, a crash or a retry never makes a side effect happen twice, and
never tells the model something ran when it didn't (or didn't when it did).

**Why:** the platform review of 2026-11-08, "Make it solid":

| Gap | Today |
| --- | --- |
| Code versioning | A run's definitions are pinned, its code isn't. The idempotency key hashes the call's *validated* arguments, defaults included, so a deploy that adds a defaulted argument gives a done call a new key: on resume it runs again. A run started on new code can be resumed by a worker still on the old code. |
| External idempotency | `retry_after_crash` defaults to true, so a new side-effecting tool is re-sent after a crash unless its author remembers to opt out. MCP tools never receive the idempotency key, so a server can't deduplicate. The next turn's repair says "did not run" for a cut-off call without checking the ledger, which may say it did. |

## 1. Research (2026-11-09)

- **The key names the call, not its contents.** Durable-execution engines (Temporal's
  activity ids, Restate's invocation ids, Stripe's `Idempotency-Key`) identify the
  operation by where it sits in the history. Whether its payload changed is a separate
  question, answered by comparing a hash.
  - The position is fixed by the checkpoint: the model's message with its tool calls is
    stored before the calls run.
  - The arguments the code derives from it are not: defaults, validation and hooks.
- **Rolling upgrades** (expand/contract, Kubernetes rolling deploys): during a rollout,
  old and new workers run side by side.
  - New code must read old state.
  - Old code must not write state it doesn't understand: a worker leaves a run whose
    format is newer than its own to a newer worker.
- **MCP request metadata:** `tools/call` accepts `_meta`, reserved for out-of-band data the
  server may use. An idempotency key belongs there, under a namespaced name
  (`io.nuria/idempotency-key`), like an HTTP `Idempotency-Key` header.

## 2. Design

### 2.1 A call is found by its place, its arguments checked apart

- **Its place:** `call_key = sha256(run · node · call index · tool)`, stored on the
  ledger row (`tool_invocations.call_key`, new, unique). The ledger finds a call by it
  first, so a change of arguments doesn't make it another call.
- **Its key stays as it was** (it still hashes the arguments) for this release:
  expand/contract. During a rolling deploy or a rollback, a worker on the release before
  looks calls up only by that key, and must find every call a newer worker made, or it
  makes a done call again. Once no worker older than H7 is left, the key can become the
  `call_key` (the contract step, a later release).
- **The arguments' hash** (`sha256(canonical(args))`) is stored with the ledger row
  (`tool_invocations.call_hash`, new; `args_hash` is already loop detection's). When a call at the same position comes back:
  - **same hash:** the stored result is served, as today;
  - **different hash** (a deploy changed defaults, a hook changed its mind): the stored
    result is still served, because the call happened and must not happen again. It is
    logged and recorded as `tool.args_changed`, so an operator sees it.
- **Upgrade safety:** a run in flight has ledger rows with no `call_key`. The ledger looks
  the key up too, so a call made before the upgrade is found, not run again, and is given
  its place then.
- **Taken over with other arguments:** a call cut off mid-call is retried (if it may be)
  under the key it was first sent with, and `tool.args_changed` is recorded too.
- `repeat_hash` (loop detection) is unchanged.

### 2.2 A run carries its format; workers respect it

- `runs.run_format` (int, new): the newest format of code that has had the run (its
  checkpoints, ledger, state). 1 for every run until a lease raises it: each lease sets
  it to at least the worker's `RUN_FORMAT` (2 with this change), in the same statement
  that takes the lease, and only if it isn't newer already. So the check and the stamp
  can't race, and an API deployed ahead of the workers can't strand new runs.
- **A worker whose `RUN_FORMAT` is lower than a run's** doesn't execute it, and doesn't
  take its lease: the run stays untouched, and the worker acks its message without
  re-sending it (deferred, counted in `runtime_runs_deferred_total`). The outbox relay
  re-sends it once the message is stale, so a newer worker gets it. A newer worker reads
  every older format.
- **H7 itself doesn't need the gate:** its rows stay readable by the release before
  (2.1). The gate is for the first change that can't be made that way.
- `runs.code_version` (the `VERSION` that created it) is recorded for Activity and
  support. It's informational, not a gate.

### 2.3 Side effects are not retried unless the tool can deduplicate

- `retry_after_crash` defaults to **not `side_effect`**. A side-effecting tool is retried
  after a crash only when it says it can be:
  - the built-in `save_note` and `notify` (the key is their primary key);
  - the sandbox tools (a fresh sandbox, nothing outside it).
- **MCP tools** always receive the key as `_meta["io.nuria/idempotency-key"]`. A server
  marked *runs without asking* (read-only) is still retried; any other tool still says
  "may have run once".

### 2.4 The repair says what really happened

- When a turn starts with tool calls of the previous turn unanswered (that turn was
  stopped or crashed), each one's result comes from the ledger:
  - **done (or failed):** its stored result, exactly as a call served from the ledger is
    shown: through the agent's post_tool hooks, truncated, marked as data;
  - **in progress:** "This call was cut off and may have run once";
  - **no row:** "This call did not run".
- The repair finds each call by its place in the turn that made it (the last turn of the
  chat that wrote anything), as that turn keyed it: no provider call ids, which some
  servers reuse. A call that turn's ledger may hold only under a key nobody can rebuild
  (made by a release before H7) is "may have run once", never "did not run".

## 3. Proof (tests)

- **A deploy that adds a defaulted argument doesn't re-run a done call.** A run's tool
  call is done, then crashes before its step commits. The tool's args model gains a
  defaulted field. On reclaim, the tool isn't called again; `tool.args_changed` is
  recorded; the turn completes.
- **An in-flight run from before the upgrade:** its ledger row under the old key is found
  and not run again.
- **Formats:**
  - a worker on format 1 releases a format-2 run (`newer_code`) and doesn't touch its
    checkpoint;
  - a format-2 worker runs a format-1 run.
- **Retry defaults:**
  - a new side-effecting tool cut off by a crash isn't re-sent ("may have run once");
  - a read tool is; `save_note` is (its key dedupes it).
- **MCP:** the fake MCP server receives the key in `_meta` on every call, the same on the
  retry of a read-only tool.
- **Repair:** after a turn stopped mid-tool:
  - a done call → the next turn's model sees its real result;
  - a cut-off one → "may have run once";
  - one never started → "did not run".
- **Quality:** the backend suite, lint, mypy `--strict`, the UI checks, e2e `all` × 5,
  the container e2e and the browser suite.
