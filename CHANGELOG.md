# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/). Each phase is tagged `phase-NN`; `v1.0.0` is tagged when every acceptance criterion passes.

## [Unreleased]

### L3d — Getting started: a guided first agent
#### Added
- **Get started** (Home's card, the sidebar with your progress, `#/start`): your first agent in five real steps (a model, the agent, a tool, a helper, try and publish), each ticking by itself when it's done.
- **Choosing a model in the guide:** Ollama found on this computer (or how to install it on your system, then Check again), a key (OpenAI, Azure AI Foundry, any OpenAI-compatible service), or the demo for now. A model added there is tested and made the default.
- **A guide strip** on Models and in the Studio of the guide's agent: the step, what to do there, **Show me** (scrolls to the section and focuses it), and a tick when done.
- Progress is derived from the account (`GET/PUT /onboarding`), so it's the same everywhere and un-ticks when something is undone; only the guide's choices are stored (migration 0014). `?guide=true` when creating an agent.
- Docs: [Getting started](docs/setup/getting-started.md); the tester guide and script point to it.

#### Changed
- **Ollama is setup's default model** (interactive and `--non-interactive`): free and private. When the Ollama app is running without the recommended model, setup downloads it (asking first); without the app, Ollama runs in Docker as before. Keys stay an option in setup and in the app; the offline demo is the last choice.

## [0.1.0] - 2026-10-18

The first release for testers: Nuria, on your own machine, from one command (phases 0–6 and L1–L5).

### L5 — Release v0.1 & the feedback loop
#### Added
- **Versions:** `VERSION` is the release, and the backend, UI and charts carry it (a test keeps them in step). Setup pins `NURIA_VERSION`, so Compose pulls exactly that release's images. The sidebar shows *Nuria 0.1.0*. A `v*` tag must match `VERSION`, and its GitHub Release gets this changelog's section as notes.
- **`./setup.sh --update [--to vX.Y.Z]`:**
  1. A checked backup first (`backups/nuria-<version>-<date>.sql.gz`); a failed backup changes nothing.
  2. The newest (or named) release.
  3. The new version's own setup finishes the job: its images, migrations, a restart, a smoke turn.
  4. On any failure, the two commands that take you back.
- **`./setup.sh --restore FILE`** (`setup.ps1 -Restore`).
- **CI checks the upgrade** from the previous release with data in it, then the restore (`infra/ci/upgrade.sh`).
- **Send feedback** (sidebar): what you were doing, what happened, how it felt. It shows the exact text, then **Open a GitHub issue** (pre-filled, nothing sent before your click) or **Download**.
- **Report this reply** (under *What happened?*): a zip with the steps (no text), the agent's definition if it's yours, and the conversation only if you tick it. Plus the matching issue template.
- **Download this chat** (Markdown).
- **Settings → Privacy:** opt-in, content-free usage counts, shown exactly. They are only ever attached to feedback you send. Migration 0013 adds `workspace_settings.share_usage`, off.
- **Issue templates:** feedback, something broke, my agent didn't do what I expected, an idea.
- **Docs:** [tester guide](docs/setup/testers.md), [updating and backups](docs/setup/updating.md), [what runs where and how to delete it](docs/security.md), troubleshooting additions, and a README for v0.1.0.

#### Fixed
- `--update`'s backup was never checked (an empty dump looked like success), and there was no way to restore one.
- During an update, the old version's setup ran the new version's start. The new version's own script now finishes the update.


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

### L4b — Nuria on Kubernetes (kind)
#### Added
- **`./setup.sh --kubernetes`** (`setup.ps1 -Kubernetes`; needs Git Bash or WSL) runs Nuria on a local multi-node cluster ([guide](docs/kubernetes.md)):
  - one control plane and two worker nodes;
  - Traefik, metrics-server and KEDA, pinned;
  - images built and loaded into the nodes;
  - the Secret made from `.env`;
  - two Helm releases, then a smoke chat turn.
- **The tools are pinned:** kind, Helm and kubectl go into `.tools/` with verified checksums, and the cluster's credentials into `.tools/kubeconfig`. Nothing is installed system-wide, and `~/.kube/config` is left alone.
- **Helm charts:**
  - **`nuria-data`:** Postgres and Redis StatefulSets on the control-plane node, with `maxUnavailable: 0` PDBs.
  - **`agent-runtime`:**
    - the migrate Job as a pre-install and pre-upgrade hook;
    - the UI, API and worker Deployments, with probes, preStop, grace periods, topology spread and resources;
    - the API's HPA on CPU, and KEDA scaling workers on the work queue's backlog;
    - PDBs, the Ingress, and a ConfigMap whose checksum rolls the pods;
    - each component reads only its own database password;
    - a ServiceAccount with no token, the restricted Pod Security Standard, and default-deny NetworkPolicies;
    - in-cluster monitoring: collector, Jaeger, Prometheus (namespace-scoped), kube-state-metrics and Grafana.
- **The "Nuria on Kubernetes" dashboard:** pods per component and node, restarts, KEDA and HPA replicas against the backlog.
- **Demos with PASS/FAIL:** `make k8s-demo-podkill`, `-drain`, `-scale`, `-upgrade` and `-security`.
- **A CI job on kind:** helm lint and kubeconform on both charts, the setup from clean, then the security, podkill and upgrade demos; diagnostics are uploaded on failure.
- **`docs/kubernetes.md`:** every object (why it's there, what breaks without it) and the measured numbers.

#### Changed
- The UI's nginx config is a template: the resolver comes from `/etc/resolv.conf` and the API address from `API_UPSTREAM`, so the same image works in Compose and on Kubernetes.
- Dashboards count only replicas scraped in the last 15 s; stale series lingered for up to 5 minutes after Prometheus moved.
- `make help` lists targets with digits in their names (`k8s-*`).

### L4a — Watch it work: traces, metrics, dashboard
#### Added
- **`./setup.sh --observability`** (`setup.ps1 -Observability`; `--no-observability` to turn it off): the Compose profile `observability` adds:
  - the OpenTelemetry Collector and Jaeger (traces);
  - Prometheus (metrics, 7 days);
  - Grafana with the **Nuria** dashboard (anonymous viewers, local only);
  - images pinned by digest, each at least two weeks old.
- **One trace per turn, across processes and time** (R2.7, R7.1, AC8):
  - the W3C context is stored on the run (`runs.traceparent`) and restored by whichever worker executes it: the first time, after a crash (a second `run` span, marked reclaimed), after an approval, a parent after its children;
  - child runs hang below their parent's `run`, and sub-agents are `subagent:{name}` spans of the run's worker;
  - our spans: `run`, `node:{name}`, `llm.call` (model, tokens, cost, attempts), `tool:{name}` (status, cached); auto-instrumentation only for FastAPI and httpx.
- **Metrics** (R7.2 with the CR additions), on the API's `/metrics` and each worker's `:8081/metrics`:
  - runs by outcome and reason, reclaims and releases, run and turn latency;
  - node, tool and model latency; tokens and cost by model; tool replays;
  - policy decisions, approvals, helpers by outcome, budget wrap-ups and stops, loop detections;
  - queue depth, undelivered messages, leases, waiting runs, active chats, today's spend, the kill switch, open streams.
- **The worker's health server** (`WORKER_HEALTH_PORT`, 8081 in containers, R10.5): liveness fails when its loop hasn't ticked within 30 s, readiness at once on drain. Compose now health-checks workers.
- **JSON logs** in containers (`LOG_FORMAT=json`): every line during a run carries `run_id`, `epoch` and `trace_id`; probe and scrape requests are left out of the access log.
- **UI:**
  - **Open the trace** in "What happened?", and the run's trace id;
  - **Dashboard** in the sidebar;
  - `GET /about` says whether tracing is on.
- Docs: [Watch Nuria work](docs/setup/observability.md).

#### Changed
- With no OTLP endpoint (the default), nothing changes: no tracing SDK, no traceparent, no export.

### L3c — Agent Studio: skills & "describe your agent"
#### Added
- **Skills** (sidebar → Skills; CR-006 R17.4):
  - write one in the app or upload one in the open Agent Skills format (a zip of its folder, or a `SKILL.md`);
  - every save is checked and **scanned**: a secret refuses it; injection phrasing, links, encoded blobs, invisible characters, code and length are reported for a look;
  - edit (a new version), upload a new version, download, remove; built-in skills `trip-planning` and `plain-writing`.
- **Skills on agents and helpers** in the Studio. Agents see a skill's name and "when to use it" and load it when needed (`load_skill`, `read_skill_file`); each sees only its own; scripts are kept and never run.
- **Pinned skills:** a turn pins its skill versions in its bundle; publishing locks them (`skill_lock`), so editing a skill never changes a published agent; a draft needs a new test after a skill changes.
- **"Describe it"** (New agent's default): the builder agent drafts the form from a description, checked by the one validator; nothing is saved until you accept. Also **From a template** and **Start blank**.
- **"Improve my instructions"**: a suggestion side by side with yours.
- **Untrusted text stays data** (CR-003 R14.15): every tool result reaches the model marked as data, and the rule closes every prompt; 22 injection cases as a gate.
- Agent exports carry their skills; imports add them (scanned), reuse identical ones and refuse a clash.
- **Database:** `skills`, `skill_versions`, `skill_files`, `agent_versions.skill_lock` (migration 0012).
- **API:** `/skills`, `/studio/describe`, `/studio/agents/{id}/improve`, `/studio/assist/{run_id}`, `/studio/agents/from-proposal`.
- Docs: [Skills](docs/setup/skills.md), the agents guide, and a [tester script](docs/setup/tester-script.md) for AC43.

#### Fixed
- A gated tool ran on any resume value, not only an approval (unreachable through the API, which cancels on a rejection; now fails closed).
- A Redis timeout (a paused host) made workers exit and restart: they now back off and keep serving.
- Migration 0010's downgrade deleted bundle snapshots that agent versions still referenced.
- Uploads through nginx were capped at 256 KB: skills (10 MB) and agent imports now have their own limit.

### L3b — Agent Studio: your own model
#### Added
- **Settings → Models** (sidebar → Models):
  - add a local **Ollama** (found automatically), **OpenAI**, **Azure AI Foundry** or any **OpenAI-compatible** service;
  - **Save and test** checks the address, the key, the model and tool use in one tiny request, and explains a failure in plain words;
  - a **default model**; edit (a new key replaces the old), remove.
- **A model per agent and per helper** in the Studio (`<connection>:<model>`, or the default). Publishing needs every chosen model to have passed its test; a missing connection is named next to the field.
- **Keys encrypted on this machine** (R18.3, AC45): envelope AES-256-GCM, a data key per secret wrapped by `NURIA_SECRET_KEY` (setup generates it, also into an existing `.env`); each ciphertext bound to its workspace, row and purpose. Keys are never returned, shown or logged: the app shows a fingerprint.
- **Model bindings pinned on each run** (`runs.model_bindings`): a conversation keeps its model when the default changes, and across a worker crash. Circuit breaker per connection.
- **Different models in one conversation** (AC44): an agent and its helpers each on their own connection.
- The chat shows which model answered. Agents with helpers are told about them in their prompt ("## Your helpers"), so real models can delegate.
- **Database:** `model_connections`, `workspace_settings`, `runs.model_bindings` (migration 0011).
- **`/models` API:** connections, test, models, Ollama discovery, the default.
- **`runtime fake-model`:** a deterministic OpenAI-compatible server for tests (Compose profile `test`, used in CI).

#### Fixed
- Studio agents' helpers were invisible to real models (only the demo model knew them): the prompt now lists them.

### L3a — Agent Studio: agents & helpers
#### Added
- **The Agent Studio** (Agents → New agent / Copy / Import):
  - a form for an agent and its helpers (sub-agents): name, purpose, instructions with insertable placeholders, tools as plain-language cards ("Asks you first"), helpers, effort presets, protections;
  - autosave, with issues next to each field in plain words;
  - a **test chat** beside the form (small budget; approval-gated tools simulated, nothing sent);
  - **publish** (needs a test on the exact draft) → immutable versions, history, restore, export / import (`.agent.md` or a zipped folder).
- **Every turn pins its agent by hash** (R15.4, now wired): a content-addressed bundle (agent + helpers); workers build from the snapshot. Publishing never changes a running or queued turn (AC47); neither does a deploy.
- **One validator for files and the Studio** (`validate_definition`); `display_name` in definitions (`chat` is "Nuria").
- **Database:**
  - `agents`, `agent_versions` (a trigger freezes published versions);
  - bundle snapshots;
  - `sessions.playground_of`;
  - `runs.idempotency_key`.
- **Retry-safe sends** (`Idempotency-Key`); the demo model hands tasks to any agent's helpers; `GET /agents` includes published Studio agents.
- Browser tests for the Studio; a user agent survives a worker crash on its version.

#### Fixed
- A tool grant written as `{name: calculator}` crashed the definition parser.
- Migration 0010's downgrade detaches runs from bundle snapshots before deleting them.

### L2 — Chat UI
#### Added
- **The web UI** (`frontend/`): React 19 + TypeScript strict + Vite + Tailwind + TanStack Query; the API client generated from the OpenAPI spec (CI fails on drift).
  - Sessions sidebar, streaming replies, tool cards, live helper (sub-agent) cards, the approval card, Stop, "What happened?" per reply.
  - Plain words throughout; dark mode; keyboard- and screen-reader-friendly.
- **Exactly-once display (AC20):** a pure transcript reducer plus an EventSource adapter that resumes from the last message held, across a reload, a lost connection, an API replica killed or drained, and a worker crash.
- **Untrusted output is inert:** no raw HTML, sanitised Markdown, safe links only, images never loaded, tool data shown as text, and a strict Content-Security-Policy.
- **The `ui` image:** unprivileged nginx serving the app and proxying `/api` to **2 API replicas** (one origin, SSE unbuffered, failover). `./setup.sh` prints the address and opens http://localhost:3000.
- **Backend:**
  - `turn.status` on the session stream;
  - the **demo responder** (the offline model answers free text using its tools, deterministically);
  - `GET /about`;
  - `runtime openapi`;
  - `runtime smoke --ui`.
- **Tests:** Playwright browser tests against the Compose stack (`make ui-e2e`, also in CI); `make ui-check`, `make ui-dev`, `make ui-api`. The Node toolchain runs in a pinned container (pnpm, verified by hash, with a 14-day release cooldown).

#### Changed
- The API has no host port of its own: everything goes through the UI's address (`/api`, `/docs`). `--api-port` became `--port`.

### L1 — Containerise & one-command setup
#### Added
- `./setup.sh` / `.\setup.ps1`: clone → running stack with only Docker (checks, generated `.env`, free ports, model choice, smoke test, `--chat`, `--stop`, `--update`, `--doctor`, `--reset`).
- The `runtime` image (non-root, read-only, tini, Debian 13, digest-pinned); the Compose `app` profile (`migrate`, `api`, 2 workers) with **per-component database logins**.
- `runtime db init`, `runtime smoke`, `runtime doctor` (secrets redacted).
- Container e2e (`make demo-compose`): kill / stop a worker container mid-turn; least-privilege probe.
- CI `containers` job (setup from scratch, idempotency, Trivy, non-root, container e2e); the `release` workflow (multi-arch images to GHCR with SBOM and provenance). Every action pinned by commit SHA.
- `docs/setup/`: macOS, Windows, Linux, models (incl. Azure AI Foundry), troubleshooting.

#### Fixed
- The CLI looked for `alembic.ini` next to its source, which fails in an installed package (`RUNTIME_HOME`).

### Phase 6c — Real models & the chat agent
#### Added
- `ModelProvider` (R3.1): `MODEL_PROVIDER=scripted|openai|ollama`, model per role (`MODEL_CHAT`, …), `embed()`; one OpenAI-compatible adapter for OpenAI and Ollama; Ollama 0.34.4 as an opt-in Compose profile (`make llm-up`).
- Live tokens on the session (or run) stream as transient `token` events; a reply cancelled mid-stream is kept, marked `interrupted` (R12.7).
- Fixture `search` tool (R3.3) with 6 fixture topics.
- The `chat` agent v2 with `researcher` and `data-analyst` sub-agents; sub-agent events carry the worker and reach the session stream (AC37).
- `runtime chat` / `make chat`: chat in the terminal with tokens live; `make demo-chat-live` and `make test-live` on the real local model (never in CI).
- E2E `chat-subagents` (AC37); provider contract tests against a fake OpenAI-compatible server.

#### Fixed
- `return_result` rejected a plain JSON `result` (e.g. `48`): a real model retried until its sub-agent timed out. Found in the first live run.
- `make` couldn't pull images when Docker's credential helper wasn't on `PATH` (Docker Desktop on macOS).

### Phase 6b — Guardrails
#### Added
- Soft → hard budgets (R14.2): at 80 % of the model-call, tool-call, token or cost budget a main agent gets one wrap-up turn with no tools; its answer is stored (`budget_limited`) and the run ends `failed(budget:*)`.
- Token and cost accounting (R14.1): priced per model (`MODEL_PRICES`), counted with each committed step, rolled up to ancestors and sessions; `max_tokens` / `max_cost_usd` budgets (from agent definitions, options, ceilings).
- Loop detection (R14.4): a repeated identical tool call is served from cache with a note, the 3rd ends the run `loop_detected`; five identical model outputs in a row too (migration `0009`: `tool_invocations.args_hash`).
- Model retries with capped full-jitter backoff and `Retry-After`, every attempt charged; a circuit breaker per provider that releases runs instead of retrying (R14.7).
- Admission control (R14.8): `SESSION_MESSAGES_PER_MINUTE`, `GLOBAL_DAILY_COST_USD`; `429` problems carry a `reason`.
- The transcript redacts secrets in tool-call arguments and results (R14.12).

### Phase 6a — Chat sessions
#### Added
- Sessions (CR-001): `POST/GET/PATCH /sessions`, `GET /sessions/{id}/messages`, `POST /sessions/{id}/messages` (one active turn: `409`), `/approve`, `/cancel`, `GET /sessions/{id}/stream` (SSE, any replica, `Last-Event-ID`).
- A session is a LangGraph thread and a turn is a run; the transcript (`session_messages`) is written in each checkpoint's transaction, with deterministic ids, gap-free `seq` and epoch fencing; `interrupt` / `approval` / `error` messages.
- Session and turn hooks (CR-004 R15.5, R15.6): `session_start` once per session, `turn_start` (context or deny → `failed(turn_denied)`), `turn_end`, `session_end` as a durable run that stores a summary; idle sessions archived by the workers. Built-ins `session_clock`, `summarize_session`.
- `GET /agents`, `GET /agents/{name}` (R15.11); the `chat` agent definition.
- E2E `chat-sessions` (AC18) and `chat-crash` (AC19); `make demo-chat`, `make demo-chat-crash`.

#### Fixed
- A run treated any existing checkpoint on its thread as its own and "resumed" it: a second chat turn would have lost its message. Runs now resume only checkpoints stamped with their own `run_id`.
- Child runs were stored with kind `workflow`; they are `child`.

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
