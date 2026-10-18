# infra

How the system is **run**. What it **is** lives in `backend/` and `frontend/`, each with its own Dockerfile.

| Path | What | Phase |
|---|---|---|
| `compose/` | `docker-compose.yml`: the local stack (Postgres + pgvector, Redis, migrate, api, worker, ui; profiles `llm`, `test`, `observability`) | 0, L1, L4a |
| `sandbox/` | The `sandbox-python` image that runs untrusted tool code | 7 |
| `observability/` | OTel collector, Prometheus and Grafana configs, and the dashboard ([guide](../docs/setup/observability.md)) | L4a |
| `kind/` | The local cluster: `kind.yaml`, the pinned tools (`tools.sh`), Traefik's values, and `cluster.sh` (up, build, load, secrets, deploy, smoke, down) | L4b |
| `helm/agent-runtime/` | Nuria's Helm chart ([every object explained](../docs/kubernetes.md)) | L4b |
| `helm/nuria-data/` | Postgres and Redis for the local cluster (managed services in the cloud) | L4b |

Use it through the root Makefile (`make up`, `make down`, `make k8s-*`) or `./setup.sh` (`--kubernetes`), which supply the root `.env`.
