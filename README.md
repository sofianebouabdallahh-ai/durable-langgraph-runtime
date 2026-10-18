# Nuria

**Agents that finish what they start.** Nuria is a chat with AI agents that runs on your own machine, built on a durable, distributed runtime for LangGraph agents.

[![ci](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/actions/workflows/ci.yml)

Under the hood, a runtime that runs LangGraph agents across a pool of workers and makes them survive what distributed systems throw at them: crashed workers, paused "zombie" workers, restarts, human approvals that take hours, node drains and rolling upgrades. It survives all of these without losing or duplicating work.

> **Status: the local release is under way: one-command setup (L1), the chat UI (L2) and the Agent Studio (L3a) are done.** Clone, run `./setup.sh`, and chat in your browser; kill a worker or an API replica mid-reply and watch nothing get lost. The runtime core (phases 0–6) is complete. Every message is in a durable transcript written with each checkpoint, tokens stream live from any API replica, and a crash mid-turn duplicates nothing. The agent calls tools through one guarded pipeline (budgets with a wrap-up turn, loop detection, retries and a circuit breaker, approvals), delegates to sub-agents that resume after a crash, and fans out child runs across workers. See the [roadmap](docs/roadmap.md) and [phase summaries](docs/progress/).

## Try it (only Docker needed)

```bash
git clone https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime.git
cd durable-langgraph-runtime
./setup.sh            # Windows: .\setup.ps1
```

Then open **http://localhost:3000** (setup opens it for you). Setup checks your machine, generates private local passwords, asks which model to use (an offline demo, a free local model with Ollama, OpenAI, Azure AI Foundry, or any OpenAI-compatible service), starts everything in Docker, and proves it works with a real chat turn. Guides for each OS, models and troubleshooting: [docs/setup/](docs/setup/).

| Home | A chat | An agent and its helpers |
|---|---|---|
| ![Home](docs/images/home.png) | ![A chat waiting for approval](docs/images/chat-ui.png) | ![The Nuria agent](docs/images/agent.png) |

**In Nuria:** replies stream in; tool calls show as cards; helpers (sub-agents) show their progress live; anything that reaches the outside world waits for your **Approve**; **Stop** keeps what was written so far; **What happened?** tells each reply's story, including a worker that crashed and the one that took over. **Agents** is the **Agent Studio**: build your own agents and their helpers (sub-agents) with a form, try them in a test chat, publish versions, import and export them. No code, no Markdown ([guide](docs/setup/agents.md)). On the offline demo model, pick a suggestion or say *hello*.

## How it works (target design)

- **Postgres is the only source of truth.** Run status, events, transcripts, tool results and LangGraph checkpoints all live there.
- **Redis is the transport.** A Stream delivers work to workers, and Pub/Sub carries live events to whichever API replica a client is connected to. It holds nothing that can't be rebuilt.
- **Leases with fencing tokens.** A worker holds a run through a renewable lease. Each takeover increments the run's `epoch`, and the database rejects writes that carry an older epoch, so a paused-then-resumed worker can't corrupt anything.
- **Idempotent tool calls.** Delivery is at-least-once, so every tool call has a deterministic key, and a retry returns the stored result instead of running again.
- **Chat sessions.** A session is a LangGraph thread, and each user message is a durable run on that thread.
- **Per-run sandboxes.** Tools that execute model-generated input run in a disposable container with no network and no secrets.

The full design is in the [spec](docs/requirements/Project_4_Detailed_Requirements_K8s.pdf) and the change requests in [docs/requirements/](docs/requirements/).

## Developer quickstart

Requirements: [uv](https://docs.astral.sh/uv/), Docker (Desktop or OrbStack), GNU make.

```bash
make up        # creates .env from .env.example, starts Postgres + Redis, migrates
make worker    # 2 worker processes that execute queued runs
make api       # HTTP API on http://127.0.0.1:8000 (docs at /docs); API_PORT=8765 to change
make ui-dev    # the UI with hot reload on http://127.0.0.1:5173 (Node runs in a container)
make run-toy   # create and execute one toy run in this process; prints its event log
make demo-e2e  # crash / zombie / release / multi-replica streaming scenarios (real processes)
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
