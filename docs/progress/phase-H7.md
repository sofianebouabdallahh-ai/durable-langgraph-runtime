# Phase H7 — Safe across deploys and side effects

**Completed:** 2026-11-09 · **Branch:** `feat/h7-safe-deploys` · **Plan:** [plans/phase-H7.md](../plans/phase-H7.md) · **Tests:** backend 880 (+16 since H6) · UI unit 78 · browser BROWSER

Found by the platform review of 2026-11-08 ("Make it solid"). Four ways a side effect could happen twice, or the model be told something false:
- **The key hashed the arguments.** The idempotency key hashed a call's *validated* arguments, defaults included. So a deploy that added a defaulted argument gave a done call a new key, and a run resumed after it made the call again.
- **Nothing stopped old code resuming new runs.** A run started on new code could be resumed by a worker still on the old code.
- **Retry was on by default.** `retry_after_crash` defaulted to true, so a new side-effecting tool was re-sent after a crash unless its author opted out.
- **The repair guessed.** MCP servers never received a key, and the turn after a cut-off one said "did not run" without checking.

## What we built

**A call is found by its place, not its arguments** (`tools/invocations.py`, `tools/pipeline.py`).
- **Lookup by place:** each ledger row now carries `call_key`, which is sha256 of run · node · position · tool. The ledger finds a call by it first.
- **Arguments checked apart:** the arguments' hash is kept beside it (`call_hash`). A call that comes back with other arguments, from a new default or a hook, is served what it did and recorded as `tool.args_changed`.
- **Takeovers:** a call cut off mid-call and taken over with other arguments is retried, if it may be, under the key it was first sent with, and it's noticed the same way.

**Expand/contract, so the deploy of H7 itself is safe.**
- **The row's key is unchanged:** it still hashes the arguments. During a rolling deploy or a rollback, a worker on the release before looks calls up only by that key, and it still finds every call a newer worker made.
- **Rows from before H7** are found by their key and given their place on the way.
- **The contract step** makes the key the `call_key`, in a later release, once no worker older than H7 is left.

**A run carries its format** (`runs.run_format`, `runs.code_version`).
- **Each lease raises the format,** to at least the worker's `RUN_FORMAT` (now 2). It does so in the same statement that takes the lease, and refuses a run that is already newer. So an older worker can never take back a run that newer code has had.
- **An older worker leaves the run untouched:** no lease and no checkpoint. It acks the message without re-sending it. The relay re-sends the run once its message is stale, so a newer worker gets it, and each such deferral is counted (`runtime_runs_deferred_total`).
- **The release** that created the run is recorded, for support.

**Side effects aren't retried unless the tool can dedupe** (`ToolSpec.retry_after_crash`).
- **Unset, it is "not a side effect".** A new side-effecting tool cut off by a crash isn't re-sent; the model is told it may have run once.
- **`save_note`, `notify` and `spawn_subagent`** dedupe by the key and say so. Reads and the sandbox tools are retried as before.
- **MCP:** every call carries its key in `_meta["io.nuria/idempotency-key"]`, the same on every attempt, so a server can do it once. A server's tool still retries only if it runs without asking.

