# Phase L7 — Watch it work

**Completed:** 2026-10-21 · **Branch:** `feat/l7-observability` · **Plan:** [plans/phase-L7.md](../plans/phase-L7.md) · **Guides:** [observability](../setup/observability.md), [security](../security.md), [Kubernetes](../kubernetes.md) · **Tests:** backend 641 (+12) · UI unit 73 (+6) · browser 53 (+6) · container e2e 4 checks

## What we built

**Activity** (L7c), a page in the app, read from Nuria's own database, so it needs no extra services:

| Section | Shows |
|---|---|
| **Right now** | running, waiting for you (with a link to the chat), queued, spend today, agents switched off |
| **Totals** | turns (and how many failed), chats, tokens and model calls, cost, tool calls and helper runs, approvals |
| **Over time, Spend** | turns per day by agent (stacked, top five and "Other"), cost per day; each chart also reads as a table |
| **Agents, Models, Tools** | per agent: turns, failures, median and p95 time, tokens, cost, 👍 / 👎; per model: calls, tokens in and out, average time, cost; per tool: calls, failures, reused results, p95 |
| **What went wrong** | failures grouped by reason and agent, with the latest one |
| **Chats, Turns** | every chat in range, and every turn (newest first, paged); a turn opens on its own page: its model calls per model, and its timeline |

Range 24 hours / 7 / 30 days, one agent or all, test chats in or out. Per-model usage is saved with each step, in its transaction (`run_model_usage`, migration 0019), so a re-run step counts once.

**One id finds every line** (L7a).
- Each boundary binds its ids: the request (`request_id`, also sent back as `X-Request-ID`), the turn (`run_id`, `session_id`, agent and version, worker), a helper, a tool call. Every line written inside carries them, and the span's `trace_id` and `span_id`. A helper's task starts from an empty context on purpose, so it takes the turn's ids over explicitly (but not the spawning tool call's).
- **What's logged:** one line per thing that happened, with its numbers: a turn starting and ending, each model call, each tool call, helpers, approvals, the kill switch, budget warnings, sandboxes, and one access line per request (the route's template, not its ids). **Never** message text, tool arguments or results; every line goes through the same secret filter as tool results.
- **Errors in the page** go to the API's log (`component=ui`), bounded and rate-limited; an error boundary replaces a blank page with a way back.
- Spans carry the **GenAI attribute names** (agent, conversation, model, tokens, tool).

**Find it in Grafana** (L7b, with `--observability`).
- **Tempo replaces Jaeger**; **Loki** keeps the log lines, 7 days. Grafana links a trace to its lines and a line to its trace; the dashboard has a **Logs** row (warnings and errors by service, failed turns with their trace, errors from the page).
- Under each reply: **Open the trace** and **Its log lines**.
- The processes send their lines to the collector over OTLP, beside their spans (decision 4 in the plan): no access to Docker's or the nodes' log files, the same on Compose and Kubernetes. Stdout stays the source of truth.
- Kubernetes: Tempo and Loki as StatefulSets with volumes, the same links.

