# Phase L4b — Nuria on Kubernetes (kind)

**Completed:** 2026-10-18 · **Branch:** `feat/l4b-local-kubernetes` · **Plan:** [plans/phase-L4.md](../plans/phase-L4.md) (slice L4b) · **Guide:** [Nuria on Kubernetes](../kubernetes.md)

## What we built

**`./setup.sh --kubernetes`** runs the same images on a local cluster: one control plane and two worker nodes, created with kind.
- **Tools:** kind, Helm and kubectl are downloaded at pinned versions, with verified checksums, into `.tools/`. Nothing is installed system-wide, and the cluster's credentials stay in `.tools/kubeconfig`.
- **Add-ons**, pinned:
  - **Traefik**, the Ingress controller. ingress-nginx is retired: no release since March 2026.
  - **metrics-server**, for the API's HPA.
  - **KEDA**, for the workers.
- **Then:** the images are built and loaded into the nodes, the Secret is made from `.env` (secret keys only), two Helm releases are installed, and a smoke chat turn runs through the Ingress.

**Two charts.**
- **`nuria-data`:** Postgres and Redis, local only.
  - They run on the control plane with `maxUnavailable: 0` PDBs, so a worker-node drain can't touch them.
  - They have their own release because the migrate Job is a pre-install hook, and a hook runs before anything else in its release exists.
- **`agent-runtime`:** every object of R10.3 to R10.11.
  - The migrate hook.
  - The UI, API and worker Deployments, with probes, preStop, grace periods, topology spread and resources.
  - The API's HPA on CPU; KEDA scaling workers on the work queue's backlog.
  - PDBs, the Ingress, and a ConfigMap whose checksum rolls the pods.
  - Each component reads only its own database password.
  - A token-less ServiceAccount, the restricted Pod Security Standard, and default-deny NetworkPolicies.
  - In-cluster monitoring: collector, Jaeger, Prometheus and kube-state-metrics (namespace-scoped), and Grafana with the Compose dashboards plus a Kubernetes one.

**One UI image for both platforms.** The UI's nginx config became a template:
- **Resolver:** from the container's `/etc/resolv.conf` (Docker's DNS in Compose, the cluster's in Kubernetes).
- **API address:** `API_UPSTREAM` (Compose's `api`, or the headless Service of ready API pods).

The proxy follows pods and retries the next one on both platforms.

**Demos with PASS/FAIL** (`make k8s-demo-*`): podkill, drain, scale, upgrade and security.

**CI** creates a kind cluster on every pull request:
- `helm lint` and kubeconform on both charts;
- `./setup.sh --kubernetes` from clean;
- the security, podkill and upgrade demos;
- events, logs and `describe` output uploaded on failure.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC7 | **`--kubernetes` from clean** | ✅ On this Mac, with only Docker installed: tools, cluster, add-ons, images, Secret, both charts, smoke turn. CI runs it on Linux for every PR |
| SC8 | **Pod kill** | ✅ Force-deleting the busy worker pod, with no grace: the turn completes with one reclaim, no duplicates, and its side effect once. The reclaim comes after 31–33 s, as the 30 s lease allows. **3/3** here, also in CI |
| SC9 | **Drain** | ✅ Draining the node with the busy worker **and both API pods**: **0 failed requests out of 117** (one every 200 ms through the Ingress). The run was handed off (released, not reclaimed) and resumed on another node **0.03–0.07 s** later (3 runs). The drain took 24 s. **3/3** |
| SC10 | **Scale** | ✅ 24 queued runs: KEDA took the workers from 2 to a **peak of 5**; **24/24** completed; back to 2 after the 120 s stabilization window, one pod at a time |
| SC11 | **Upgrade and rollback** | ✅ `helm upgrade` to a new image mid-turn: the migrate Job ran first, the turn completed, and the pods moved to the new image. `helm rollback` restored the old one. **0 failed requests out of 115**. **3/3** |
| SC12 | **Pod security** | ✅ The namespace enforces `restricted` and refuses a privileged pod. The UI, API, workers, Postgres and Redis all run non-root on a read-only root filesystem, with no capabilities and no token. An intruder pod times out reaching Postgres; the API connects. **3/3** |
| AC8 on kind | **One trace** | ✅ A fan-out through the Ingress is one trace in Jaeger: the API request, the parent's `run` ×2, and three children's `run`. Every span names its pod, namespace and node (Downward API) |
| L4b.4 | Dashboards on the cluster | ✅ Every query of both dashboards (Nuria, and Nuria on Kubernetes) evaluates on the cluster's Prometheus. Replica counts, KEDA's desired workers and pods per node are correct |
| SC13 (L4b part) | Quality and docs | ✅ Both charts lint and render. The new CI job is on the PR. [`docs/kubernetes.md`](../kubernetes.md) explains every object and has the measured numbers |

## Bugs found by testing

- **The migrate hook couldn't start.** It named the release's ServiceAccount, which doesn't exist yet when a pre-install hook runs. It now uses the namespace's default account, still with no token.
- **A drain took Redis down.** The first drain demo drained the node that held `redis-0`. Redis has a single replica on a node-local volume, so it couldn't move, and every request failed until the node came back. The data stores now live on the control plane, with PDBs that make a drain of their node wait. The drain demo then had 0 failed requests.
- **Grafana spun in garbage collection.** At a 256 Mi limit, Grafana 13 used 6 cores for 10 minutes and never became ready. It needs ~275 Mi while it migrates at start. The limit is now 512 Mi, plus a CPU limit.
- **Prometheus counted pods that were gone.** After Prometheus itself was moved by a drain, it counted pods that no longer existed for up to 5 minutes, because no staleness markers were written. The dashboards now count only targets scraped in the last 15 s, which fixes Compose's too.
- **The UI's nginx couldn't run on Kubernetes.** It hardcoded Docker's DNS server (`127.0.0.11`). It's now a template.
- **`make help` hid every `k8s-*` target.** Its pattern didn't allow digits.

## Known limitations

- **Pods don't move back after a drain.** `uncordon` makes the node schedulable again, but nothing rebalances running pods (no descheduler).
- **`setup.ps1 -Kubernetes` needs bash** (Git for Windows or WSL), and hasn't been run on Windows yet.
- **The podkill reclaim waits out the lease** (30 s). A graceful stop or a drain hands the run off at once.

## Next

L5: release v0.1 and the feedback loop.
