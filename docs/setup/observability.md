# Watch Nuria work: traces, metrics and a dashboard

One command adds three things to Nuria running on your machine:

- **Traces** (Jaeger): every step of a reply, from your message to the answer, across every process that worked on it.
- **Metrics** (Prometheus): counts and timings for runs, model calls, tools, helpers and guardrails.
- **A dashboard** (Grafana) that shows those metrics live.

Nothing leaves your machine. Every port is bound to `127.0.0.1`.

## Turn it on

```bash
./setup.sh --observability          # Windows: .\setup.ps1 -Observability
```

Setup remembers the choice in `.env`, so a later `./setup.sh` keeps it. When it's ready, it prints the links:

| What | Where (default port) |
|---|---|
| Dashboard | http://localhost:3001/d/nuria |
| Traces | http://localhost:16686 |
| Metrics | http://localhost:9090 |

If one of those ports is taken, setup picks a free one and prints it.

To turn it off again:

```bash
./setup.sh --no-observability       # Windows: .\setup.ps1 -NoObservability
```

## Open a reply's trace

1. In a chat, open **What happened?** under a reply.
2. Click **Open the trace**. Jaeger opens on that reply's trace.

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

Every container writes its logs as **JSON lines**. While a run executes, each line carries its `run_id`, `epoch` and `trace_id`, so a line from `docker logs` leads to the trace:

```json
{"ts": "2026-10-18T17:23:05.745+00:00", "level": "INFO", "logger": "agent_runtime.runs.executor",
 "msg": "run 01a15009-…: failed (budget:tokens)", "component": "worker",
 "run_id": "01a15009-…", "epoch": 1, "trace_id": "ce79df650ef9c75e10e4907a94d7d806"}
```

This doesn't need `--observability`. Health checks and metric scrapes are left out of the access log.

## For developers

- **Off costs nothing.** Tracing starts only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (Compose sets it from `OTEL_ENDPOINT`, which setup fills in). Without it, no tracing SDK is installed, no traceparent is stored on runs, and nothing is exported.
- **Where the code is:** spans, context and JSON logs are in [`telemetry.py`](../../backend/src/agent_runtime/telemetry.py); every metric is declared once in [`metrics.py`](../../backend/src/agent_runtime/metrics.py).
- **Scrape endpoints:** the API serves metrics at `/metrics`. Each worker's health server on `:8081` serves `/healthz`, `/readyz` and `/metrics` (`WORKER_HEALTH_PORT`; off by default on the host, where several workers share one machine).
- **Probes:**
  - **Liveness** fails when the worker's main loop hasn't ticked within `WORKER_LIVENESS_S` (30 s).
  - **Readiness** fails as soon as the worker starts draining.
- **Running from a terminal:** `make api` and `make worker` log as text. Set `LOG_FORMAT=json` to get JSON.

## Limits

- **Traces are kept in memory.** Restarting Jaeger forgets them. Prometheus keeps 7 days of metrics.
- **A killed worker loses its last second of spans.** Spans are exported every second, so a worker killed by `SIGKILL` loses the spans it hadn't sent yet. The run itself is unaffected: it is taken over, and the trace continues.
- **Turn latency needs traffic.** It shows "No data" until a few turns have finished, because Prometheus computes it from rates.
- **The dashboard's Jaeger link uses port 16686.** If setup moved Jaeger to another port, the dashboard's "Traces (Jaeger)" link won't match. Nuria's own "Open the trace" link always uses the right port.
- **Traces aren't searchable in Grafana.** Jaeger 2.21 only offers its newer query API, which Grafana's Jaeger plugin doesn't use. Open traces in Jaeger instead.
