# Durable, Distributed Runtime for LangGraph Agents

[![ci](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/actions/workflows/ci.yml)

A runtime that runs LangGraph agents across a pool of workers and makes them survive what distributed systems throw at them: crashed workers, paused "zombie" workers, restarts, human approvals that take hours, node drains and rolling upgrades. It survives all of these without losing or duplicating work.

> **Status: Phase 0 (foundations).** The tooling, local services, schema and CI are in place. Nothing runs agents yet. See the [roadmap](docs/roadmap.md).

## How it works (target design)

- **Postgres is the only source of truth.** Run status, events, transcripts, tool results and LangGraph checkpoints all live there.
- **Redis is the transport.** A Stream delivers work to workers, and Pub/Sub carries live events to whichever API replica a client is connected to. It holds nothing that can't be rebuilt.
- **Leases with fencing tokens.** A worker holds a run through a renewable lease. Each takeover increments the run's `epoch`, and the database rejects writes that carry an older epoch, so a paused-then-resumed worker can't corrupt anything.
- **Idempotent tool calls.** Delivery is at-least-once, so every tool call has a deterministic key, and a retry returns the stored result instead of running again.
- **Chat sessions.** A session is a LangGraph thread, and each user message is a durable run on that thread.
- **Per-run sandboxes.** Tools that execute model-generated input run in a disposable container with no network and no secrets.

The full design is in the spec (`Project_4_Detailed_Requirements_K8s.pdf`) and the change requests in [docs/requirements/](docs/requirements/).

## Quickstart (Phase 0)

Requirements: [uv](https://docs.astral.sh/uv/), Docker (Desktop or OrbStack), GNU make.

```bash
make up      # creates .env from .env.example, starts Postgres + Redis, applies migrations
make check   # lint + mypy --strict + all tests
make help    # every target
```

`make down` stops the services and keeps their data; `make nuke` deletes the data too.

## Repository layout

| Path | What |
|---|---|
| `runtime/` | The runtime package (`runtime` CLI) |
| `migrations/` | Alembic migrations, written as explicit SQL |
| `tests/` | Unit tests; `tests/integration/` needs `make up` |
| `docs/roadmap.md` | Phase plan and status |
| `docs/requirements/` | Accepted change requests on top of the spec |
| `docs/progress/` | One summary per completed phase |

## Configuration

All settings come from environment variables ([runtime/config.py](runtime/config.py)). For local development, copy [.env.example](.env.example) to `.env`; `make` exports it automatically. Never commit `.env`.

## Security posture

Read this before running the project. It's a learning project, not a hardened product.

- **Today, nothing executes agent tools.** The tool and sandbox layers arrive in phases 4 and 7.
- **Planned:** tools that execute model-generated input (`run_python`) will run in a per-run sandbox container with no network, no secrets, a read-only filesystem and resource limits ([CR-002](docs/requirements/CR-002-run-sandboxes.md)). Trusted in-process tools (search over fixtures, retrieval, saving findings) run with the worker's privileges.
- **Containers aren't a perfect isolation boundary.** Run only against trusted documents and the bundled fixture data.
- **Never use production credentials.** The local Postgres password in `.env.example` is a placeholder for development only.

## License

[Apache-2.0](LICENSE)
