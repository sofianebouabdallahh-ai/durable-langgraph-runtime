# Phase H5 plan — Long chats

**Goal:** a chat can go on for hundreds of turns. What the model is sent stays inside
its context window, and the storage behind a chat grows with what the chat holds, not
with the number of turns squared.

**Why:** the platform review of 2026-11-08, "Make it solid":

| Gap | Today |
| --- | --- |
| Context management | Every model call resends the whole thread; tool results (up to 16k characters each) stay forever. Once a chat passes the model's context window, every turn fails with `context_length_exceeded`, and the chat is stuck. |
| Storage growth | LangGraph stores the `messages` channel whole in every checkpoint, so a chat's checkpoints grow roughly with turns²; nothing is ever pruned. |

## 1. Research (2026-11-09)

- **LangChain 1.4** ships `SummarizationMiddleware`, which replaces the state's messages
  (`RemoveMessage(REMOVE_ALL_MESSAGES)`) with a summary and the recent ones, and
  `ContextEditingMiddleware` / `ClearToolUsesEdit`, which clears old tool results in
  what's sent. We can't use them as they are:
  - their model call bypasses Nuria's budget, retries and breaker;
  - the summary call would consume the scripted model's script;
  - removing messages mid-turn would shift the positions that transcript ids
    (`message_id(run, node, index, type)`) and idempotency keys (`call_index`) are
    built from.

  Their two ideas are the right ones, though: clear old tool results first, summarise
  only when that isn't enough.
- **Where removal is safe:** at the very start of a turn, in `before_agent` (a node, so
  checkpointed), before the turn has written any transcript row or recorded any tool
  call. Every key and id the turn makes afterwards is computed from the compacted
  thread, and a reclaim reads that same checkpoint. Inside a turn, only what is *sent*
  may change; the state stays as it is.
- **Context windows:** providers don't report them uniformly. A setting per connection,
  a cautious default (8,192 for a local model, 128,000 for a hosted one), and the
  provider's own number when it says "maximum context length is N tokens".
- **Checkpoint storage** (langgraph-checkpoint-postgres 3.1): `checkpoints` (one row
  per step), `checkpoint_blobs` (a channel's value per version: the whole message list
  for `messages`) and `checkpoint_writes`. Only the latest checkpoint of a thread, with
  its writes and the blobs it references, is needed to resume, redrive or start the next
  turn.

## 2. Design

### 2.1 Context windows

- `model_connections.context_tokens` (optional), set in Settings → Models.
- Otherwise `LOCAL_CONTEXT_TOKENS` (8,192) for a model on this machine or network,
  `CONTEXT_TOKENS` (128,000) for a hosted one.
- **Pinned** with the turn's model bindings, like its price (H2).

### 2.2 What each call sends fits (non-destructive, every call)

**Pattern: a Strategy chain in `context/fit.py`, run in `RuntimeMiddleware` before each
model call (main agents and helpers):**

1. Estimate the request: the messages, plus the tools' schemas
   (`count_tokens_approximately`, plus a margin).
2. **Under 60 % of the window:** send it as it is.
3. **Over 60 %:** clear old tool results, oldest first, keeping the 2 latest and never
   the results of the latest step (the model hasn't seen them; cleared, it would only
   call the tools again):
   `[runtime] This tool result was cleared to make room (N characters). Call the tool
   again if you need it.` The call/result pairing is kept, so the request stays valid.
4. **Still over 85 %:** shorten the oldest messages of the current turn to a head and a
   tail, never the latest exchange.
5. A `context.trimmed` event records what was cleared, once per call that changed.

The state isn't changed: the full result is still in the checkpoint and the transcript.

### 2.3 Long chats are compacted (at the start of a turn)

In `before_agent`, after the turn hooks: if the thread before this turn is over 60 % of
the window, older turns are folded into one summary.

- **Kept:** the latest turns verbatim, at most 2 and within 30 % of the window (a latest
  turn too big for that is folded too), this turn's message, and session_start's
  context, which is said once per chat (`session:` ids). The gap between 60 % and 30 %
  is the room a chat grows into before the next compaction.
