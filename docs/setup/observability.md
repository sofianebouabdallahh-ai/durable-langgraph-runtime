# Watch Nuria work: activity, logs, traces, metrics and a dashboard

**Activity** is built in: open **Activity** in the sidebar to see every chat and turn, what each one used and cost, and what went wrong. It reads Nuria's own database, so it needs nothing below.

One command adds four more things to Nuria running on your machine:

- **Traces** (Tempo): every step of a reply, from your message to the answer, across every process that worked on it.
- **Logs** (Loki): every log line, searchable by chat, turn, agent or tool, and linked to its trace.
- **Metrics** (Prometheus): counts and timings for runs, model calls, tools, helpers and guardrails.
- **A dashboard** (Grafana) that shows those metrics live, and where traces and logs are searched.

Nothing leaves your machine. Every port is bound to `127.0.0.1`.

## Built in: Activity, who changed what, and ratings

- **Activity** (sidebar): every chat and turn in the last 24 hours, 7 or 30 days; turns and spend per day by agent; each agent's turns, failures, median and slowest times, tokens, cost and ratings; each model and tool; what went wrong, grouped, with the latest example. A turn opens on its own page: its model calls per model and its timeline.
- **Who changed what** (Activity, top right): every change to agents, skills, models, settings and the kill switch, and every approval, newest first, with what it was before. **Download (CSV)** saves it. Nothing in the app can edit or delete it.
- **👍 / 👎** under each reply, with an optional reason for 👎. Click it again to take it back. Activity counts them per agent; they're kept with the agent's version, the start of evaluation sets later on.

## Turn it on

```bash
./setup.sh --observability          # Windows: .\setup.ps1 -Observability
```

Setup remembers the choice in `.env`, so a later `./setup.sh` keeps it. When it's ready, it prints the links:

| What | Where (default port) |
|---|---|
| Dashboard | http://localhost:3001/d/nuria |
| Traces and logs (Grafana Explore) | http://localhost:3001/explore |
| Metrics | http://localhost:9090 |

If one of those ports is taken, setup picks a free one and prints it.

To turn it off again:

```bash
./setup.sh --no-observability       # Windows: .\setup.ps1 -NoObservability
```

## Open a reply's trace and its log lines

1. In a chat, open **What happened?** under a reply. (Or open the turn from **Activity**.)
2. Click **Open the trace**. Grafana opens on that reply's trace.
3. Or click **Its log lines**: every line the turn wrote, from the worker, its helpers and its tools.

In Grafana, the two are linked both ways: a span's **Logs for this span** button shows the lines written in that trace, and a log line's **Open the trace** button opens the trace it belongs to.

You can read the trace from top to bottom:

```
POST /sessions/…/messages        api      your message arrives
└─ run                           worker   a worker picks up the turn
   ├─ node:model
   │  └─ llm.call                         model, tokens in and out, cost, attempts
   ├─ node:tools
   │  ├─ tool:calculator                  status, replayed (cached) or not
   │  └─ subagent:researcher              a helper, with its own model and tool calls
   └─ node:model
      └─ llm.call
```

**After a crash, the trace continues.** If a worker stops in the middle of a reply, another worker takes the turn over. The trace then shows a **second `run`** in the same trace, marked `run.reclaimed = true`. A paused reply works the same way: after an approval, a new `run` joins the trace.

**Child runs are part of the trace too.** A research run that fans out shows each child's `run` below the parent's.

The run's short trace id also appears at the bottom of **What happened?**, next to the run id.

## The dashboard

The **Nuria** dashboard opens from **Dashboard** at the bottom of the sidebar. It has five sections:

- **Right now:** API replicas and workers that are up, queued and running turns, turns waiting for a person, open live streams, active chats, today's spend, undelivered queue messages, and the kill switch.
- **Runs:** runs that ended and how, why runs failed, how long a turn takes (p50 and p95), crash take-overs and hand-offs.
- **Models:** tokens, spend and call latency, by model.
- **Steps, tools and helpers:** step latency, tool calls, how often a tool call was replayed instead of re-run, helpers by outcome, policy decisions and approvals, budget wrap-ups and stops, loop detection.
- **Processes:** runs in flight per worker, and which replicas Prometheus can reach.

Viewers need no login. To edit the dashboard, sign in as `admin` with `GRAFANA_ADMIN_PASSWORD` from `.env`. The dashboard itself is a file, [`infra/observability/grafana/dashboards/nuria.json`](../../infra/observability/grafana/dashboards/nuria.json): a change you want to keep goes there.

## Logs

Every container writes its logs as **JSON lines**, one per thing that happened. This doesn't need `--observability`.

**One id finds everything.** Each line carries the ids of what it belongs to:

| Where the line comes from | Its ids |
|---|---|
| An API request | `request_id` (also sent back as the `X-Request-ID` header), and `session_id` or `run_id` when the address has one |
| A turn, on a worker | `run_id`, `epoch`, `session_id`, `agent`, `agent_version`, `kind`, `worker` |
| A helper | the turn's ids, plus `helper` and `helper_handle` |
| A tool call | the turn's ids, plus `tool` and `tool_call_id` |

