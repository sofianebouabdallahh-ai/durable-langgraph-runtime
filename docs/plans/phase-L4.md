# Phase L4 plan — Dashboards & local Kubernetes

**Goal:** someone running Nuria can **watch it work**.
- **L4a, dashboards:** `./setup.sh --observability` adds traces (Jaeger), metrics (Prometheus) and a Grafana dashboard. "What happened?" opens the turn's trace.
- **L4b, local Kubernetes:** `./setup.sh --kubernetes` runs the same images on a local multi-node cluster with Helm, probes, autoscaling and disruption budgets, plus demos that kill pods and drain nodes while a chat keeps going.

**Part of:** the [local release](local-release.md) (L1 ✅ → L2 ✅ → L3a–c ✅ → **L4** → L5 v0.1).

**Requirements:**
- **R2.7** trace propagation; **R7.1** tracing; **R7.2** metrics (with the CR-001, CR-003 and CR-005 additions);
- §10 for the local cluster: **R10.2–R10.12**, with **R10.13** (CI on kind) and **R10.14** (`docs/kubernetes.md`);
- **AC8:** one trace spans API → parent worker → child runs.

The cloud deploy (R10.15) is the hosted beta's (P16).

**Re-cut (recommended):** the roadmap budgeted L4 at 16–22 h, but tracing, metrics and the local cluster together are nearer **30 h**. Two slices, each with its own PR, like L3:

| Slice | What | Estimate | Done when |
|---|---|---|---|
| **L4a** | Observability in Compose: OpenTelemetry, `/metrics`, Grafana, JSON logs, the worker's health server, "open the trace" | ~10–13 h | **AC8**; the dashboard shows a live chat; `--observability` from a clean machine |
| **L4b** | Local Kubernetes: kind, the Helm chart, probes, KEDA, PDBs, pod security, demos, CI on kind | ~16–20 h | `--kubernetes` from a clean machine; pod-kill and upgrade demos PASS in CI |

---

## 1. Research findings

| Topic | Finding | Consequence |
|---|---|---|
| **What exists** | `runs.traceparent` exists but is never set. No OpenTelemetry dependency, no `/metrics`, plain-text logs. The API has `/healthz` and `/readyz` and drains on SIGTERM (R10.7); the worker has no HTTP server. Images are multi-stage, non-root, Trivy-scanned, on GHCR | L4a adds tracing, metrics, JSON logs and the worker's health server; L4b reuses the images as they are |
| **Tracing design** | OpenTelemetry's W3C `traceparent` is a string. Storing it on the run when it's created, and restoring it in whichever worker executes the run (or resumes it after a crash or an approval), keeps one trace across processes and time | Set at `POST /runs` **and** at a chat turn (the session API). Child runs inherit their parent's context; sub-agents are spans in the main run's worker (CR-005) |
| **Which spans** | Auto-instrumentation (FastAPI, psycopg, Redis, httpx) gives the plumbing; the meaningful spans are ours | Our own spans where the runtime already has hooks: `run` (executor), `node:{name}` (graph callbacks), `llm.call` (the model-call middleware: model, tokens, cost, cached), `tool:{name}` (the ToolPipeline: cached, epoch, decision), `subagent:{name}`. Auto-instrumentation only for FastAPI and httpx (model calls), to keep traces readable |
| **Cost when off** | The OpenTelemetry API is a no-op without an SDK and exporter | Tracing is configured **only** when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. The default stack is unchanged and pays nothing |
| **Metrics** | `prometheus_client` is the standard. The API is one process per container; the worker runs one process (`--workers 1`) | `/metrics` on the API, and on the worker's new `:8081` server, which also gives Kubernetes its probes (R10.5: liveness = the main loop ticked within 30 s; readiness = not draining). Counters and histograms where events happen; gauges (queue depth, pending, leases, sessions) read from Postgres and Redis on scrape |
| **Dashboards** | Grafana provisions data sources and dashboards from files | `infra/observability/`: collector config, Prometheus config, Grafana provisioning, and the dashboard JSON (R7.2: `ops/grafana/` in the original spec; kept under `infra/` like the rest) |
| **Logs** | R7.1: JSON logs with `run_id`, `epoch`, `trace_id` (and the pod on Kubernetes) on every line | A JSON formatter fed by context variables the executor sets per run; `LOG_FORMAT=json` (the default in Compose and Kubernetes, text for `make` in a terminal) |
| **Images to pin** | The project pins images by digest and tools by version, with a two-week cooldown | Jaeger v2 (OTLP built in), the OpenTelemetry Collector (contrib), Prometheus 3, Grafana, all pinned by digest at implementation time; Python packages through the existing uv cooldown |
| **Local cluster** (L4b) | R10.2: kind (1 control plane + 2 workers), ingress-nginx, metrics-server, KEDA, images loaded with `kind load`. Works the same on macOS, Linux and Windows | `./setup.sh --kubernetes` (and `make k8s-*`), Helm chart `deploy/helm/agent-runtime` with `values.yaml`, `values-kind.yaml` and `values-cloud.example.yaml`. Monitoring: a minimal Prometheus + Grafana in `values-kind.yaml` by default (kube-prometheus-stack is heavy on a 16 GB laptop), the full stack as an option |
| **Autoscaling** (L4b) | KEDA's Redis Streams scaler reads a consumer group's pending entries; workers are LLM-bound, so CPU is a misleading signal | A KEDA ScaledObject on `runs:work`/`workers` (min 1, max 8, cooldown 120 s); an HPA on CPU for the API (2 to 6) |

