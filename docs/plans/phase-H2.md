# Phase H2 plan — Budgets that bind

**Goal:** every budget an agent has (model calls, tool calls, tokens, cost, time) is
really enforced, with real models, and reaching a limit ends a turn with an answer, not a
crash.

**Why:** the platform review of 2026-11-08 found that budgets, the second guardrail Nuria
leads with, don't bind in practice:

| # | Finding | Severity |
| --- | --- | --- |
| 5 | **Cost is $0 for every real model.** Only the scripted model has a price, and the lookup uses the model id the provider reports (dated snapshots such as `gpt-4o-mini-2024-07-18`). So the cost budgets, the $2 ceiling and the daily ceiling never fire. | Critical |
| 6 | **No tool-call ceiling** when an agent sets no limit of its own (`runs/limits.py:83`): `max_tool_calls: 1000000` is accepted with no 422, and the same goes for model calls. | High |
| 7 | **Hitting 100% loses the answer.** Helpers, or a burst of parallel calls, cross 100% between checks; the run fails with no reply, and calls already done are later reported as "did not run". | High |
| 8 | **Usage is lost on failure paths.** Tokens and cost are written only when a step commits, so crashes, cancels and retries spend money that is never counted. | Medium |
| 15 | **A failed call counts toward the loop limit:** a timeout, a retry, and the run ends `loop_detected`. | Medium |

**Requirements:** R14.1 (budgets), R14.2 (soft limit, wrap-up turn), R14.3 (ceilings ≥
profile ≥ options), R14.4 (loops), R16.8 (helpers' soft limit), R1.7.

---

## 1. Research (2026-11-08)

**Prices.** From OpenAI's [pricing page](https://developers.openai.com/api/docs/pricing)
(standard tier, short context, USD per 1M tokens; the page gives no "last updated" date,
and its latest dated note is 2026-07-30):

| Model | Input | Output | | Model | Input | Output |
| --- | --- | --- | --- | --- | --- | --- |
| gpt-6-astra | 10.00 | 50.00 | | gpt-5.2 | 1.75 | 14.00 |
| gpt-6.1-sol / gpt-6-sol | 2.00 | 10.00 | | gpt-5.1 / gpt-5 | 1.25 | 10.00 |
| gpt-6.1-terra | 1.00 | 5.00 | | gpt-5-mini | 0.25 | 2.00 |
| gpt-6-luna | 0.10 | 0.50 | | gpt-5-nano | 0.05 | 0.40 |
| gpt-5.6-sol | 4.00 | 20.00 | | gpt-4.1 | 2.00 | 8.00 |
| gpt-5.6-terra | 2.00 | 12.00 | | gpt-4.1-mini | 0.40 | 1.60 |
| gpt-5.6-luna | 0.20 | 1.20 | | gpt-4o | 2.50 | 10.00 |
| gpt-5.5 | 5.00 | 30.00 | | gpt-4o-mini | 0.15 | 0.60 |
| gpt-5.4 | 2.50 | 15.00 | | o3 | 2.00 | 8.00 |
| gpt-5.4-mini | 0.75 | 4.50 | | gpt-5.4-nano | 0.20 | 1.25 |

- Providers report **dated snapshot ids** (`gpt-4o-mini-2024-07-18`), so matching must be by
  the **longest prefix** (`gpt-4o-mini`, not `gpt-4o`).
- Cached input is cheaper. We count all input at the full rate, which errs high, and that
  is the safe side for a budget.
- Azure deployments have names their owner chose, so they rarely match. A per-connection
  price is the real answer for those.
- Prices change. The table is a dated default, never the only source.

## 2. Design

### 2.1 Every ceiling always applies (finding 6)

`resolve_limits` applies every server ceiling, whatever the profile sets. An option above
a ceiling is a 422 for every field.

### 2.2 Prices that are never silently zero (finding 5)

**Pattern: Chain of Responsibility (price resolvers), resolved once at turn creation and
pinned with the run's model bindings.** For each model the turn will use, the first that
answers wins:

1. **The connection's own price** for that model, set in Settings → Models (new:
   `model_connections.prices`).
2. **`MODEL_PRICES`** in `.env`, matched exactly, then by longest prefix.
3. **The built-in table** (§1), matched by longest prefix, dated in the code.
4. **A local model** (Ollama, or an address on this machine or network) is free.
5. **Otherwise an estimate:** a deliberately high default ($5 / $30 per 1M tokens), marked
   `estimated` so budgets still bind.

- The binding stores `{price: {input_per_mtok, output_per_mtok, source}}`. A turn keeps the
  price it started with.
- The usage recorder prices by the **binding** (the model the agent was configured with),
  not by the id the provider reports.
- Activity and "What happened?" show an estimated cost as `≈ $0.03 (estimated price)`, and
  the Studio says so when an agent's model has no price.

### 2.3 Usage recorded the moment it's spent (finding 8)

Each model call's tokens and cost are written right after the call, in their own fenced
transaction: the run and its ancestors, the session and `run_model_usage`. This is the
same pattern `charge_model_call` already uses before the call. A step lost to a crash and
run again really did call the model twice, and is now counted twice. Prometheus counts
usage at the same moment.

### 2.4 Reaching a limit ends with an answer (finding 7)

- **The wrap-up call is the one call allowed past a limit.** It's charged, but not refused
  for tokens, cost or a model-call budget a helper used up. It has no tools, so at most one
  such call happens.
- **Tool budgets don't crash a step.** A call over the tool budget returns a tool error
  ("the tool budget is used up; this call wasn't made") instead of raising. The calls
  already done in that step are checkpointed with their results, and the next model call
  is the wrap-up.
- **Helpers wrap up on every budget,** not only model and tool calls: tokens and cost too,
  at the same 80%.

### 2.5 Loops: failures can be retried (finding 15)

In the ledger, an identical call is served from an earlier result only if that result was
`done`, and only `done` calls count toward the loop limit (the 3rd identical call ends the
run). A `failed` call may be retried: the 3rd identical failure ends the run as
`loop_detected`.

## 3. Proof (tests)

- **Ceilings:** `max_tool_calls: 1000000` (and model calls, tokens, cost) → 422 for an agent
  with no limits of its own. Every agent run stores every ceiling.
- **Prices** (unit):
  - longest prefix (`gpt-4o-mini-2024-07-18` → gpt-4o-mini, not gpt-4o);
  - precedence (connection > `MODEL_PRICES` > built-in > local > estimate);
  - an Ollama connection is free;
  - an unknown model gets the estimate, marked.
- **Cost binds** (integration): a scripted run bound to a priced model fails `budget:cost`
  at its `max_cost_usd`, with its wrap-up answer.
- **Durable usage:** a worker dies after a model call and before the step commits; the
  run's tokens and cost include that call.
- **100%:**
  - a burst of 15 parallel tool calls at 78% of the tool budget ends with a wrap-up answer;
    the calls that ran keep their results, and the rest say why they didn't run;
  - a helper that uses up the run's model-call budget still leaves the main agent its
    wrap-up answer.
- **Loops:** a call that fails once and is retried with the same arguments runs again; the
  3rd identical failure ends the run as `loop_detected`.
- **UI:** a connection model's price in Settings → Models; "estimated" in Activity.
- **E2e and browser:** the suites, with a new browser step that sets a price.

## 4. Out of scope

- Per-connection rate limits (GCRA).
- Model fallback chains.
- Context-window management (H5).
- Exact cached-input pricing.