With tracing on, every line also has the `trace_id` and `span_id` of the step it was written in. So `session_id` finds a whole chat in every container's log, and `trace_id` leads from a line to its trace.

**What's logged:** a turn starting and ending (status, reason, steps, tokens, cost, time), each model call (model, tokens, cost, time, attempts), each tool call (status, reused or not, time), helpers starting and ending, approvals asked and decided, the kill switch, budget warnings, sandboxes created and removed, and one line per API request (method, route, status, time). The route is the template (`/sessions/{session_id}`), so lines group by endpoint.

**Never logged:** message text, tool arguments or results. Every line also goes through the same secret filter as tool results: an API key or a password in an error message becomes `[REDACTED]`.

```json
{"ts": "2026-10-21T04:18:04.191+00:00", "level": "INFO", "logger": "agent_runtime.tools.pipeline",
 "msg": "tool call: calculator success", "component": "worker", "run_id": "01a15cae-…", "epoch": 1,
 "session_id": "01a15cae-…", "agent": "chat", "agent_version": 4, "kind": "turn",
 "worker": "0b4e1580bbe5:7", "tool": "calculator", "tool_call_id": "call_1", "status": "success",
 "stage": "execute", "duration_ms": 2}
```

**Errors in the app's page** are logged too: the page sends them to the API, which writes them with `component=ui` (and the `X-Request-ID` of the call that failed, if one did). They stay on your machine.

To follow one chat across every container, in Grafana (**Explore → Loki**):

```
{service_name=~".+"} | session_id="<the chat id>"
```

Or without `--observability`:

```bash
docker compose -p agent-runtime logs --no-log-prefix api worker | grep '"session_id": "<the chat id>"'
```

The dashboard's **Logs** section shows warnings and errors by service, the turns that failed (each with its trace), and errors from the app's page.

Health checks and metric scrapes are left out of the access log.

## For developers

- **Off costs nothing.** Tracing starts only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (Compose sets it from `OTEL_ENDPOINT`, which setup fills in). Without it, no tracing SDK is installed, no traceparent is stored on runs, and nothing is exported.
- **How log lines reach Loki:** each process sends them to the collector over OTLP, beside its spans, as the same redacted fields it writes to stdout. Stdout stays the source of truth: if the collector is down, nothing that matters is lost. Nothing reads Docker's or Kubernetes' log files, so the collector needs no access to the host or the nodes.
- **Where the code is:** spans and their context are in [`telemetry.py`](../../backend/src/agent_runtime/telemetry.py); log lines, their ids and the formatter in [`logs.py`](../../backend/src/agent_runtime/logs.py); the access log in [`api/access.py`](../../backend/src/agent_runtime/api/access.py); every metric is declared once in [`metrics.py`](../../backend/src/agent_runtime/metrics.py).
- **Adding a log line:** `logs.event(log, "what happened", field=value, …)` writes one line with its numbers as fields; `with logs.bind(id=…):` adds ids to every line inside (and to the tasks it starts). Never put message text, tool arguments or results in either.
- **Scrape endpoints:** the API serves metrics at `/metrics`. Each worker's health server on `:8081` serves `/healthz`, `/readyz` and `/metrics` (`WORKER_HEALTH_PORT`; off by default on the host, where several workers share one machine).
- **Probes:**
  - **Liveness** fails when the worker's main loop hasn't ticked within `WORKER_LIVENESS_S` (30 s).
  - **Readiness** fails as soon as the worker starts draining.
- **Running from a terminal:** `make api` and `make worker` log as text. Set `LOG_FORMAT=json` to get JSON.

## Limits

- **Memory:** Tempo, Loki and the collector together take about 285 MiB (measured: 85, 125 and 75 MiB, with a few hundred turns stored). Prometheus about 60 MiB. Grafana is the largest.
- **Kept for 7 days** (Tempo, Loki and Prometheus, each on its own volume; 2 days on Kubernetes). `./setup.sh --reset` deletes them with everything else.
- **A killed worker loses its last second of spans and log lines.** Both are exported every second, so a worker killed by `SIGKILL` loses what it hadn't sent yet (its stdout still has the lines). The run itself is unaffected: it is taken over, and the trace continues.
- **Restarting Loki loses its last few minutes of lines** (up to 5): it keeps no write-ahead log, whose disk check would refuse every line once your disk is 90% full. The lines are still in each container's stdout.
- **A line written before the process is ready** (a crash at start) is only on stdout: the OTLP pipeline starts with the app.
- **Turn latency needs traffic.** It shows "No data" until a few turns have finished, because Prometheus computes it from rates.
- **Replaced Jaeger (L7b).** Traces used to open in Jaeger on port 16686; they're now in Grafana with the logs. Traces from before the update aren't carried over.