## 2. Design

```
 L4a (Compose, --observability)
   browser ─► ui ─► api ──(traceparent stored on the run)──► Postgres
                     │ spans                                  │
                     ▼                                        ▼
               otel-collector ◄── spans ── worker ── child runs / sub-agents
                 │        │                 │ :8081 /metrics /healthz /readyz
              Jaeger   (logs: JSON with run_id, epoch, trace_id)
   Prometheus ◄── scrape api:/metrics, worker:8081/metrics ──► Grafana (dashboard)

 L4b (kind, --kubernetes): the same images; Helm installs ui, api (HPA, PDB), worker (KEDA,
   PDB, Downward API), postgres + redis (StatefulSets), migrate Job (pre-install/upgrade hook),
   collector + Jaeger, Prometheus + Grafana, NetworkPolicies; restricted Pod Security.
```

### 2.1 L4a — observability
- **`telemetry.py`** (one module, Facade):
  - `configure(service)` installs the SDK only when an endpoint is set;
  - `inject()` / `extract(traceparent)` handle the W3C context;
  - `span(name, **attrs)` wraps our spans; Kubernetes resource attributes come from the Downward API (L4b) when present.
- **Run creation** (RunService, SessionService): store the current `traceparent` on the run. Child runs (`spawn_children`) and resumed runs keep it.
- **Executor:**
  - restore the context, then open the `run` span (attributes: run, graph, epoch, worker, reclaimed);
  - `node:{name}` spans from the graph's callbacks;
  - `llm.call` from the model middleware: model, tokens in and out, cost, cached, retries;
  - `tool:{name}` from the ToolPipeline: cached, decision, duration.
  - **Patterns:** Decorator and Observer, on the hooks that already exist; nothing new in agent code.
- **Metrics** (`metrics.py`, a Registry), covering R7.2 plus the CRs:
  - runs by status;
  - queue depth and pending entries; active leases;
  - reclaims vs graceful releases;
  - tool cache hit ratio; policy denials by reason;
  - LLM tokens and cost by model;
  - node latency histograms; turn latency;
  - stream subscribers per replica; active sessions;
  - sub-agents by outcome; budget warnings and breaches; loop detections;
  - the daily cost gauge; the kill switch;
  - replica counts (from the scrape targets).
- **Worker health server** (`:8081`): `/healthz` (the main loop ticked within 30 s), `/readyz` (not draining), `/metrics`.
- **Logs:** a JSON formatter carrying `run_id`, `epoch` and `trace_id` from context variables; `LOG_FORMAT=json|text`.
- **Compose profile `observability`:**
  - services: otel-collector, Jaeger, Prometheus, Grafana (anonymous viewer, local only);
  - ports bound to 127.0.0.1;
  - `./setup.sh --observability` (and `setup.ps1`) prints the links.
