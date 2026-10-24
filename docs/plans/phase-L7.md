# Phase L7 plan — See everything: logs, activity, audit

**Goal:** from any chat, reply or failure, find everything that happened, in one place, and
see at a glance what all agents are doing: sessions, turns, agents, tools, models, cost,
errors.

**Why:** today the pieces exist but don't meet (the map below).
- **Logs** are JSON lines with `run_id`, `epoch` and `trace_id`, but no session, agent,
  helper or tool; API requests carry nothing of ours; access logs are unstructured text;
  nothing ships logs anywhere (`docker logs` / `kubectl logs` only); the formatter doesn't
  redact.
- **Traces** reach Jaeger (in memory) but Grafana can't search them (Jaeger 2.x dropped the
  API Grafana's datasource uses), and logs and traces don't link.
- **Metrics** feed one Grafana dashboard, with no agent or session dimension (by design:
  bounded labels).
- **No product view:** there is no `GET /runs` list, `RunView` has no tokens, cost or agent,
  there's no Activity page, and per-model usage isn't stored per run.
- **No audit trail:** approvals record `decided_by: "local"` in run events; kill-switch, publish
  and settings changes leave no history.

**Requirements:** R7.1 (structured logs), R7.2 (metrics), R7.3 (traces), R2.7 (trace
continuity), R14.12 (redaction), R9.4 (security posture text); prepares P7 (audit, identity)
and P10 (retention).

---

## 1. Research findings (2026-10-21)

- **Correlate by context, not by search.** Bind ids (`trace_id`, `span_id`, session, run,
  agent, helper, tool, request) into `contextvars` at each boundary (HTTP request, work
  message, run, helper task, tool call); one log processor adds them to every line. Our
  `bind_run` already does this for `run_id`; it stops there.
- **Keep stdout JSON as the source of truth** (12-factor, works with no collector). Ship it
  with the OpenTelemetry Collector (`filelog` receiver) rather than Python's OTLP log bridge:
  its API is still under `_logs` (unstable) in 2026.
