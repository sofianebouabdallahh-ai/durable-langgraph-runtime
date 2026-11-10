# Phase H5 — Long chats

**Completed:** 2026-11-09 · **Branch:** `feat/h5-long-chats` · **Plan:** [plans/phase-H5.md](../plans/phase-H5.md) · **Tests:** backend 843 (+27 since H4) · UI unit 78 · browser 59

Found by the platform review of 2026-11-08 ("Make it solid"): every model call resent the whole thread, tool results stayed forever, and once a chat passed the model's window every turn failed with `context_length_exceeded`. LangGraph stored the whole message list in every checkpoint, and nothing was pruned, so a chat's storage grew with turns².

## What we built

**Each call fits the model's window** (`context/fit.py`, a Strategy chain). Applied before every model call, for main agents and helpers. Only what's sent changes; the checkpoint and the transcript keep everything.
- **Past 60 % of the window:** old tool results are left out, oldest first: "This tool result was cleared to make room… call the tool again if you need it". The 2 latest are kept, and so are the latest step's (the model hasn't seen them). Every call keeps its result, so the request stays valid.
- **Past 85 %:** the longest older messages are cut to their start and end.
- **A model that says "too long":** the window it states is used for the rest of the run, and the request is fitted again, more strictly, once. If that fails too, the turn ends `context_overflow`. It isn't offered **Try again**, because the same turn would overflow again; the next message starts compacted.

**Long chats are compacted at a safe point** (`context/compact.py`).
- **When and where:** past 60 % of the window, at the start of a turn, in `before_agent`. That is before the turn writes a transcript row or records a tool call, so every id and idempotency key it makes is computed from the compacted thread.
- **What's kept verbatim:** the latest turns, within 30 % of the window; this turn's message; and `session_start`'s context, which is said only once per chat.
- **The summary:** everything older becomes one summary message, marked as data. The agent's own model writes it, charged like any call, with nothing streamed. With the scripted model, or if that call fails, it's extracted from the turns instead.
- **Room to grow:** compacting at 60 % and keeping 30 % leaves space before the next compaction.

**Storage stays flat.**
- After a run ends, its thread keeps only its latest checkpoint, the writes that checkpoint needs and the blobs it references. Its helpers' threads are dropped.
- Only rows older than the run's own last checkpoint go, so a next turn that has already started is never touched.
- The database does it (`prune_checkpoints`, `SECURITY DEFINER`). The worker still has no `DELETE` on LangGraph's tables.

**A context window per connection.** Settings → Models → **Context window**. The default is 128,000 tokens, or 8,192 for a model on this machine. It's pinned with each turn, like its price.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | A 200-turn chat stays inside its window | ✅ An 8,192-token window, about 6,000 characters of tool output per turn: the largest request the model received was **4,596 tokens**. Every turn completed; the transcript has all 200 questions and answers, with 400 unique tool-call ids |
| 2 | Its storage stays flat | ✅ **4,582 bytes after turn 50, 4,676 after turn 200**, with 1 checkpoint left after every turn |
| 3 | Fitting | ✅ Unit: unchanged when it fits; old results cleared first, the latest step's never, pairs valid, state not mutated; head and tail next; after a refusal nothing is cleared that the model hasn't seen. Integration: an 8-call turn stays in the window, `context.trimmed` recorded, the checkpoint keeps the full results |
| 4 | Compaction | ✅ One data-marked summary at the start of the thread; the oldest turn survives in it; `context.compacted` records the turns, tokens and how. The model writes it (charged) or it's extracted; `session_start`'s context is kept; a latest turn too big for its share is folded too; a repair keeps its transcript id when compaction moves it |
| 5 | Overflow | ✅ A model refusing anything over 3,000 tokens: refitted and answered. A model that never accepts: `failed(context_overflow)`, not redrivable |
| 6 | Pruning | ✅ 1 checkpoint after a turn, and the next turn works; a failed turn is still redriven from its pruned thread with nothing done twice; a helper's threads are gone; the worker can prune but `DELETE FROM checkpoints` is refused; in the containers, every finished thread keeps 1 |
| 7 | Quality | ✅ Backend 843 passed; e2e `all` × 5: 75/75; container e2e 8/8 on H5 images; browser 59/59; UI lint, types, 78 tests, build; mypy `--strict` |

## Review

A separate reviewer read the change before the final runs. Its findings, all fixed and tested:
1. **Fitting could clear the latest step's results.** The model would call the same tools again and loop. Those results are never cleared now, only shortened after a refusal, and a window the provider states is kept for the run.
2. **Compaction dropped `session_start`'s context,** which is said only once per chat. It is kept now (`session:` ids), and other context goes into the summary.
3. **A repair row could be written twice** when compaction moved it. Its transcript id now comes from its own id.
4. **A latest turn too big to keep was kept anyway,** so "the next message starts compacted" wasn't true. It's folded now.
5. **The scripted model reused tool-call ids** after compaction. They now include the turn.
6. **Pruning could remove older checkpoints of a next turn that had already started.** That was harmless, but it now prunes only below the finished run's own last checkpoint.
7. **Smaller points:** the summary call no longer hides a budget stop or a lost lease; `context.trimmed` is recorded only when trimming grows; the refit's window arithmetic is fixed.

**Not done:** very large tool-call arguments in older messages are not shortened (it would risk invalid JSON for some providers). They count toward the window like everything else.

## Design notes

- **Why not LangChain's `SummarizationMiddleware` as is:** its model call bypasses Nuria's budget, retries and breaker. It would consume the scripted model's script. And removing messages mid-turn would shift the positions that transcript ids and idempotency keys are built from. Its two ideas, clear tool results first and summarise when that isn't enough, are the ones used here.
- **Why fitting doesn't change the state:** a crash, a redrive or a reclaim must replay the same thread. What's sent can change with every call; what's stored can't.
- **Why a database function for pruning:** granting the worker `DELETE` on checkpoint tables would let a bug, or a compromised worker, erase any run's history. A `SECURITY DEFINER` function that can only delete what's older than a run's own last checkpoint keeps the grant narrow.