- **UI:**
  - **What happened?** gets "Open the trace" (Jaeger, by the run's trace id) when observability is on (`GET /about` says so);
  - the trace id appears in run views;
  - Grafana opens from the sidebar's model status area.

### 2.2 L4b — local Kubernetes
- **Cluster:** `deploy/kind/kind.yaml` (1 + 2 nodes, ingress port mappings). `./setup.sh --kubernetes` installs, in order:
  - ingress-nginx, metrics-server, KEDA (pinned versions);
  - `kind load`s the images;
  - creates the Secret from `.env` (`k8s-secrets`: never committed, never in values);
  - `helm upgrade --install`.
- **Helm chart** `deploy/helm/agent-runtime`, every object of R10.3–R10.11:
  - **workloads:** Deployments (ui ×2, api ×2 with HPA, worker with KEDA); the worker's pod name passed via the Downward API as `WORKER_ID`; StatefulSets (postgres, redis with AOF), each with a PVC;
  - **jobs:** migrate (pre-install and pre-upgrade hook), ingest; both with `backoffLimit` and `ttlSecondsAfterFinished`;
  - **routing:** an Ingress, with SSE timeouts of 3600 s and buffering off;
  - **config:** a ConfigMap and the Secret via `envFrom`, with a checksum annotation so a config change rolls the pods;
  - **health:** probes with documented timings;
  - **shutdown:** a preStop sleep of 5 s for the API; grace periods of 60 s (worker) and 30 s (API);
  - **disruption and placement:** PDBs (API `minAvailable: 1`, worker `maxUnavailable: 1`), topology spread across nodes, the API's rollout at `maxUnavailable: 0`;
  - **resources:** requests and limits, measured;
  - **security:** the restricted Pod Security Standard, a dedicated ServiceAccount without a token, and NetworkPolicies (default deny);
  - **observability:** the collector and Jaeger, Prometheus and Grafana (minimal by default).
- **Make targets** (each demo prints PASS/FAIL):
  - setup and teardown: `k8s-up`, `k8s-build`, `k8s-load`, `k8s-secrets`, `k8s-deploy`, `k8s-ingest`, `k8s-down`;
  - demos: `k8s-demo-podkill`, `k8s-demo-drain`, `k8s-demo-scale`, `k8s-demo-upgrade`.
- **CI:** a job that creates a kind cluster, installs the chart, runs a smoke turn, then podkill and upgrade; on failure it uploads events, logs and `describe` output.
- **`docs/kubernetes.md`:** every object (what, why, what breaks without it) plus the measured numbers.

## 3. Tasks

| # | Task | Verification |
|---|---|---|
| **L4a.1** | `telemetry.py`; traceparent at run and turn creation; restored in executors, child runs and resumes; our spans (run, node, llm.call, tool, subagent) | Integration with an in-memory span exporter: one trace id across API → worker → child runs; attributes present; nothing configured → no exporter, no overhead |
| L4a.2 | `metrics.py`; `/metrics` on the API; the worker's `:8081` server (`/healthz`, `/readyz`, `/metrics`) | Unit and integration: counters move with real runs; the worker's liveness fails when the loop stalls, readiness while draining |
| L4a.3 | JSON logs with run context | Unit: every line during a run carries run_id, epoch, trace_id |
| L4a.4 | Compose profile, configs, the Grafana dashboard, `setup --observability` | Container e2e: Jaeger's API returns the turn's trace with api and worker spans and the child runs' (**AC8**); Prometheus has both targets up; the dashboard's queries return data |
| L4a.5 | UI: "Open the trace", the Grafana link | Vitest; browser test with the profile up |
| L4b.1 | kind config, add-ons, `k8s-up` / `k8s-down`, image loading, secrets | A clean `k8s-up` on this Mac; teardown leaves nothing |
| L4b.2 | Helm chart: workloads, jobs, config, probes, shutdown, PDBs, spread, resources | `helm lint`, kubeconform; install, then upgrade, then rollback on kind |
| L4b.3 | KEDA and HPA; pod security; NetworkPolicies | Scale demo; the namespace enforces "restricted"; a pod outside the policy can't reach Postgres |
| L4b.4 | Monitoring in the cluster: collector, Jaeger, Prometheus, Grafana (+ pod, restart and KEDA panels) | AC8 on kind; dashboard panels with data |
| L4b.5 | Demos: podkill, drain, scale, upgrade (PASS/FAIL), with a chat running through each | Each 5×; measured hand-off times recorded |
| L4b.6 | CI on kind (smoke, podkill, upgrade; artifacts on failure); `docs/kubernetes.md`; `setup --kubernetes` | CI green; the doc's numbers measured |

## 4. Success criteria

| # | Criterion | How | Pass when |
|---|---|---|---|
| SC1 | **AC8: one trace** | A research run with child runs, and a chat turn with helpers, under `--observability` | Jaeger shows one trace: the API request → the parent worker's run → each child run's run (and the sub-agents), with node, llm.call and tool spans and their attributes; **5/5** |
| SC2 | **The trace survives a crash** | Kill the worker mid-turn | The reclaimed execution continues the same trace (a second `run` span, marked reclaimed) |
| SC3 | **Metrics tell the story** | A chat, a crash, an approval, a budget stop | The dashboard shows them: runs by status, a reclaim, tokens and cost by model, latency, queue depth |
| SC4 | **Off costs nothing** | The default stack (no `--observability`) | No collector traffic, no exporter threads; the suites' timings unchanged |
| SC5 | **Logs carry the context** | Any run | Every log line during it is JSON with run_id, epoch and trace_id |
| SC6 | **Worker probes** | Stall the worker's loop; drain it | Liveness fails after 30 s; readiness fails at once on drain |
| SC7 | **`--kubernetes` from clean** | A machine with Docker only | One command: the cluster, the chart, Nuria at a local URL, a smoke chat |
| SC8 | **Pod kill** | Kill the worker pod mid-turn | The chat completes, the screen matches the transcript; one reclaim; **5/5**, also in CI |
| SC9 | **Drain** | Drain a node with an api and a worker on it | No failed requests (PDBs, topology spread), the stream reconnects, the turn completes; hand-off time measured |
| SC10 | **Scale** | Queue 20 turns | KEDA adds workers (up to 8), then scales down without losing a run |
| SC11 | **Upgrade and rollback** | `helm upgrade` with a new image while a chat runs; then `helm rollback` | No failed request; the migration Job runs first; rollback restores the previous version |
| SC12 | **Pod security** | The namespace and pods | Restricted standard enforced; non-root, read-only root filesystem, no capabilities; NetworkPolicies block Postgres from outside api/worker/jobs |
| SC13 | Quality and docs | CI | Backend, UI, browser 5×, container e2e 5×, the kind job green; `docs/kubernetes.md` with measured numbers |

## 5. Risks

| Risk | Mitigation |
|---|---|
| A 16 GB laptop can't hold kind with full monitoring | A minimal Prometheus and Grafana by default; kube-prometheus-stack optional; resource requests measured; kind on 2 worker nodes only |
| Traces that are a wall of auto-instrumented spans | Our own spans carry the meaning; auto-instrumentation limited to FastAPI and httpx |
| Context lost across the queue | The traceparent travels in Postgres, on the run, not in the Redis message, so a reclaim or a resume always finds it |
| CI time on kind | One job, smoke + podkill + upgrade only, with artifacts on failure |
| Windows | kind and Helm work there too; `setup.ps1` gets the same flags; a real Windows run is still the carried-over follow-up |

## 6. Out of scope
- **The cloud deploy** (R10.15: AKS, managed Postgres/Redis, cert-manager): P16.
- **Hosted telemetry and SLOs** (P12).
- **Log shipping to a store** (Loki): the dashboard links traces, and logs stay in `docker logs` / `kubectl logs`.
- **The eval suite and its CI gate** (R7.3, AC9): a later phase.
