# Phase L4a — Watch it work: traces, metrics, a dashboard

**Completed:** 2026-10-18 · **Branch:** `feat/l4-dashboards-kubernetes` · **Plan:** [plans/phase-L4.md](../plans/phase-L4.md) (slice L4a) · **Guide:** [Watch Nuria work](../setup/observability.md) · **Tests:** backend 546 (+20; coverage 92.2%) · UI unit 57 (+3) · browser 2 new scenarios

## What we built

**`./setup.sh --observability`** turns on the Compose profile `observability`. It adds four services:

- the OpenTelemetry Collector;
- Jaeger, for traces;
- Prometheus, for metrics;
- Grafana, with the **Nuria** dashboard.

All four are pinned by digest, bound to `127.0.0.1`, and at least two weeks old. Setup prints the links and remembers the choice; `--no-observability` turns it off. `setup.ps1` has the same flags.

**One trace per turn, across processes and time (AC8).** The W3C context is stored on the run (`runs.traceparent`) when the run is created. That context is the API request's span, or, for a child run, its parent's `run` span. Whichever worker executes the run restores it, so the trace continues:

- after a crash: a second `run` span, marked reclaimed;
- after an approval;
- in a parent re-queued by its children.

Our own spans carry the meaning:

- `run` (graph, epoch, worker, reclaimed, outcome);
- `node:{name}`;
- `llm.call` (model, tokens, cost, attempts);
- `tool:{name}` (status, replayed or not);
- `subagent:{name}`, below the node that spawned it, with the helper's own calls below it.

Only FastAPI and httpx are auto-instrumented.

**Metrics** are declared once, in `metrics.py`.
- **From events:** most counters come from committed events, at the one place they all pass after COMMIT (`publish_events`). An event is counted exactly once, and a fenced write never.
- **Where they happen:** model usage, run latency and budget warnings are recorded at the point they occur.
- **Polled:** state gauges (queue, leases, waiting runs, chats, today's spend, the kill switch) are read from Postgres and Redis every 5 s.
- **Endpoints:** the API serves `/metrics`, and each worker serves its own on `:8081`.

**The worker's health server** (`:8081`) serves `/healthz`, `/readyz` and `/metrics`.
- **Liveness** means "the read loop ticked within 30 s".
- **Readiness** drops at once on SIGTERM.
- Compose now health-checks workers, and L4b's probes will use the same endpoints.

**JSON logs** in containers: every line during a run carries `run_id`, `epoch` and `trace_id`. Probe and scrape requests are left out of the access log.

**UI:**
- **Open the trace** under "What happened?", and the run's trace id;
- **Dashboard** at the bottom of the sidebar.

**Off costs nothing.** Without `OTEL_EXPORTER_OTLP_ENDPOINT`, no SDK is installed, no traceparent is stored, and nothing is exported.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | **AC8: one trace** | ✅ Integration: a fan-out (request → parent `run` ×2 → three children's `run`) and a turn with a helper (node → `llm.call` / `tool:*`; `subagent:mathematician` under `node:tools`, its own `llm.call` and `tool:calculator` below it), one trace each. **In containers**, through the UI's proxy: the same trees in Jaeger, with spans from the `api` and `worker` services and children executed on two different worker containers. Browser: a chat turn's trace has api and worker spans, `llm.call` and `tool:calculator` |
| SC2 | **The trace survives a crash** | ✅ Integration (task cancelled mid-run), and in containers (`docker kill -s KILL` on the owning worker): the reclaimed execution is a second `run` in the same trace, under the same request, `run.reclaimed=true`, epoch 2, another worker |
| SC3 | **Metrics tell the story** | ✅ In containers: a chat, a crash, an approval and a budget stop show as runs by outcome (`failed` / `budget:tokens`), a reclaim, an approval, a wrap-up warning and a breach; every dashboard query evaluates in Prometheus |
| SC4 | **Off costs nothing** | ✅ Unit and integration: no endpoint → `configure` installs nothing, no traceparent is stored, the run view has no trace id. The existing 526 backend tests pass unchanged with tracing off |
| SC5 | **Logs carry the context** | ✅ Integration: every line about a run is JSON with its `run_id`, `epoch` and `trace_id`; seen in `docker logs` of the workers |
| SC6 | **Worker probes** | ✅ Unit, over real HTTP: liveness 503 once the loop is 31 s stale; readiness 503 before the first tick and at once on drain (while liveness stays 200); a taken port is logged, never fatal. Compose health-checks the workers |
| SC13 (L4a part) | Quality and docs | ✅ Backend lint, mypy strict, 546 tests, coverage 92.2%; UI check (57 unit tests); the full browser suite (31 tests) passes with the profile up; CI turns the profile on before the browser tests; guide, design patterns, changelog |

## Bugs and surprises found by testing

- **Port 8081 clashed on the host.** The supervisor (`--workers N`) and the e2e tests start several workers on one machine, and the second one failed to bind. The health server is now off by default (on in containers, one worker per container), and a taken port is logged, never fatal.
- **Jaeger 2.21 serves only its v3 query API** (`/api/v3/...`). Grafana's Jaeger data source calls the old one and got 404, so it was dropped. The dashboard links to Jaeger's own UI instead, as "Open the trace" does.
- **A SIGKILLed worker lost its unexported spans** with the default 5 s batch. Spans are now exported every second.
- **ASGI `http receive` / `http send` spans** cluttered every request trace; they're excluded.
- **The API's own zero `runtime_worker_inflight`** showed on the dashboard; the panel now reads the worker job only.

## Known limitations

- Traces live in Jaeger's memory (a restart forgets them).
- The dashboard's Jaeger link assumes port 16686.
- Turn latency needs a few turns before it shows.
- An approval's `require_approval` policy decision is counted twice. The resumed step re-emits its audit event, which is existing behaviour of the event log.
- Model usage is counted when a response arrives, so a step lost to a crash and re-run is counted twice. That matches what was paid; budgets count it once.

## Next

L4b, local Kubernetes: kind, the Helm chart (probes on the worker's new `:8081`), KEDA, PDBs, pod security, demos, CI on kind.
