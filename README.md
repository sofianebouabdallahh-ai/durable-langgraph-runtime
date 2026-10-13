# Durable, Distributed Runtime for LangGraph Agents

[![ci](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/actions/workflows/ci.yml)

A runtime that runs LangGraph agents across a pool of workers and makes them survive what distributed systems throw at them: crashed workers, paused "zombie" workers, restarts, human approvals that take hours, node drains and rolling upgrades. It survives all of these without losing or duplicating work.

> **Status: Phase 1 (durable single run) complete.** Runs execute durably: checkpointed every step, fenced against zombie workers, resumable after a crash. Workers, streaming and real agents come next. See the [roadmap](docs/roadmap.md) and [phase summaries](docs/progress/).

## How it works (target design)

- **Postgres is the only source of truth.** Run status, events, transcripts, tool results and LangGraph checkpoints all live there.
- **Redis is the transport.** A Stream delivers work to workers, and Pub/Sub carries live events to whichever API replica a client is connected to. It holds nothing that can't be rebuilt.
- **Leases with fencing tokens.** A worker holds a run through a renewable lease. Each takeover increments the run's `epoch`, and the database rejects writes that carry an older epoch, so a paused-then-resumed worker can't corrupt anything.
- **Idempotent tool calls.** Delivery is at-least-once, so every tool call has a deterministic key, and a retry returns the stored result instead of running again.
- **Chat sessions.** A session is a LangGraph thread, and each user message is a durable run on that thread.
- **Per-run sandboxes.** Tools that execute model-generated input run in a disposable container with no network and no secrets.

The full design is in the [spec](docs/requirements/Project_4_Detailed_Requirements_K8s.pdf) and the change requests in [docs/requirements/](docs/requirements/).

## Quickstart

Requirements: [uv](https://docs.astral.sh/uv/), Docker (Desktop or OrbStack), GNU make.

```bash
make up        # creates .env from .env.example, starts Postgres + Redis, migrates
make run-toy   # create and durably execute a run of the `toy` graph; prints its event log
make api       # HTTP API on http://127.0.0.1:8000 (docs at /docs); API_PORT=8765 to change
make check     # lint + mypy --strict + agent validation + all tests
make help      # every target
```

`make down` stops the services and keeps their data; `make nuke` deletes the data too.

## Repository layout

A monorepo with one folder per deliverable ([ADR-0001](docs/adr/0001-repository-layout.md) explains why).

| Path | What |
|---|---|
| [`backend/`](backend/) | Python service: `src/agent_runtime` package, Alembic `migrations/`, `tests/{unit,integration}` |
| [`frontend/`](frontend/) | React + TypeScript UI (phase 11) |
| [`infra/`](infra/) | How it runs: `compose/` now; sandbox image, observability, kind, k8s and Helm later |
| [`docs/`](docs/) | `requirements/` (spec + change requests), `adr/`, `progress/` (phase summaries), `roadmap.md` |
| `Makefile` | The single entry point. Run `make` from the root |

## Configuration

All settings come from environment variables, validated at startup by [backend/src/agent_runtime/config.py](backend/src/agent_runtime/config.py). How they get there depends on the environment:

| Environment | Configuration | Secrets |
|---|---|---|
| Laptop | `.env` (from [.env.example](.env.example)), passed by `make` to `uv` and Compose | same `.env`, git-ignored |
| CI | workflow `env:` | GitHub Environment secrets; OIDC for cloud access |
| Kubernetes | ConfigMap from Helm values | K8s Secret (kind: `make k8s-secrets`; cloud: External Secrets) |

The same image runs everywhere; only the injected environment differs. Details and rules are in [ADR-0002](docs/adr/0002-configuration-and-secrets.md).

Run `make hooks` once after cloning: the pre-commit hooks block secrets from being committed.

## Security posture

Read this before running the project. It's a learning project, not a hardened product.

- **Today, nothing executes agent tools.** The tool and sandbox layers arrive in phases 4 and 7.
- **Planned:** tools that execute model-generated input (`run_python`) will run in a per-run sandbox container with no network, no secrets, a read-only filesystem and resource limits ([CR-002](docs/requirements/CR-002-run-sandboxes.md)). Trusted in-process tools (search over fixtures, retrieval, saving findings) run with the worker's privileges.
- **Containers aren't a perfect isolation boundary.** Run only against trusted documents and the bundled fixture data.
- **Never use production credentials.** The local Postgres password in `.env.example` is a placeholder for development only.

## License

[Apache-2.0](LICENSE)
