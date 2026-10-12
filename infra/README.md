# infra

How the system is **run**. What it **is** lives in `backend/` and `frontend/`, each with its own Dockerfile.

| Path | What | Phase |
|---|---|---|
| `compose/` | `docker-compose.yml`: the local inner loop (Postgres + pgvector, Redis; api/worker/ui later) | 0 |
| `sandbox/` | The `sandbox-python` image that runs untrusted tool code | 7 |
| `observability/` | OTel collector, Prometheus, Grafana dashboards | 9 |
| `kind/` | Local multi-node Kubernetes cluster config | 12 |
| `k8s/` | Raw manifests, written first to learn each object | 12 |
| `helm/agent-runtime/` | The Helm chart, written last | 12 |

Use it through the root Makefile (`make up`, `make down`, later `make k8s-*`), which supplies the root `.env`.
