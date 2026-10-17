# Roadmap

The delivery plan for **Durable, Distributed Runtime for LangGraph Agents**: what we build, in what order, and how we know each part is done.

**Sources of truth for scope**
- Base spec: [`Project_4_Detailed_Requirements_K8s.pdf`](requirements/Project_4_Detailed_Requirements_K8s.pdf). Requirements are `R<section>.<n>` and acceptance criteria are `AC<n>`.
- [CR-001 — Chat sessions](requirements/CR-001-chat-sessions.md): accepted. Adds §12 (R12.x), fixes F1–F3, AC18–AC21.
- [CR-002 — Per-run sandboxes](requirements/CR-002-run-sandboxes.md): accepted. Adds §13 (R13.x), AC22–AC25.
- [CR-003 — Harness guardrails](requirements/CR-003-harness-guardrails.md): accepted. Adds §14 (R14.x): budgets, loop detection, least privilege, untrusted content, kill switch; AC26–AC32.
- [CR-004 — Agent definitions & hooks](requirements/CR-004-agent-definitions-and-hooks.md): accepted. Adds §15 (R15.x): one Markdown definition per agent (name, max turns, prompt, tools, limits, hooks; folder layout per CR-005); `session_start` / `turn_*` / `pre_tool` / `post_tool` / `session_end` hooks; AC33–AC36.
- [CR-005 — Sub-agents](requirements/CR-005-subagents.md): accepted. Adds §16 (R16.x): agents are folders (`agents/<name>/agent.md`), sub-agents are leaf sub-folders, run in-process by an orchestrator with status/progress/return tools, each checkpointed; AC37–AC42.
- [ADR-0001 — Repository layout](adr/0001-repository-layout.md): where every component lives, including how the spec's paths (`examples/`, `deploy/helm/`, `ops/grafana/`) map to this repo.

When this roadmap and a requirement disagree, the requirement wins and this file gets fixed.

---

## How we work

### Who builds what
- **Claude writes the code:** all of it, task by task, with tests. Before a core distributed piece (leases, fencing, reclaim, streaming, idempotency, sub-runs, sandboxes), Claude first explains the concept and the design, then implements it.
- **Sofiane reviews:** each task's diff before it's committed. Sofiane asks about anything unclear and approves or requests changes.
- Nothing moves to the next task until the current one is reviewed.

### Each phase follows the same loop
1. **Kick-off:** list the phase's tasks, one or two hours each, from its requirements. Note the concepts it teaches.
2. **Build:** one task at a time. Each task ends with its tests passing, `ruff` and `mypy --strict` clean, and a conventional commit.
3. **Demo:** run the phase's acceptance criteria or demo script.
4. **Summary:** write `docs/progress/phase-NN.md` (template below).
5. **Close:** update this file's status table, add to `CHANGELOG.md`, tag `phase-NN`.

### Definition of done (every phase)
- [ ] Every requirement listed for the phase is implemented or explicitly deferred, with a reason, in its summary
- [ ] Unit tests pass; integration tests pass where the phase has them
- [ ] The phase's ACs and demos pass and are scripted (`make …`), not just tried by hand
- [ ] `ruff`, `mypy --strict` and CI are green
- [ ] The phase summary is written, and design decisions are recorded in `docs/design.md`

### Phase summary template — `docs/progress/phase-NN.md`
```markdown
# Phase NN — <name>
## What we built        — the components, one paragraph each: what it is and what it does
## How it fits          — where it sits in the system; a small diagram if useful
## Requirements covered — R… / AC… → status (done | deferred: why)
## Concepts learned     — the distributed-systems / LangGraph / K8s ideas this phase taught
## Decisions & trade-offs
## Known issues & follow-ups
## How to try it        — the commands to run the demo
```