**Who did what** (L7d).
- **Who changed what:** every change to agents, skills, models, settings, the kill switch and approvals, written in the change's own transaction (`audit_events`, migration 0020), with before and after. The API's database user can insert and read it, never update or delete it; a key appears only as "set" and its fingerprint. A page under Activity, and a CSV download.
- **👍 / 👎 on each reply**, with an optional reason; click again to take it back. Counted per agent in Activity, kept with the agent's version: the seed of evaluation sets.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | **One id finds everything** | ✅ Integration: a chat turn through the API with a helper and three tool calls; every worker, helper and tool line carries its session, run and trace; the API's line has the request id and the same trace. Browser, in containers: the turn's lines in the workers' `docker logs`, and the API's access line, carry the chat's id |
| SC2 | **Logs ↔ traces** | ✅ Browser, on the observability stack: the turn's spans (API and worker) in Tempo, its lines from both in Loki under the same trace id, Grafana's links provisioned both ways, and **Open the trace** / **Its log lines** open in Grafana. Kubernetes: same provisioning, rendered and validated; the kind job runs in CI |
| SC3 | **Activity tells the truth** | ✅ Integration: totals, per-agent, per-model, per-tool and error numbers equal raw queries; test chats left out unless asked. Browser: a turn shows up in totals, lists and its own page; filters scope everything |
| SC4 | **Turn detail** | ✅ The turn's page shows its model calls per model (they add up to its model calls) and its timeline, including take-overs after a crash; the container e2e covers the crash itself |
| SC5 | **Audit** | ✅ Integration: each of 17 actions writes exactly one row; a blocked publish, a duplicate skill and a keyless provider write none; the API's user can't update, delete or truncate the trail; no key in any row or in the CSV |
| SC6 | **No secrets in logs** | ✅ A key in a message and in a tool's arguments appears in no line of a whole turn; in a log message, a field, a bound id and an exception, it's `[REDACTED]`; same for the OTLP copy and errors from the page |
| SC7 | **Still light** | ✅ Measured: Tempo 85 MiB, Loki 125 MiB, collector 75 MiB (about 285 MiB together). Observability stays optional; Activity needs none of it |
| SC8 | Quality | ✅ Backend 641 passed (coverage 92%), lint and types clean; UI 73; **browser suite 5×: 53/53 every time**; container e2e 4/4; the chart lints and renders |

## Bugs found while building

- **The resilience tests found which API replica serves a chat's stream from uvicorn's access line,** written when a response starts. Ours is written when it ends, which for a live stream is after the replica is killed. A stream now gets a line when it opens too.
- **Grafana sent anonymous viewers away from Explore,** so "Open the trace" landed on the dashboard. Viewers may use Explore now; dashboards stay read-only.
- **Model calls were counted twice in the metrics after a crash re-run** (L4a): now counted when the step commits, like the database.
- **An approval's policy decision was recorded twice:** the node runs again from its start after the decision. Now once (the test fails without the fix).
- **The kill-switch panel ignored agents switched off one by one:** a gauge for them, on the same panel.
- **"Used Ran Python"** in a turn's timeline: tool names that already say what happened stand alone.
- **A chart drawn as a scaled image** had 20 px axis labels on a wide screen and only the days that had data: it's now drawn at its real size, and the API returns every day in the range.

## Decisions

- **Tempo replaces Jaeger; Activity first; ratings in this phase** (2026-10-21, before building).
- **Log lines go to Loki over OTLP from the processes** (while building): Docker Desktop's default logging driver here is `local` (binary), and reading log files needs root and host or node mounts. The cost: a crash before the app is up is only in stdout. The Logs API is still `_logs` in the SDK, so it's used in one small handler rather than the SDK's deprecated `LoggingHandler`.
- **Tempo 2.10** (released 2026-08-13), not 3.x: its single-binary configuration is the well-trodden one; images pinned by digest, each at least two weeks old.

## Not done / next

- **The demo model with `--no-sandbox`** still calls Run Python for arithmetic (Nuria no longer has the calculator); the tool fails but the scripted reply says the answer anyway. Needs a choice: give Nuria the calculator back without a sandbox, or let the demo say it can't compute.
- Each finished reply asks for its rating separately when a chat opens: fine for chats of tens of turns; a long chat could get them in one request.
- Activity reads Postgres directly; the hosted beta will need hourly rollups and retention (P10). The endpoints are shaped so that can change underneath.
- Tempo's and Loki's memory on kind is taken from Compose; to measure on the cluster.
- **What agent platforms have that Nuria doesn't yet**, ranked, is in the plan's §7: MCP tools, ratings → evaluation sets, scheduled and webhook triggers, files and RAG, memory, guardrails, replay, model fallback and caching, accounts and quotas, an API and SDK.
