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

### Phase 5b — Sub-agents
#### Added
- Sub-agent orchestrator (CR-005 R16.3): sub-agents run as concurrent tasks in the main run's worker, each with its own checkpoint thread under the main run's fence; at most 4 in parallel and 10 per run, a timeout each; one recovery path (stop → recover from checkpoints) for pauses, releases and crashes.
- Tools granted by the harness: `spawn_subagent` (idempotent), `subagent_status`, `wait_subagents` (≤ 120 s), `cancel_subagent` for the main agent; `report_progress` (rate-limited) and `return_result` for sub-agents.
- Isolation and least privilege: a sub-agent sees only its prompt and its task, gets only its own tools, and can't pause for approval (`ask` → deny).
- Budgets: a sub-agent's own limits plus the run's (roll-up); at 80 % of the run's budget sub-agents are asked to wrap up; at the hard limit they are cancelled.
- Turn guard (R16.9): the main agent can't finish while sub-agents run.
- `subagent.spawned / progress / completed` events; `GET /runs/{id}` lists sub-agents.
- Migration `0008` (cooperative cancel); `delegator` fixture agent; e2e `subagents-crash` (AC41); `make demo-subagents`.
- Scripted model: tool arguments may reference earlier tool results (`${spawn_subagent[0].handle}`).

#### Fixed
- Deadlock between concurrent transactions of one run (a turn's parallel tool calls; sub-agents' checkpoints): `check_fence` locked the run row `FOR SHARE` and then upgraded it. It now takes `FOR NO KEY UPDATE`. Latent since phase 4.

### Phase 5a — Child runs & backpressure
#### Added
- Child runs (R2.8): `spawn_children` from a workflow node (the `Spawner` port: `RunSpawner`, and `LocalSpawner` for `runtime run --local-fanout`); the fan-out runs in one fenced transaction; the parent waits in `waiting_children` holding no lease; an atomic fan-in counter re-queues it exactly once; it resumes with the children's results, `partial` when some failed, `failed(children_failed)` when all did.
- Fan-out limits (R14.6): `max_children` (default 6, per-run option), depth ≤ 2, ≤ 20 descendants per root; a breach is an error the node handles.
- Budget roll-up (R14.1): model and tool calls count for every ancestor, within each ancestor's limits.
- Cancelling a run cancels its live descendants.
- Backpressure (R2.9): `POST /runs` → `429` + `Retry-After` at `QUEUE_DEPTH_LIMIT`; queue depth in `/admin/state`; `RunView` shows the run tree.
- Migration `0007` (`child_key`, `descendants`, queued index); `fanout` demo workflow; e2e `fanout` (AC6) and `child-crash`; `make demo-fanout`.
- ADR-0005: child runs vs `Send` vs sub-agents.

### Phase 4 — Tools & human-in-the-loop
#### Added
- Tool registry (`@registry.tool`): strict, frozen argument models; risk classes; per-tool `max_calls`; isolation flag. Fixture tools `calculator`, `save_note`, `notify` (migration `0006`: `notes`, `outbox_notifications`, `runs.resume_value`).
- Hook registry (`@registry.hook`): ordered, bounded, fail-closed, audited `pre_tool` / `post_tool` hooks; built-in secret redaction for args and results.
- `ToolPipeline`: the fixed-order Chain of Responsibility every tool call goes through; `ToolPolicy` with a risk-class default (external side effects need approval).
- Tool ledger (`tool_invocations`): idempotency keys, "record, then act", cached replay, takeover of a dead owner's call; per-run and per-tool budgets charged once per key; model-call budget from the agent's `max_turns`.
- `ScriptedChatModel` and agent graphs built from agent definitions with `create_agent` + `RuntimeMiddleware` (the `assistant` agent).
- Durable approval: `waiting_approval` with no lease held; `POST /runs/{id}/approve` (approve with edits, or reject → `cancelled(rejected)`); `409 not-waiting-for-approval`.
- Audit events `policy.decision`, `hook.decision`, `approval.decided`, `run.resumed`; `tool.called {taken_over}`.
- E2E scenarios `tool-crash` and `approval-restart`; `make demo-tools`, `make demo-approval` (AC4).

### Phase 3 — Streaming across replicas
#### Added
- `EventBus` port: Redis Pub/Sub adapter + in-memory fake (one contract suite); wire format for persisted and transient events; `run:` / `session:` channels.
- Publish after commit: events announced only once their transaction has committed (checkpointer `after_commit` hook, `RunRepository.emitted`).
- `StreamMerger`: pure replay/live/dedup/back-fill algorithm with property-based tests (`hypothesis`).
- Per-replica `Broker`: one Pub/Sub subscription multiplexed over all streams, reference-counted channels, bounded per-stream queues with catch-up.
- `GET /runs/{id}/stream` (SSE): `Last-Event-ID` / `after_seq` resume, safety-net poll, `: ping` keep-alive, no-cache/no-buffering headers, closes after the terminal event.
- Graceful API drain on SIGTERM (`DrainingServer`): `/readyz` 503, new streams 503 + `Retry-After`, `event: reconnect` to open streams.
- E2E scenarios with multiple API replicas; `make demo-replicas` (AC3).
- ADR-0004 (Redis Pub/Sub vs LISTEN/NOTIFY vs Streams vs polling).

### Phase 2 — Distributed workers
#### Added
- `WorkQueue` port with a Redis Streams adapter and an in-memory fake, verified by one contract suite.
- Outbox relay that rebuilds the work stream from Postgres (`runs.message_id`/`enqueued_at`, migration `0003`).
- Workers: `runtime worker --concurrency C --workers N` (competing consumers, bulkhead, supervisor), reaper (`XAUTOCLAIM`), heartbeat that also touches the message, graceful release on SIGTERM.
- `POST /runs/{id}/cancel` and `/resume`; kill switch `/admin/pause|resume|cancel-all|state`; `503` while paused; `/readyz` checks Redis.
- Database-enforced fencing trigger (migration `0004`).
- Least-privilege database users per component (migration `0005`, `runtime db provision-users`).
- End-to-end harness with real processes; `make demo-crash`, `demo-zombie`, `demo-release`, `demo-e2e`.

#### Changed
- `RunNotRunnable` unified into `RunTerminal`; the API returns `409` for runs that have already ended.
- API and worker connect as their own database users (`API_POSTGRES_*`, `WORKER_POSTGRES_*`).
- `make env` adds keys missing from `.env` without overwriting.
- PR descriptions no longer carry a "Generated with Claude Code" footer.

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