### Branching & commits
- **Nothing is committed directly to `main`.** Every change goes on a branch named `<type>/<topic>` (e.g. `feat/phase-01-durable-run`, `chore/config-and-secrets`). A pre-commit hook blocks commits on `main`.
- **One pull request per phase,** or per standalone change. Sofiane reviews it on GitHub; it merges only when CI is green. PRs are merged with a merge commit, not squashed, so the per-task commits stay visible in history.
- **Commits are small and conventional** (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`, `refactor:`). Each phase ends with a `phase-NN` tag on `main` after the merge.
- **Hooks:** run `make hooks` once per clone. They block secrets (gitleaks), fix formatting and check file hygiene before each commit. CI runs the same checks.

---

## Status

| # | Phase | Status |
|---|---|---|
| 0 | Foundations | ✅ Done — [summary](progress/phase-00.md) |
| 1 | Durable single run | ✅ Done — [summary](progress/phase-01.md) |
| 2 | Distributed workers | ✅ Done — [summary](progress/phase-02.md) |
| 3 | Streaming across replicas | ✅ Done — [summary](progress/phase-03.md) |
| 4 | Tools & human-in-the-loop | 🚧 In progress (`feat/phase-04-tools-hitl`) |
| 5 | Sub-runs, sub-agents & backpressure | — |
| 6 | Chat sessions + chat agent | — |
| 7 | Sandboxes | — |
| 8 | Research agent | — |
| 9 | Observability | — |
| 10 | Evals & CI quality gate | — |
| 11 | UI | — |
| 12 | Kubernetes | — |
| 13 | Release v1.0.0 | — |

Legend: ⏳ next · 🚧 in progress · ✅ done · ⏸ blocked

---

## Phases

Estimates are focused hours and only rough guesses; we'll correct them as we go. The total is **~180–235 h**: the base spec's 100–130 h, plus about 15–20 h for CR-001, 20–25 h for CR-002, 14–18 h for CR-003, 10–14 h for CR-004 and 10–14 h for CR-005.

### Phase 0 — Foundations · ~4–6 h
**Goal:** an empty but real project. Running `make up` brings up Postgres and Redis, `make test` runs, and CI is green.
- Repo layout: a monorepo with `backend/`, `frontend/`, `infra/` and `docs/` ([ADR-0001](adr/0001-repository-layout.md)); `uv`, Python 3.12, pinned dependencies, `ruff`, `mypy --strict`, pytest
- `pydantic-settings` config and `.env.example` (R9.1)
- Docker Compose with Postgres 16 + pgvector and Redis 7 (part of R9.2)
- Alembic and the first migration with every table from §9 + CR-001 §6 (`runs`, `run_events`, `run_results`, `tool_invocations`, `findings`, `documents`, `chunks`, `sessions`, `session_messages`)
- GitHub Actions: lint, type-check, unit tests
- `LICENSE` (Apache-2.0), README skeleton with the security posture (R9.4, as amended by CR-002), `CHANGELOG.md`

**Learn:** project tooling, migrations, config from environment.
**Done when:** a fresh clone runs `make up && make test` green.

### Phase 1 — Durable single run · ~14–18 h (actual: delivered with the lease and heartbeat pulled in from phase 2)
**Goal:** a toy 3-node graph runs to completion in one process, survives a restart, and its events can be replayed.
- Run model and state machine (R1.1); limits (R1.7)
- Postgres checkpointer with `thread_id` (R1.2); **prototype the epoch-aware checkpointer first (F1 / R2.10)**
- Persisted events with a per-run `seq` (R1.5)
- First API endpoints: `POST /runs`, `GET /runs/{id}`, `GET /runs/{id}/events`, `/healthz`
- Agent definition loader (`backend/agents/<name>/agent.md`, sub-agents as leaf sub-folders), strict schema, `runtime agents validate` in CI, per-run snapshots in `agent_definitions` (R15.1–R15.4, R16.1, R16.2; AC38)
- Limits hierarchy, where options can only tighten server ceilings, for wall-clock and steps (R1.7, R14.3)
- *Pulled in from phase 2:* lease acquisition with the exact R2.3 SQL, heartbeat, and reclaim counting toward `max_reclaims`, because "resume after a crash" can't be correct without them
- *Moved to phase 4:* `ScriptedModelProvider` (R14.20) and the model-call/tool/token/cost budgets. Nothing calls a model before phase 4, so there was no consumer to test them against

**Learn:** LangGraph state, supersteps, checkpointers, threads; transactional state transitions.
**Done when:** killing the process mid-run and calling resume finishes the run without re-running completed nodes.

### Phase 2 — Distributed workers · ~10–14 h (actual ~20 h; plan: [plans/phase-02.md](plans/phase-02.md))
**Goal:** multiple worker processes share the work safely.
- Redis Stream `runs:work`, consumer group, at-least-once delivery, `XAUTOCLAIM` (R2.1)
- Worker pool with `--concurrency` and `--workers` (R2.2)
- Reaper loop and `XAUTOCLAIM` reclaim (R2.4); the reclaim race (F2). *Leases, fencing and heartbeats already exist from phase 1*
- Fencing extended to every write (DB trigger or check on events, results, tool rows)
- Resume (R1.3), cooperative cancel (R1.6)
- Worker graceful shutdown on SIGTERM, release with `run.released` (the runtime part of R10.7)
- Least-privilege Postgres roles per component (R14.13); kill switch (R14.18); budgets survive reclaim

**Learn:** at-least-once delivery, leases, fencing tokens, zombies, the reasons for idempotency.
**Done when:** **AC2** (crash-and-resume) and **AC5** (zombie safety) pass via `make demo-crash`.

### Phase 3 — Streaming across replicas · ~6–8 h (actual ~12 h; plan: [plans/phase-03.md](plans/phase-03.md))
**Goal:** any API replica can stream any run without losing events.
- Redis Pub/Sub publish-after-persist; subscribe → replay → dedup → gap back-fill (R2.5). The code is generic over `run:{id}` and `session:{id}` channels (CR-001 amendment).
- SSE with `Last-Event-ID` and a 15 s heartbeat (CR-001 D3)
- Multiple API replicas + workers as local processes (Compose/containers in phase 12, as in phase 2)

**Learn:** pub/sub vs. persistent logs, ordering, exactly-once *display* on top of at-least-once delivery.
**Done when:** **AC3** passes via `make demo-replicas`, plus SC1–SC11 in the plan.

### Phase 4 — Tools & human-in-the-loop · ~8–10 h
**Goal:** tools are safe to retry, and runs can pause for a human.
- Tool registry with `side_effect`, `cache` and `isolation` (R3.4, R13.1)
- `ToolPolicy` (R3.2); idempotency wrapper and `tool_invocations` (R2.6)
- `interrupt()`, the approve endpoint, re-enqueue on approval (R1.4)
- Hook registry; `pre_tool` / `post_tool` hooks with the fixed check order, fail-closed and audited (R15.5, R15.7–R15.9)
- `ScriptedModelProvider` (R14.20) and model-call/tool budgets (R14.1), moved here from phase 1
- Deny-by-default grants per graph/node, risk classes, strict argument validation, audit events, result truncation (R14.9–R14.11, R14.17, R14.5)

**Learn:** idempotency keys, the outbox-style "record, then act" pattern, durable pauses.
**Done when:** **AC4** (approval survives restart) passes.

### Phase 5 — Sub-runs, sub-agents & backpressure · ~10–14 h
**Goal:** the research fan-out spreads across workers (child runs), and a main agent can orchestrate its sub-agents in-process (CR-005).
- Parent/child protocol, `waiting_children`, atomic `child_done`, fan-in and `partial` (R2.8)
- `max_children`, queue-depth metric, `429` with `Retry-After` (R2.9)
- Sub-run depth and descendant limits; child usage rolls up to its ancestors (R14.6)
- Sub-agent orchestrator: spawn/status/wait/cancel tools for the main agent, `report_progress`/`return_result` for sub-agents, per-sub-agent checkpoints and crash resume, limits, budget roll-up (R16.3–R16.9)
- `docs/design.md`: the trade-off of sub-runs vs. `Send`

**Learn:** distributed fan-out/fan-in, atomic counters, backpressure.
**Done when:** **AC6** (children run on more than one worker), **AC40** (status, return, cancel, timeout), **AC41** (crash resume) and **AC42** (budget roll-up) pass.

### Phase 6 — Chat sessions + chat agent · ~12–16 h
**Goal:** chat with an agent across many sessions, with a durable transcript.
- Sessions, turns, the one-active-turn rule (R12.1, R12.2); transcript with deterministic ids and fencing (R12.3, R12.4)
- Session SSE stream (R12.5); HITL and cancel in chat (R12.6, R12.7); session API (R12.10)
- `ModelProvider` with OpenAI + Ollama + `embed()` (R3.1, F3); `backend/src/agents/chat` agent with `search`, `retrieve`, `save_note` (R12.9)

**Learn:** LangGraph threads and `add_messages`; conversation state vs. transcript.
- `agents/chat/agent.md`; `session_start` / `turn_start` / `turn_end` / `session_end` hooks, idle-session archiving, `/agents` API (R15.6, R15.11)
- Model-call budget, soft→hard wrap-up, loop detection, retries with backoff, admission control (R14.2, R14.4, R14.7, R14.8)

- `chat/researcher` and `chat/data-analyst` sub-agents; `make demo-subagents`

**Done when:** **AC18**, **AC19**, **AC26–AC28** (runaway agent, loop, ceilings), **AC33–AC35** (definitions, tool hooks, session hooks) and **AC37**, **AC39** (parallel sub-agents, isolation) pass.

### Phase 7 — Sandboxes · ~10–12 h
**Goal:** risky tools run in a disposable, locked-down container per run.
- `sandbox-python` image, hardened (R13.3)
- `sandboxd` with the Docker backend behind a socket proxy, epoch fencing (R13.4), GC (R13.5)
- `run_python` tool (R13.7); durability rules (R13.6)
- Escape-test suite

**Learn:** container isolation primitives (namespaces, cgroups, capabilities, seccomp), least privilege, the Docker socket risk.
**Done when:** **AC22**, **AC23** and **AC24** pass via `make demo-sandbox-escape`.

### Phase 8 — Research agent · ~12–16 h
**Goal:** the full Planner → Approval → Researcher×N → Critic → Synthesizer example.
- `SearchTool` fixtures (R3.3); ingest and retrieval with pgvector (R4.5)
- Four agent folders (`agents/planner`, `researcher`, `critic`, `synthesizer`) composed by `backend/src/workflows/research` (R15.10)
- Planner, Researchers as child runs, Critic routing as a pure function, Synthesizer with the citation validator (R4.1–R4.4)
- ≥ 3 fixture sets, one deliberately thin (R4.6)

**Learn:** structured output, agent loops, RAG with pgvector, grounding and citation checks.
**Done when:** **AC1** (quickstart in under 5 min) and **AC7** (Critic loop) pass.

### Phase 9 — Observability · ~5–7 h
- OpenTelemetry → Collector → Jaeger, one trace across API → worker → children (R2.7, R7.1); JSON logs
- Prometheus metrics and Grafana dashboard (R7.2), including the session and sandbox metrics
- Compose `observability` profile
- Guardrail metrics, content-free logging, reproducible model-call attributes (R14.16, R14.19)

**Learn:** distributed tracing and context propagation, RED/USE metrics.
**Done when:** **AC8** passes: one trace spans every hop.

### Phase 10 — Evals & CI quality gate · ~6–8 h
- ≥ 20 research cases + ≥ 5 multi-turn chat cases; scorers; `make eval` (R7.3)
- CI gate against `evals/baseline.json`, `make eval-accept` (R7.4)
- ≥ 10 prompt-injection cases; the gate requires 0 policy violations (R14.15, AC30)
- Integration tests in CI with Compose (§8)

**Learn:** LLM evaluation, LLM-as-judge, regression gates.
**Done when:** **AC9** passes: CI green, including evals.

### Phase 11 — UI · ~14–18 h
- React 18 + TS strict + Vite + Tailwind + TanStack Query; client generated from OpenAPI (R6.5)
- Chat view: sessions sidebar, messages, tool and code cards, approval card, stop button (R12.11)
- Run live view with React Flow and child chips (R6.1); approval screen (R6.2); answer view (R6.3)
- SSE hook with `Last-Event-ID` reconnect; pure reducers with Vitest tests

**Learn:** event-sourced UI state, resilient streaming clients.
**Done when:** **AC10** and **AC20** pass.

### Phase 12 — Kubernetes · ~35–48 h
Follows the PDF's learning path: **raw YAML first, Helm last.**

| Step | Work | Covers |
|---|---|---|
| 12.1 Containerize | Images for api, worker, ui, `sandboxd`, `sandbox-python`; multi-stage, non-root, Trivy | R10.1 |
| 12.2 First deploy | kind with 3 nodes; raw YAML for Postgres, Redis, api, worker; one question works | R10.2, R10.3 |
| 12.3 Make it healthy | ConfigMap/Secret, probes, migration Job, Ingress with SSE | R10.4–R10.6 |
| 12.4 Make it survive | Graceful shutdown wiring, PDBs, topology spread, pod-kill and drain demos | R10.7, R10.8 |
| 12.5 Make it scale | HPA for api, KEDA for workers, scale demo | R10.9 |
| 12.6 Sandboxes on K8s | Kubernetes backend, `agent-sandboxes` namespace, RBAC, deny-all NetworkPolicy, quota | R13.4, CR-002 R10.x amendments |
| 12.7 Package & harden | Helm chart, Pod Security, NetworkPolicies, CI on kind | R10.10–R10.13 |

**Learn:** everything listed in the "You learn" lines of §10.
**Done when:** **AC11–AC17**, **AC21** and **AC25** pass.

### Phase 13 — Release v1.0.0 · ~3–5 h
- `docs/kubernetes.md` with measured numbers (R10.14); `docs/design.md` complete
- README: quickstart, architecture, security posture, badges
- `CHANGELOG.md`, tag `v1.0.0`

**Done when:** every AC is green.

---

## Backlog (SHOULD items — picked up when time allows)

| Item | Source |
|---|---|
| Fleet panel in the UI | R6.6 |
| Judge calibration (Cohen's κ) | R7.5 |
| Cloud deployment (AKS/EKS/GKE) | R10.15 |
| Multi-arch images + SBOM | R10.1 |
| WebSocket endpoint | §5, CR-001 D3 |
| Context-window summarisation | R12.8 |
| `deep_research` tool from chat | R12.9 |
| `fetch_url` with egress allowlist | R13.8 |
| gVisor runtime + sandbox warm pool | R13.9 |
| External Secrets / Sealed Secrets docs | R10.4 |

## Roadmap after v1.0 (out of scope)
Runs dashboard & trace view · gateway/policy-engine adapters · cross-run memory · auth & multi-user sessions · message editing and branching · NoSQL read model via outbox · Copilot SDK adapter · session-scoped sandboxes · microVM isolation · GitOps, service mesh, multi-cluster.
