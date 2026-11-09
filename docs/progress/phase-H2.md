# Phase H2 — Budgets that bind

**Completed:** 2026-11-09 · **Branch:** `feat/h2-budgets` · **Plan:** [plans/phase-H2.md](../plans/phase-H2.md) · **Tests:** backend 711 (+26 since H1) · UI unit (unchanged count, checks green) · browser +1

Found by the platform review of 2026-11-08: the budgets, the second guardrail Nuria leads with, didn't bind with real models and crashed instead of answering at the limit.

## What we built

**Prices that are never silently zero** (`models/pricing.py`).
- A Chain of Responsibility, in order:
  1. the connection's own price (new: Settings → Models → Prices, `model_connections.prices`);
  2. `MODEL_PRICES`;
  3. Nuria's dated price list, from OpenAI's official page, checked 2026-11-08;
  4. free for a local model;
  5. otherwise a deliberately high **estimate** ($5 / $30 per 1M tokens).
- Matching is by **longest prefix**, so a dated snapshot such as `gpt-4o-mini-2024-07-18` is priced as gpt-4o-mini, not gpt-4o.
- The price is resolved once, at turn creation, and **pinned in the run's model bindings**. A turn keeps its price even if you change it mid-turn.
- Activity and the turn detail show an estimated cost as `≈$… estimated`.

**Every ceiling applies to every run.** Before, the model- and tool-call ceilings applied only when the agent set its own limit, and tokens and cost only for agent graphs. Now an option above any ceiling is a 422.

**Reaching a limit ends with an answer.**
- The **wrap-up call is the one call allowed past a limit.** The soft-limit check now runs before the charge, so the wrap-up is charged without being refused. Follow-up calls (the empty-reply nudge, the turn guard) keep their tools and never take this allowance.
- **A tool call over the budget is a tool error** ("the tool budget is used up; this call wasn't made"), not an exception that fails the step. The calls already done keep their results, and the next call is the wrap-up.
- **Helpers wrap up at 80% of tokens and cost too**, not only model and tool calls.

**Usage recorded the moment it's spent.** Each model call's tokens and cost go to the run (and its ancestors), the session and `run_model_usage` in their own fenced transaction, right after the call. A step lost to a crash and run again really called the model twice, and is counted twice. Prometheus counts at the same moment.

**Loops:** an identical call is served again, and counted as a repeat, only if it didn't fail. A failed call may be retried; the 3rd identical failure ends the run as `loop_detected`.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | Ceilings | ✅ Unit: an option above any ceiling → `LimitAboveCeiling` for an agent with no limits; every run stores every ceiling; tighter layers still win |
| 2 | Prices | ✅ Unit: prefix matching (dated snapshots, no false prefix); the chain's order; local free; unknown → estimate. Integration: a connection's price is used and **pinned** (changed mid-turn, the turn keeps it); a negative price → 422 |
| 3 | Cost binds | ✅ A priced run with `max_cost_usd` ends `failed(budget:cost)` with its wrap-up answer; the soft limit was reached below the hard one |
| 4 | Durable usage | ✅ Worker A's call is recorded, then A dies before the step commits: the run's tokens and cost = the committed calls + A's lost call; `run_model_usage` agrees (3 calls) |
| 5 | A burst at the limit | ✅ 7/10 used, then one step asks for 15: 3 run, 12 are refused as tool errors, the wrap-up answers; never past 10 |
| 6 | A helper uses the budget up | ✅ The main agent still answers (6 calls + its one wrap-up) |
| 7 | Loops | ✅ A failing call is retried (not served); the 3rd identical failure → `loop_detected` |
| 8 | Quality | ✅ Backend 711 passed; lint, mypy --strict; UI lint, types, tests, build |

## Behaviour that changed (tests updated on purpose)

- **A run whose tool budget runs out** used to end `failed(budget:tool_calls)` with no answer. Now it ends `failed(budget:tool_calls)` with the wrap-up answer.
- **The session-repair test** used a tool budget to leave a turn's tool calls unanswered. A budget no longer does that, so it now uses a loop, which still fails mid-step.
- **`GET /runs/{id}`'s `limits`** now lists every ceiling.

## Design notes

- **Why pin prices at turn creation:** a turn's budget must not move under it, and a price change applies from the next turn, like a model change.
- **Why a high estimate, not "unpriced fails":** failing every turn on an Azure deployment name until someone sets a price would break working setups. A high estimate keeps the budget binding, errs on the safe side, and says "estimated" where you look.
- **Overshoot is bounded:** the wrap-up is one call with no tools, so it can go past a limit by at most one call (plus its retries).