- **Loki** (single binary, label-indexed) is the light log store: a few hundred MB.
  OpenSearch (JVM, GBs) and ClickHouse (8 GiB minimum in Langfuse's sizing) are too heavy for
  a laptop. Loki 3 takes OTLP; `trace_id` goes in **structured metadata**, never a label.
- **Tempo** instead of Jaeger gives Grafana searchable traces with **trace ↔ logs** links both
  ways (`tracesToLogsV2`, Loki derived fields), provisioned in YAML.
- **GenAI semantic conventions** are still "Development" (moved to their own repo in June
  2026): use the names now (`gen_ai.operation.name`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.conversation.id`, `gen_ai.agent.name`,
  `gen_ai.tool.name`), pin the version, **never capture prompts or completions by default**.
- **LLM observability products** show the same few views: a sessions list, a per-turn tree
  (agent → model calls → tools → helpers), tokens and cost over time by model and agent,
  latency percentiles, error rates, feedback scores. Langfuse (MIT, but ~25 GiB of minimum
  allocations: Postgres, ClickHouse, Redis, S3) and Phoenix (ELv2, one ~1 GB container) can
  receive our spans; **neither replaces an in-app view** of data we already hold (budgets,
  approvals, the kill switch). Build the view in the app; offer Phoenix later as an optional
  profile.
- **Audit logs** are a separate append-only table (who, what, when, before/after, trace),
  not log lines.
- **Redaction** in two layers: at the source (our `redact()` in the log formatter, already
  used for tool args, transcripts and errors) and in the collector (`redaction` /
  `transform` processors).

## 2. Design

### 2.1 One id finds everything (L7a: logs)

| Boundary | Binds |
|---|---|
| HTTP request (middleware) | `request_id` (also returned as `X-Request-ID`), `trace_id`/`span_id`, `session_id` when the path has one |
| Work message / run | `run_id`, `epoch`, `session_id`, `agent`, `agent_version`, `kind`, `worker` |
| Helper task | `helper` (its name), `helper_handle` |
| Tool call | `tool`, `tool_call_id` |
| Model call | `model` (the binding: connection and model name) |

- **Every line:** `ts, level, logger, msg, component, pod`, plus whatever the context holds,
  plus `span_id`. Logged through `redact()`; `exc` too.
- **Access log:** our own middleware line (`method`, route template, `status`, `duration_ms`,
  `request_id`), replacing uvicorn's text line (probes still filtered).
- **What gets logged** (INFO, one line each, no content): a turn started/ended (status, reason,
  steps, tokens, cost, duration), each model call (model, tokens, latency, attempts), each
  tool call (tool, status, cached, duration), each helper (spawned, ended), approvals asked
  and decided, kill-switch changes, budget warnings and breaches, sandbox create/remove.
  **Never** message text, tool arguments or results.
- **UI errors:** an error boundary and `window.onerror`/`unhandledrejection` post
  `{message, stack, route, request_id}` to `POST /client-errors` (rate-limited, redacted),
  logged as `component=ui`. Nothing leaves the machine.
- **Spans** get the GenAI names alongside ours, plus agent, version, session and cost on `run`.

### 2.2 Find it in Grafana (L7b: shipping)

- **Compose** (`--observability`): **Loki** (single binary, pinned, 7-day retention) and
  **Tempo** replacing Jaeger (local storage, 7 days). The collector gains a `logs` pipeline:
  ~~`filelog` over Docker's json-file logs~~ OTLP from the processes (Decision 4), the
  service as `service_name`, every field and `trace_id` as structured metadata, a second
  redaction net (`attributes` processor).
- **Grafana:** Loki and Tempo datasources; **trace → logs** (`tracesToLogsV2` on
  `trace_id`) and **log → trace** (derived field); a "Logs" row on the Nuria dashboard
  (errors by component, recent failures with their trace).
- **Kubernetes** (`monitoring.enabled`): ~~the collector as a DaemonSet with `filelog` over
  `/var/log/pods`~~ the same OTLP path (Decision 4); Loki and Tempo as single-replica
  StatefulSets; same provisioning.
- The UI's **Open the trace** and **logs for this turn** links open Grafana Explore at the
  trace, and at the turn's `run_id` for its lines ("Its log lines").
- Off by default, as today: without `--observability`, logs stay on stdout and the in-app
  Activity page (below) works on its own.

### 2.3 Activity: what all agents are doing (L7c: the in-app dashboard)

A new **Activity** page (sidebar), from Postgres, always available (no observability
profile needed). Range: 24 h · 7 d · 30 d; filter by agent; test chats in or out.

| Section | Shows |
|---|---|
| **Now** | turns running, waiting for approval (with Approve links), queued, agents switched off, spend today |
| **Totals** | chats, turns, failed turns (rate), tokens, cost, tool calls, helper runs, approvals |
| **Over time** | turns and cost per day, by agent (stacked) |
| **Agents** | each agent: turns, failure rate, median and p95 turn time, tokens, cost, top tools; link to the Studio |
| **Models** | each model: calls, tokens in/out, cost, p50/p95 latency, retries and errors |
| **Tools** | each tool: calls, failure rate, cache hits, p95 duration; approvals asked/approved/rejected |
| **Sessions** | every chat: agent, messages, tokens, cost, last activity, status; click → the chat |
| **Turns** | every run: when, agent and version, model(s), status and reason, steps, tools, tokens, cost, duration, reclaims; click → **turn detail** |
| **Errors** | failures grouped by reason and agent, with the latest examples |

- **Turn detail:** the tree of model calls, tools, helpers, approvals and errors, from run
  events (what *What happened?* shows, larger), with the trace and logs links when
  observability is on.
- **Backend:**
  - `GET /runs` (filters: agent, status, reason, session, kind, range; cursor);
  - `GET /activity/summary?range=&agent=`; `GET /activity/series?metric=&by=&range=`;
  - `GET /sessions` gains `agent`, `include_tests`, `range`;
  - `RunView` gains agent, version, tokens, cost, model calls, tool calls.
- **Per-model usage per turn:** a `run_model_usage` table (run, model, calls, tokens in/out,
  cost, latency), written with each model call **in the step's transaction**. That also fixes
  L4a's known double count after a re-run.
- **Indexes:** `runs (created_at)`, `runs (agent_name, created_at)`,
  `run_events (type, ts)`.

### 2.4 Who did what (L7d: audit, feedback)

- **`audit_events`** (append-only; insert-only grants like skill versions): `at, actor,
  action, target, before, after, request_id, trace_id`. Written in the **same transaction**
  as the change (Unit of Work). The actor is `local` today; a user id after P7.
- **Actions:** approval decided, kill switch on/off (one agent, all), agent
  created/published/restored/archived/imported, skill created/updated/archived, model
  connection added/changed/removed, default model changed, tool settings changed (search
  provider, key set: fingerprint only, allowlist), usage sharing on/off, data restored.
- **Activity → Audit:** a filterable list, and Download (CSV).
- **Feedback:** 👍 / 👎 (with an optional reason) on each reply, stored per run and agent
  version; shown per agent in Activity. It's the seed of the evaluation sets later on.

### 2.5 Fixes from the map
- The kill-switch gauge reads per-agent switches too; `runtime_worker_inflight` is set.
- L4a's double counts: the policy decision counted twice, and model usage after a re-run
  (2.3).

## 3. Tasks

| # | Task | Est. |
|---|---|---|
| L7a | Log context (contextvars at every boundary), access-log middleware, redaction in the formatter, the INFO lines, client errors, GenAI span names | ~8 h |
| L7b | Loki + Tempo + collector logs pipeline (Compose, Helm), Grafana links both ways, Logs row, UI links | ~8 h |
| L7c | `run_model_usage`, `GET /runs`, activity endpoints, indexes; the Activity page, turn detail | ~12 h |
| L7d | `audit_events` + writes + page; feedback 👍/👎; the gauge and double-count fixes | ~5 h |
| L7e | Tests (below), docs (observability guide, security, Kubernetes, design), summary | ~5 h |

**Estimate:** about 35–40 h. Each sub-phase ships on its own; L7c (the Activity page) can go
first if you want the dashboard soonest.

## 4. Success criteria

| # | Criterion | How it's checked |
|---|---|---|
| SC1 | **One id finds everything** | A turn with a helper and two tools: every API, worker, helper and tool log line for it carries its `session_id`, `run_id` and `trace_id` (integration test over captured logs) |
| SC2 | **Logs ↔ traces** | In Grafana, from a trace to its log lines and back (provisioned links; browser test on the observability stack, Compose and kind) |
| SC3 | **Activity tells the truth** | Its totals, per-agent, per-model and per-tool numbers equal queries over the raw tables for a seeded history (integration); the page renders them (browser) |
| SC4 | **Turn detail** | Model calls, tools, helpers, approvals and errors in order, for a turn with a crash and a reclaim |
| SC5 | **Audit** | Every listed action writes exactly one audit row in its own transaction; a failed change writes none; the API can't update or delete rows |
| SC6 | **No secrets in logs** | Planted keys and passwords in messages, tool args, errors and exceptions appear in no log line and no span |
| SC7 | **Still light** | Loki + Tempo + collector memory measured; observability stays optional; the Activity page needs none of it |
| SC8 | Quality | Backend, UI, browser 5×, container e2e, the kind job green |

## 5. Risks

- **Docker Desktop's log path** (`/var/lib/docker/containers` inside its VM) differs by
  platform. Spike first; fallback: the Docker Loki logging driver, or the Python OTLP log
  bridge behind a flag.
- **Aggregations on Postgres** are fine for one machine; the hosted beta will need rollups
  (hourly tables) and retention (P10). The endpoints are shaped so that can change underneath.
- **Tempo replacing Jaeger** changes the trace link people know (`localhost:16686`). The
  Jaeger UI could stay beside it for a release.

## 6. Decisions (2026-10-21)

1. **Tempo replaces Jaeger:** Grafana searches traces, and trace ↔ logs links go both ways.
2. **The Activity page first:** L7c, then L7a/L7b (logs), then L7d.
3. **Feedback 👍/👎 is in this phase,** shown per agent in Activity: the start of evaluations.
4. **Log lines reach Loki over OTLP from the processes, not from log files** (decided while
   building L7b, from the spike in §5): Docker Desktop's default logging driver here is `local`
   (binary files, no JSON for `filelog`), and reading `/var/lib/docker/containers` or
   `/var/log/pods` needs root in the collector and host or node mounts. Each process instead
   sends the same redacted fields it writes to stdout, beside its spans; stdout stays the
   source of truth. One path for Compose and Kubernetes, no DaemonSet, no host access. The
   cost: lines written before the app is up (a crash at start) are only on stdout, and the
   Logs API is still `_logs` in the SDK, so it's used in one small handler (`logs.OtlpHandler`)
   instead of the SDK's deprecated `LoggingHandler`.

---

## 7. Beyond this phase: what agent platforms have that Nuria doesn't (yet)

Ranked for a laptop-first platform heading to a hosted beta (research 2026-10-21):

| # | Capability | Why | Effort |
|---|---|---|---|
| 1 | **MCP client** (agents use tools from MCP servers) | The standard way tools are shared now (Linux Foundation, spec 2026-07-28); thousands of servers. Through our approvals and sandbox | M |
| 2 | **Feedback → evaluations** (datasets per agent, LLM-as-judge, regression runs before publishing) | "Did this change make my agent worse?" is the question after versioning | M |
| 3 | **Scheduled and triggered agents** (cron, inbound webhooks) | A durable runtime's natural next step: agents that run without a chat | S–M |
| 4 | **Files: uploads to chats, knowledge bases (RAG), file outputs** | The most common ask after tools; pgvector is already there | M–L |
| 5 | **Long-term memory** (per user, across chats, viewable and deletable) | Agents that remember preferences | M |
| 6 | **Guardrails** (input/output checks, PII detection, injection screening of tool output) | OWASP Agentic Top 10; we have the sandbox and approvals already | M |
| 7 | **Replay and fork from a checkpoint** (time travel) | Debugging; LangGraph checkpoints make it cheap | M |
| 8 | **Model fallback and prompt caching** | Resilience and cost | S–M |
| 9 | **Accounts, roles and quotas** | Required before the hosted beta (P7) | L |
| 10 | **Public API/SDK and outbound webhooks** | Embedding agents in other apps | M |
| — | Later: agent-to-agent (A2A), voice, browser use | Emerging or costly | L |

**Recommendation:** after L7, **MCP client** (L8), then **scheduled/webhook triggers** and
**feedback → evaluations**, then files and RAG, before the hosted beta's accounts.
