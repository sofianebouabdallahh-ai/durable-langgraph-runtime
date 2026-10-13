# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/). Each phase is tagged `phase-NN`; `v1.0.0` is tagged when every acceptance criterion passes.

## [Unreleased]

### Changed
- Python package renamed `runtime` → `agent_runtime` (`backend/src/agent_runtime`). The CLI command is still `runtime`.
- Configuration and secrets follow [ADR-0002](docs/adr/0002-configuration-and-secrets.md): `make` passes `.env` to `uv run --env-file` and `compose --env-file` instead of `include`-ing it; unit tests run without `.env`.
- Workflow: all changes go through a branch and pull request; commits to `main` are blocked by a hook.
- Repository reorganised into a monorepo ([ADR-0001](docs/adr/0001-repository-layout.md)): `backend/` (Python service, `src/` layout, `tests/unit` + `tests/integration`), `frontend/`, `infra/compose/`, and `docs/requirements/` for the spec. `make` targets are unchanged.

### Added
- Pre-commit hooks (`make hooks`): gitleaks, ruff (locked version), file hygiene, no commits to `main`.
- CI `secrets` job: gitleaks over the full git history, failing if it scans zero commits; per-job timeouts.
- `docs/adr/` index.
- CR-005 (accepted): sub-agents. Agents are folders (`agents/<name>/agent.md`), and sub-agents are leaf sub-folders discovered by the harness. They run in-process in the main agent's worker under an orchestrator (spawn/status/wait/cancel; `report_progress`/`return_result`), each with its own checkpoint for crash resume, a fresh context, its own tools only, and budget roll-up.
- CR-004 + ADR-0003 (accepted): agents defined as `backend/agents/*.agent.md` (name, max turns, prompt, tools, limits, hooks); hooks for session start/end, turn start/end and pre/post tool, built on LangChain middleware plus harness-owned session hooks.
- CR-003 (accepted): harness guardrails. Run budgets with a soft→hard wrap-up, loop detection, ceilings that callers can only tighten, deny-by-default tool grants, least-privilege DB roles, untrusted-content handling, audit trail, kill switch.

### Phase 1 — Durable single run
#### Added
- Epoch-fenced LangGraph checkpointer (Protection Proxy over `AsyncPostgresSaver`); spike findings in `docs/design.md`.
- Run state machine, UUIDv7 ids, `RunRepository` (atomic transitions + events, gap-free `seq`, leases, heartbeat, results).
- `RunExecutor`: lease + heartbeat, `durability="sync"`, node events committed with each step's checkpoint (Transactional Outbox), `max_steps` and wall-clock limits, reclaim with `max_reclaims`.
- Limits where options can only tighten server ceilings (`422` names the field and maximum).
- Agent definitions: `backend/agents/<main>/agent.md` with leaf sub-agent folders; strict loader; content-addressed snapshots; `runtime agents validate|show`.
- API: `POST /runs`, `GET /runs/{id}`, `/events`, `/result`, `/graphs`, `/healthz`, `/readyz`; RFC 9457 problem details.
- CLI: `runtime db upgrade`, `api`, `run`, `execute`/`resume`. Makefile: `api`, `run-toy`, `agents-validate`.
- Migration `0002` (agent snapshots, usage counters, limits, kill switch, sub-agent invocations).
- Tests: 116 (unit + integration), including a real-process SIGKILL crash-and-resume test; branch coverage 95.9% with a 90% floor in CI (`make coverage`).

#### Changed
- Package renamed `runtime` → `agent_runtime` (the CLI is still `runtime`).
- Supply-chain cooldown: `[tool.uv] exclude-newer`.
- Integration tests fail (not skip) on missing services under `make test` and in CI.

### Phase 0 — Foundations
#### Added
- Requirements: CR-001 (chat sessions) and CR-002 (per-run sandboxes) on top of the v1.0 + Kubernetes spec; `docs/roadmap.md`.
- Python 3.12 project managed by `uv` with a locked dependency set; `ruff`, `mypy --strict`, `pytest`.
- `agent_runtime.config.Settings`: environment-only configuration with `pydantic-settings`, plus `.env.example`.
- Docker Compose with Postgres 16 + pgvector and Redis 7 (AOF), bound to localhost.
- Makefile: `up`, `down`, `nuke`, `migrate`, `migration`, `lint`, `fmt`, `typecheck`, `test`, `check`.
- Alembic migration `0001`: `sessions`, `runs`, `run_events`, `run_results`, `tool_invocations`, `findings`, `documents`, `chunks`, `session_messages`.
- GitHub Actions CI: lint, type-check, unit tests, migrations and integration tests.
- Apache-2.0 license, README.