**The repair says what really happened** (`RunExecutor._repairs`, `sessions/turns.py`). A turn that starts with calls of the previous turn left unanswered answers each one from that turn's ledger, finding the call by its place:
- **done (or failed):** its real result, exactly as a call served again is shown, through the agent's post_tool hooks, truncated and marked as data;
- **cut off mid-call:** "may have run once";
- **never recorded:** "did not run". This is never said of a call that might have run: a row from before H7 that can't be matched makes it "may have run once".

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | A deploy that adds a defaulted argument | ✅ A done call, resumed by a release whose args model gained `loud: bool = False`, is served its result; the tool isn't called; `tool.args_changed` is recorded once. A call the new release made isn't flagged |
| 2 | Rolling deploy and rollback (expand/contract) | ✅ A new worker's row has the pre-H7 key, so the release before finds it. Rows from before (no `call_key`) are found by key, served or taken over under their own key, and placed. When an old row matches by key and a new one by place, the place wins |
| 3 | Formats | ✅ A lease raises format 1 to 2. An older worker can't reclaim it, and changes nothing trying. A worker leaves a newer run: no lease, no epoch bump, no checkpoint. The worker acks its message without re-sending it. A format-1 run completes on new code |
| 4 | Retry defaults | ✅ A new side-effecting tool cut off by a crash isn't re-sent ("may have run once"). The built-in reads, `save_note`, `notify`, `spawn_subagent` and `run_python` retry. An MCP tool retries only when it runs without asking |
| 5 | MCP key | ✅ The fake MCP server records a 64-hex key on every call; the read-only call cut off by a crash and sent again carries the same key |
| 6 | Repair | ✅ After a turn cut short mid-step: the call that finished → its real result, marked as data, `cached`; the one cut off → "may have run once"; the refused one → "did not run". A replayed result is redacted and can be withheld by post_tool hooks. Calls from before H7 → never "did not run" |
| 7 | Quality | ✅ Backend 880 passed; e2e `all` × 5: 75/75; container e2e CONTAINER on H7 images; browser BROWSER; UI lint, types, 78 tests, build; mypy `--strict` |

## Review

A separate reviewer read the change before the final runs. Its findings, all fixed and tested:

**Serious**
1. **H7's own rollout could make a done side effect happen twice.** The first version wrote rows under the new, place-only key. A worker still on the release before, picking a run up during a rolling deploy or after a rollback, would find nothing and send `notify`, or an MCP write, again. It's now expand/contract: the key is unchanged, the place is a new column looked up first.

**Medium**

2. **The format was stamped by whoever created the run, and never raised.** A newer worker resuming an older run left it readable by older workers, and an API deployed ahead of the workers would strand new runs. Each lease now raises it atomically and refuses a newer one.
3. **The repair matched calls by the provider's call id across the whole chat.** Some servers reuse ids (`call_0`), and sub-agents' calls share the run, so a call that never ran could be shown another's result. It now finds each call by its exact place in the turn that made it.
4. **A call taken over with other arguments went unnoticed.** It's now recorded as `tool.args_changed` and retried under its original key.
5. **Tests didn't prove some claims:** the worker's ack without re-send, post_tool hooks on a replay, and which row wins when both match. All are now tested.

**Small**: calls from before H7 are never "did not run"; the new index is built `CONCURRENTLY`, so the ledger isn't locked while it builds; deferrals are counted.

**Checked and fine** (the reviewer's own words, in short): the tool always receives the key its row was recorded under, so `save_note`, `notify` and `spawn_subagent` keep deduping after a takeover; positions can't collide (the run id is in the key, compaction only happens at a turn's start, sub-agents have their own node); the repair is deterministic across a reclaim; the deferral path can't lose a run; nothing leaks across chats.

**Known limits**
- A run in flight across this upgrade whose call's *validated* arguments also change in this same release would get a new key. H7 changes no tool's arguments, so this can't happen now; from H7 on, the call's place protects it.
- The repair shows a replayed result through the post_tool hooks of the turn that reads it (the agent's current version), not those of the turn that made the call.
- The format gate has nothing to gate yet: H7's own changes are readable by the release before. It's there for the first change that can't be made that way.

## Design notes

- **Why not just change the key:** the whole fleet doesn't change at once. During a rolling deploy both releases run side by side, and a rollback puts the old one back. Each must find every call the other made, so a change to how calls are found takes two releases (expand, then contract), like a database column rename.
- **Why the format is raised by the lease:** the worker that takes the run is the one that writes it, so that's where the check and the stamp belong, and doing both in one `UPDATE … WHERE run_format <= mine` means no other worker can slip in between.
- **Why "may have run once" rather than a guess:** telling the model a call didn't run when it did invites it to do it again; the person decides.