- **Summarised:** everything before them, together with an earlier summary. The summary
  is written by the agent's own model:
  - charged to the turn like any call, through its retries and breaker; it is the
    runtime's own call, so the agent's model hooks don't see it and nothing is streamed;

  When that isn't possible or fails (the scripted model, an error, an empty answer), an
  **extractive summary** is used instead: each turn's question and answer, shortened, and
  the tools used.
- **The state update:** `RemoveMessage(REMOVE_ALL_MESSAGES)`, the summary, then the kept
  messages with their own ids. The summary is a `HumanMessage` with id
  `summary:<run id>`: `[runtime] What happened earlier in this conversation` plus the
  summary, marked as data. The transcript ignores it; the transcript keeps everything.
- An event, `context.compacted`, records the turns folded, the tokens before and after,
  and how the summary was written (`model` or `extract`).
- **Safe for keys and ids:** compaction happens before the turn writes anything, and
  every id and key is computed afterwards from the compacted thread. `script_offset`
  counts only what remains, so the scripted model still finds its place.

### 2.4 A context overflow is recovered, not repeated

- A window the provider states is kept for the rest of the run.
- If the provider answers that the request is too long (OpenAI's
  `context_length_exceeded`, or "maximum context length"/"too many tokens"), the call is
  fitted again with a smaller budget. The window is taken from the error message when it
  states one. It is retried **once**.
- If that fails too, the turn fails with `context_overflow`. It isn't offered **Try
  again** (the same turn would overflow again); the next message starts compacted.

### 2.5 Checkpoints are pruned

- **When:** after a run ends (completed, failed or cancelled), the executor prunes its
  thread. Nothing is pruned while a run waits or runs.
- **What it keeps:** the latest checkpoint, its writes, and the blobs any remaining
  checkpoint references.
- **What it deletes:** checkpoints older than the finished run's own last checkpoint
  (ids are time-ordered, so a next turn that already started is never touched), their
  writes, and blobs no remaining checkpoint references.
- **Helpers' threads** (one per sub-agent invocation) are dropped entirely once the run
  ends; they're never resumed after that.
- **Least privilege:** the worker gets no `DELETE` on LangGraph's tables. It may call one
  `SECURITY DEFINER` function, `prune_checkpoints(thread_id, keep_latest)`, owned by the
  migrator, which can only do this.
- A failure to prune is logged and never fails a run. The next prune catches up.

### 2.6 UI

- "What happened?":
  - "Earlier messages were summarised to make room (N turns)";
  - "Old tool results were cleared to make room".
- Settings → Models: an optional **Context window** per connection.

## 3. Proof (tests)

- **A 200-turn chat** (integration, scripted):
  - each turn calls a tool returning about 3,000 characters, on an 8,192-token window;
  - every model request stays under the window (measured on what the model received);
  - compaction happened, and every turn completed;
  - the thread's checkpoint storage after turn 200 is within 1.5× of after turn 50
    (flat, not growing with turns²);
  - the transcript has every turn, in full.
- **Fitting** (unit): under the limit → unchanged; old tool results are cleared first,
  the latest kept, and pairs stay valid; then head-and-tail; the state is never mutated.
- **Compaction** (integration):
  - ids are kept;
  - the summary is data;
  - a reclaim after the compaction step resumes with the same keys;
  - no tool is run twice;
  - the transcript is untouched;
  - `script_offset` still works;
  - the model summary is charged;
  - the extractive summary is used with the scripted model.
- **Overflow:** a fake provider that refuses requests over N tokens with
  `context_length_exceeded` → fitted again and answered; a second refusal →
  `failed(context_overflow)`, not redrivable; the next turn is compacted and answers.
- **Pruning:**
  - after a turn, the thread keeps 1 checkpoint and the next turn works;
  - a failed run can still be redriven from it;
  - a run's helper threads are gone;
  - the worker can't `DELETE FROM checkpoints` directly (least privilege);
  - a newer turn's checkpoints are never pruned.
- **Quality:** the backend suite, lint, mypy `--strict`, the UI checks, e2e `all` × 5,
  the container e2e and the browser suite.
