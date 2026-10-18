# infra

How the system is **run**. What it **is** lives in `backend/` and `frontend/`, each with its own Dockerfile.

| Path | What | Phase |
|---|---|---|
| `compose/` | `docker-compose.yml`: the local stack (Postgres + pgvector, Redis, migrate, api, worker, ui; profiles `llm`, `test`, `observability`) | 0, L1, L4a |
| `sandbox/` | The `sandbox-python` image that runs untrusted tool code | 7 |
| `observability/` | OTel collector, Prometheus and Grafana configs, and the dashboard ([guide](../docs/setup/observability.md)) | L4a |
| `kind/` | Local multi-node Kubernetes cluster config | 12 |
| `k8s/` | Raw manifests, written first to learn each object | 12 |
| `helm/agent-runtime/` | The Helm chart, written last | 12 |

Use it through the root Makefile (`make up`, `make down`, later `make k8s-*`), which supplies the root `.env`.
