# ADR-0001 — Repository layout: a monorepo split by deliverable

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-11 |
| **Supersedes** | The flat layout used during phase 0 (`runtime/`, `tests/` and `docker-compose.yml` at the root) |
| **Amended by** | [ADR-0003](0003-agents-as-definition-files.md): agents become `backend/agents/*.agent.md`, plus `src/agent_runtime/hooks/` and `src/workflows/` |

## Context

The project ships several independently built things: a Python service (API, workers, `sandboxd`), a React UI, container images, and deployment configuration for Compose, kind, Kubernetes and Helm. With everything at the root, it was unclear which files belong to which deliverable, which tool owns which config, and what a CI job or Docker build needs to see. The spec also names paths ad hoc (`examples/research`, `deploy/helm/agent-runtime`, `ops/grafana/`, `evals/`, `fixtures/`).

## Decision

One repository, split into **one top-level folder per deliverable**. Each folder owns its own tool configuration, and a root `Makefile` orchestrates them.

```
.
├── backend/                     Python service (one package, several entrypoints)
│   ├── src/
│   │   ├── agent_runtime/       the durable runtime: API, worker, leases, streaming, tools
│   │   ├── agents/              graphs that run on it: chat (phase 6), research (phase 8)   [later]
│   │   └── sandboxd/            sandbox manager service (phase 7)                            [later]
│   ├── migrations/              Alembic, explicit SQL
│   ├── tests/{unit,integration}/
│   ├── evals/                   eval cases, scorers, baseline (phase 10)                     [later]
│   ├── fixtures/                search fixtures + documents to ingest (phase 8)              [later]
│   ├── Dockerfile               api / worker / sandboxd images (phase 12)                    [later]
│   └── pyproject.toml · uv.lock · alembic.ini
├── frontend/                    React + TypeScript UI, its own package.json and Dockerfile (phase 11)
├── infra/                       how the system is run, not what it is
│   ├── compose/                 docker-compose.yml: local inner loop
│   ├── kind/                    kind cluster config (phase 12)                               [later]
│   ├── k8s/                     raw manifests, written first to learn (phase 12)             [later]
│   ├── helm/agent-runtime/      the Helm chart, written last (phase 12)                      [later]
│   ├── sandbox/                 sandbox-python image (phase 7)                               [later]
│   └── observability/           OTel collector, Prometheus, Grafana dashboards (phase 9)     [later]
├── scripts/                     demo and ops scripts that print PASS/FAIL                    [later]
├── docs/
│   ├── requirements/            the spec PDF + accepted change requests (CR-*)
│   ├── adr/                     architecture decision records (this file)
│   ├── progress/                one summary per phase
│   └── roadmap.md
├── .github/workflows/           CI
├── Makefile                     single entry point: `make help`
└── .env.example                 one config file for every component (R9.1)
```

### Rules

1. **Code and its Dockerfile live together** (`backend/Dockerfile`, `frontend/Dockerfile`). The Docker build context is that folder, so images can't accidentally include the other parts of the repo. `infra/` describes how images are *run* (Compose, manifests, Helm values), not how they are built. The exception is `infra/sandbox/`: the sandbox image contains none of our code.
2. **`src/` layout for Python.** Tests import the *installed* package, never files that happen to be in the working directory. This catches packaging mistakes (a module missing from the wheel) before an image build does.
3. **Tests are split by what they need.** `unit/` needs nothing; `integration/` needs services. CI runs each kind in its own job.
4. **Run commands from the root.** `make <target>` exports the root `.env` and `cd`s into the right folder. Each folder can still be used on its own (`cd backend && uv run pytest tests/unit`).
5. **One configuration source.** A single root `.env` (from `.env.example`) feeds Compose and every local command. Kubernetes gets the same variables from a ConfigMap and Secret (R10.4).

### Mapping from the spec's paths

| Spec path | Path here |
|---|---|
| `runtime` (package) | `backend/src/agent_runtime` (renamed in phase 1; the CLI command is still `runtime`) |
| `examples/research`, `examples/chat` | `backend/src/agents/research`, `backend/src/agents/chat` |
| `evals/cases/*.yaml`, `evals/baseline.json` | `backend/evals/…` |
| `fixtures/search/*.json` | `backend/fixtures/search/…` |
| `deploy/helm/agent-runtime` | `infra/helm/agent-runtime` |
| `ops/grafana/` | `infra/observability/grafana/` |
| `docs/design.md`, `docs/kubernetes.md` | unchanged |

## Alternatives considered

- **Flat layout** (the phase 0 starting point). Simple, but mixes deliverables, and the Docker build context would be the whole repo.
- **Separate repositories** for backend, frontend and infra. Teams do this when separate teams own each part. Here it would split one change, such as a new API field plus the UI that shows it, across several PRs, and the end-to-end and cluster tests would need to check out several repos at matching versions. One developer, one release train: a monorepo fits.
- **`agents/` as a top-level folder.** The agents are Python, depend on `agent_runtime`, and ship in the same worker image, so they belong in the same package tree.

## Consequences

- Phase 0 commands are unchanged (`make up`, `make check`); only the paths moved.
- CI jobs run in `backend/`. A `frontend` job will be added in phase 11, with path filters so each job runs only when its folder changes.
- Folders marked `[later]` are created by the phase that needs them, not as empty placeholders.
