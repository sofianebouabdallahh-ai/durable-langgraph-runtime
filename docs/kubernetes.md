# Nuria on Kubernetes

Nuria runs the same images on a local multi-node cluster ([kind](https://kind.sigs.k8s.io/)) as it does in Compose. This page covers:
- how to start the cluster;
- every Kubernetes object the charts create: what it is, why it's there, and what breaks without it (R10.14);
- the numbers measured on this cluster.

The cloud deployment (managed Postgres and Redis, TLS, a real domain) comes with the hosted beta (P16). [`values-cloud.example.yaml`](../infra/helm/agent-runtime/values-cloud.example.yaml) is its starting point.

## Start it

```bash
./setup.sh --kubernetes            # Windows: .\setup.ps1 -Kubernetes (needs Git Bash or WSL)
```

You only need Docker. Setup checks Docker, creates `.env`, asks which model to use, and runs [`infra/kind/cluster.sh all`](../infra/kind/cluster.sh). That script:

1. **Downloads the tools.** kind, Helm and kubectl, at pinned versions with verified checksums, go into `.tools/bin` in this folder ([`tools.sh`](../infra/kind/tools.sh)). Nothing is installed system-wide.
2. **Creates the cluster.** It has one control plane and two worker nodes ([`kind.yaml`](../infra/kind/kind.yaml)). Its credentials go in `.tools/kubeconfig`, not in `~/.kube/config`.
3. **Installs the add-ons**, pinned:
   - **Traefik**, the Ingress controller;
   - **metrics-server**, CPU readings for the API's autoscaler;
   - **KEDA**, which scales workers on the work queue.
4. **Builds the images** and copies them into the nodes. They are never pulled from a registry.
5. **Creates the Secret** from the secret keys of `.env`. It is never written to a file in the repository, and never put in the chart's values.
6. **Installs two Helm releases:**
   - `nuria-data`: Postgres and Redis;
   - `nuria`: the migrate Job first, then everything else.
7. **Runs a real chat turn** through the Ingress.

When it finishes:

| What | Where |
|---|---|
| Nuria | http://localhost:8090 |
| Dashboards | http://grafana.localhost:8090/d/nuria, and **Nuria on Kubernetes** (pods, restarts, autoscaling) |
| Traces | http://jaeger.localhost:8090 (or **Open the trace** under a reply's "What happened?") |

**Step by step:** `make k8s-up`, `k8s-build`, `k8s-load`, `k8s-secrets`, `k8s-deploy`.

**Status and teardown:**
- `make k8s-status` shows nodes, pods and autoscalers.
- `make k8s-down` deletes the cluster and everything in it.

**Port:** set `K8S_PORT` to use another port than 8090.

## Demos

Each demo disturbs the cluster while a chat turn is running, then prints PASS or FAIL. A turn passes when it completed, has no duplicate message, and did its side effect exactly once ([`k8s_e2e.py`](../backend/tests/e2e/k8s_e2e.py)).

| Demo | What it does | Measured on this Mac (8 GB for Docker) |
|---|---|---|
| `make k8s-demo-podkill` | Force-deletes the worker pod running the turn: no grace period, like a crash | Another worker reclaims the turn after **31–33 s** (3 runs): the lease (30 s) has to expire first. One reclaim, no duplicates |
| `make k8s-demo-drain` | Drains the node running that worker. In the measured run, that node also had **both** API pods | The drain took **24 s**. **0 failed requests out of 117** (a request every 200 ms through the Ingress). The worker handed the run off, and another node picked it up **0.03–0.07 s** later (3 runs). No reclaim |
| `make k8s-demo-scale` | Queues 24 slow runs | KEDA went from **2 to 5 workers**. Every run completed, and the workers went back to 2 after the stabilization window |
| `make k8s-demo-upgrade` | Runs `helm upgrade` to a new image mid-turn, then `helm rollback` | The migrate Job ran first. The turn completed, and **0 failed requests out of 115** during both |
| `make k8s-demo-security` | Checks pod security and the network policies | The namespace refuses a privileged pod. Every component runs non-root, read-only, with no capabilities and no token. A pod outside the policies times out reaching Postgres; the API connects |

CI runs `security`, `podkill` and `upgrade` on a fresh kind cluster for every pull request. When one fails, it uploads the events, the pods' logs and `describe` output.

## The objects, one by one

### The cluster ([`infra/kind/`](../infra/kind/))

| Object | Why | Without it |
|---|---|---|
| **3 nodes** (1 control plane, 2 workers) | Pods spread across nodes, so a node can be drained while Nuria keeps answering (R10.2) | One node is one failure domain: a drain is an outage |
| **Port mapping** 127.0.0.1:8090 → the control plane's port 80 | The one way in, from this machine only | You'd need `kubectl port-forward`, which doesn't survive a pod restart |
| **Traefik** (instead of ingress-nginx) | Reads standard Ingress objects and never buffers responses. ingress-nginx is retired: no release since March 2026 | No Ingress controller, so no way in |
| **metrics-server** | The API's HPA needs CPU readings | The HPA shows `<unknown>` and never scales |
| **KEDA** | Scales workers on the work queue | Workers stay at a fixed count however long the queue gets |

### Data stores ([`infra/helm/nuria-data`](../infra/helm/nuria-data/), local only)

| Object | Why | Without it |
|---|---|---|
| **Postgres StatefulSet** with its own volume | The source of truth: runs, events, checkpoints, chats, agents (R10.9) | Nothing survives a restart |
| **Redis StatefulSet** with AOF, with its own volume | The work queue and live streams. AOF keeps pending messages through a restart. Everything in it can be rebuilt from Postgres | A Redis restart costs a relay sweep (≤ 30 s) before queued runs move again |
| **Both on the control-plane node** (`nodeSelector`, toleration) | Their volumes are local to one node. Off the worker nodes, a worker-node drain can't take them down | The first drain demo did take Redis down: every request failed until the node came back |
| **PDBs with `maxUnavailable: 0`** | A drain of their own node waits instead of evicting them | A drain silently stops the database |
| **Separate chart** | The migrate Job is a pre-install hook, which runs before anything else in its release exists, including a Postgres in the same release. In the cloud, the data stores are managed services and this chart isn't installed | The first install deadlocks: the hook waits for a database that isn't created yet |

### Nuria ([`infra/helm/agent-runtime`](../infra/helm/agent-runtime/))

| Object | Why | Without it |
|---|---|---|
| **Migrate Job**: a `pre-install,pre-upgrade` hook running `runtime db init`, with `backoffLimit: 3`, `ttlSecondsAfterFinished: 600` and `activeDeadlineSeconds: 300` | The schema and the per-component database logins are ready before any new pod starts (R10.6). Migrations are expand/contract, so old pods keep working while it runs | New code meets an old schema mid-rollout |
| **ConfigMap** through `envFrom`, with a checksum on the pods | The non-secret configuration (R9.1, R10.4). A change rolls the pods | Pods keep running on stale settings until something restarts them |
| **Secret** `nuria-secrets` (created by `cluster.sh`) | Passwords and keys. Each component reads **only its own** database password by `secretKeyRef` (least privilege, R14.13) | Secrets would end up in values, in Git, or in every pod |
| **UI Deployment** (×2) with a Service and a PDB (`minAvailable: 1`) | Serves the app and proxies `/api`, as in Compose | — |
| **API Deployment** (×2): `maxUnavailable: 0`, a 5 s `preStop` sleep, a 30 s grace period | Several replicas, and any of them serves any stream. In a rollout, a new pod is ready before an old one leaves. The sleep lets every node remove the old endpoint before the pod stops taking traffic (R10.7) | Requests fail during every rollout |
| **API probes**: startup on `/healthz` (up to 60 s), liveness on `/healthz` every 10 s, readiness on `/readyz` every 3 s | Liveness never checks dependencies, so a Postgres blip doesn't restart every pod. Readiness fails at once when the pod drains (R10.5) | Either cascading restarts or traffic to a pod that is shutting down |
| **API HPA**: 2 to 6 replicas at 70 % CPU | The API's work is CPU: JSON and stream fan-out (R10.8) | A traffic spike queues on two pods |
| **API PDB** (`minAvailable: 1`) | A drain evicts API pods one at a time | A drain can evict both API pods at once: an outage. With the PDB, the measured drain of a node holding both had 0 failed requests |
| **Headless Service** `nuria-api-pods` | One DNS record per **ready** API pod. The UI's nginx re-resolves it every 2 s and retries the next pod, exactly as in Compose (AC20) | The proxy sticks to one address and can't retry another pod |
| **Worker Deployment**: `WORKER_ID` = the pod's name (Downward API), a 60 s grace period | The pod name is the lease owner (R2.2). On SIGTERM a worker finishes its current step and hands its runs off within 50 s (R10.7) | Every shutdown becomes a crash: a 30 s reclaim instead of a 0.07 s hand-off |
| **Worker probes** on its health server (`:8081`) | Liveness means "the read loop ticked within 30 s", so a wedged loop is restarted. Readiness drops at once on drain | A stuck worker holds its slots forever |
| **KEDA ScaledObject**: 2 to 8 workers, one more per 4 queued messages, scale-down one pod per 30 s after 120 s | Workers wait on models, so CPU says nothing about load. The queue backlog does (R10.8) | A CPU-based HPA never scales workers |
| **Worker PDB** (`maxUnavailable: 1`) | Drains and node upgrades take one worker at a time | Several workers released at once: everything is still handed off, but with half the capacity |
| **Topology spread** (`ScheduleAnyway`) | Replicas land on different nodes (R10.11). `ScheduleAnyway` lets pods still schedule when only one node is left | One node holds all replicas, and its drain is an outage |
| **Ingress** (class `traefik`) | `/` → the UI; with monitoring, `grafana.localhost` and `jaeger.localhost`. Streams go straight through: Traefik doesn't buffer, the UI's nginx has buffering off and a 1 h read timeout (R10.3) | No way in |
| **ServiceAccount**, no token mounted | Nuria's pods never call the Kubernetes API (R10.10) | A compromised pod finds cluster credentials on disk |
| **Restricted Pod Security** (namespace label): every pod non-root, `seccomp: RuntimeDefault`, no privilege escalation, every capability dropped, read-only root filesystem (writes only to `/tmp` emptyDirs) | The baseline that makes a container escape hard (R10.10) | The namespace would accept a privileged pod |
| **NetworkPolicies**: default deny, then DNS for everyone. UI ← Traefik; UI → API; API ← UI and Prometheus. Postgres ← API, workers and migrate only; Redis ← API, workers and KEDA | A pod that shouldn't talk to the database can't (R10.10) | Any pod in the namespace reaches Postgres. The `security` demo's intruder pod would connect |

### The agents' tools (L6; `search`, `fetcher`, `sandbox` in values)

| Object | Why | Without it |
|---|---|---|
| **SearXNG Deployment** + Service, its settings from a ConfigMap (the same file as Compose: [`files/searxng-settings.yml`](../infra/helm/agent-runtime/files/searxng-settings.yml)) | Web search with no key. Runs as SearXNG's own user (977), read-only root, its cache in an emptyDir | Search the web needs a key (Tavily, Brave) |
| **Page reader Deployment** (×2) + Service + PDB | The one way tools reach the web. It refuses private and internal addresses itself | — |
| **NetworkPolicies** for both: in from the workers (and the API for SearXNG's test search); **out to public addresses only** (every private, link-local, loopback and carrier-grade NAT range excepted) | A page can't send the reader to Postgres, a pod or cloud metadata, even if its own checks had a gap. Verified with the reader's checks bypassed: Postgres, Redis and the API time out, the internet answers | One bug in the reader is an SSRF into the cluster |
| **sandboxd Deployment** (×2) + Service + PDB, `SANDBOX_DRIVER=kubernetes` | Starts one sandbox **Pod** per run and epoch and runs code in it through the exec API (argv on stdin, so big files and code fit). No Docker socket anywhere. Pods are named by run and epoch, so two replicas asking at once get the same one | — |
| **ServiceAccount + Role** in the sandboxes' namespace only: `pods` create/get/list/delete, `pods/exec` create/get. The token is mounted into sandboxd's pods alone | sandboxd can touch sandbox Pods and nothing else in the cluster | — |
| **Namespace `nuria-sandboxes`**: restricted Pod Security, a **NetworkPolicy with no rules** (no traffic in or out, not even DNS), a **ResourceQuota** (20 pods, 20 × 256 Mi) | The cluster's version of Docker's `--network none`, and a ceiling on what sandboxes can take together | A sandbox could reach the network, or a burst could crowd out the app |
| **Sandbox Pods**: non-root (10002), read-only root, all capabilities dropped, seccomp RuntimeDefault, no service account token, no service links, `/workspace` and `/tmp` in memory, CPU and memory limits, `activeDeadlineSeconds` 2 h, `shareProcessNamespace` (the pause container reaps orphans) | The same lockdown as Compose's sandbox. Optional: a `runtimeClassName` (gVisor, Kata) and user namespaces (`hostUsers: false`) | — |

Measured on kind: a 90 s `time.sleep` in a sandbox stopped **0.9 s** after its agent was turned off; eight first calls at once across both sandboxd replicas got one Pod; nothing was left in `nuria-sandboxes` after a turn.

### Monitoring (`monitoring.enabled`, on in `values-kind.yaml`)

| Object | Why |
|---|---|
| **OpenTelemetry Collector + Jaeger** | Traces, as in Compose ([guide](setup/observability.md)). On Kubernetes each span also names its pod, namespace and node (Downward API) |
| **Prometheus** (StatefulSet with a Role, **namespace-scoped**) | Finds every pod annotated `prometheus.io/scrape` in the namespace: the API replicas and however many workers KEDA runs. Nothing cluster-wide |
| **kube-state-metrics** (same Role, `--namespaces=nuria`) | Pod restarts, deployment readiness, and the autoscalers' desired replicas, for the **Nuria on Kubernetes** dashboard |
| **Grafana** | The same dashboards as Compose, plus the Kubernetes one, read from the repository at deploy time |

## Resources (measured, idle, with 5 workers)

| Component | Memory used | Request / limit |
|---|---|---|
| API (each) | 96–117 Mi | 192 Mi / 512 Mi |
| Worker (each) | 84–88 Mi | 224 Mi / 640 Mi |
| UI (each) | 7 Mi | 24 Mi / 96 Mi |
| Postgres | 149 Mi | 192 Mi / 512 Mi |
| Redis | 15 Mi | 32 Mi / 128 Mi |
| Grafana | 226 Mi | 192 Mi / 512 Mi |
| Prometheus, Jaeger, collector, kube-state-metrics | 42, 27, 106, 17 Mi | see [`values.yaml`](../infra/helm/agent-runtime/values.yaml) |
| Traefik, KEDA (2 pods), metrics-server | 55, 152, 24 Mi | |
| **The three nodes, together** | **~3.6 Gi** | Fits in Docker's default 8 GB, next to Compose |

**Grafana needs room at start.** At a 256 Mi limit, Grafana 13 spun in garbage collection while migrating its database: 6 cores and never ready. It needs ~275 Mi while starting, so its limit is now 512 Mi, plus a CPU limit so a spin can't starve the node.

## Things to know

- **After a drain, pods don't move back.** `kubectl uncordon` makes the node schedulable again, but running pods stay where they are, as in any cluster without a descheduler. New pods spread.
- **The dashboards' replica counts** only count targets scraped in the last 15 s. A plain `count(up == 1)` also counted pods that went away while Prometheus itself was being moved, for up to 5 minutes.
- **The sandbox needs NetworkPolicy enforcement.** Its "no network" is a NetworkPolicy: kind's kindnet, Calico and Cilium enforce it; a plugin that doesn't leaves sandboxes networked. On such a cluster set `sandbox.enabled: false` (the code tools are then not offered).
- **Processes per sandbox** is a node setting on Kubernetes (the kubelet's `podPidsLimit`), not a pod's. `infra/kind/kind.yaml` sets 4096 for clusters created from now on (`cluster.sh down`, then `up`); Compose caps each sandbox at 64.
- **Images:** the sandbox image is released with the others (`…/sandbox`); kind builds and loads `nuria/sandbox:$TAG` on every node.
- **Models:** the cluster uses the model from `.env`. For Ollama on this machine, pods reach `host.docker.internal`, as containers do in Compose.
- **Windows:** `setup.ps1 -Kubernetes` runs the same bash script, so it needs Git for Windows or WSL. Like the rest of `setup.ps1`, it hasn't been run on Windows yet.
