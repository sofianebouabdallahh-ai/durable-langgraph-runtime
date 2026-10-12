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
