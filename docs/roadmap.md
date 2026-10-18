# Roadmap

The delivery plan for **Durable, Distributed Runtime for LangGraph Agents**: what we build, in what order, and how we know each part is done.

**Where we are (2026-10-17):** the runtime core is done (phases 0–6). In the local release, L1 (one-command setup) and **L2 (the chat UI, now called _Nuria_)** are merged: milestone **M1** is reached. L3a (agents and helpers), L3b (your own model) and **L3c (skills and "describe your agent") are merged**. **M2** is declared once 2–3 non-technical testers pass the [tester script](setup/tester-script.md). Next: L4, dashboards and local Kubernetes.

**Sources of truth for scope**
- Base spec: [`Project_4_Detailed_Requirements_K8s.pdf`](requirements/Project_4_Detailed_Requirements_K8s.pdf). Requirements are `R<section>.<n>`; acceptance criteria are `AC<n>`.
- Change requests, all accepted:
  - [CR-001](requirements/CR-001-chat-sessions.md): chat sessions.
  - [CR-002](requirements/CR-002-run-sandboxes.md): per-run sandboxes.
  - [CR-003](requirements/CR-003-harness-guardrails.md): harness guardrails.
  - [CR-004](requirements/CR-004-agent-definitions-and-hooks.md): agent definitions & hooks.
  - [CR-005](requirements/CR-005-subagents.md): sub-agents.
  - [CR-006](requirements/CR-006-agent-studio.md): Agent Studio, bring your own model, instruction-only skills.
- Plans:
  - [local release](plans/local-release.md): what testers run on their machine;
  - [beta platform](architecture/beta-platform.md): the hosted, multi-user system, after the feedback.
- [ADR-0001](adr/0001-repository-layout.md): where every component lives.

When this roadmap and a requirement disagree, the requirement wins and this file gets fixed.

---

## The road at a glance

```
 DONE                      LOCAL RELEASE (on testers' machines)                    HOSTED BETA (after feedback)
 ────────────────────      ─────────────────────────────────────────────────      ────────────────────────────────
 0–6 runtime core    ──►  L1 ✅ ─► L2 ✅ ─► L3a ✅ ─► L3b ✅ ─► L3c ✅ ─► L4 ─► L5 ──►  P7 ─► P8 ─► P9 ─► P10 ─► P11 ─► P12
 durable runs, workers,     setup  chat  Studio Studio dash- v0.1               identity keys Studio fair  UI   Azure
 streaming, tools, HITL,          UI    backend UI    boards feedback                       multi- sched.     closed
 sub-agents, chat, models           ▲            ▲    + K8s    ▲                                 user              beta
                                    M1           M2            M3                                                  M4
```

| Milestone | After | What a person can do | Who tries it |
|---|---|---|---|
| **M1 · It works in the browser** | L2 | `./setup.sh`, open `localhost`, chat with the built-in agent: streaming replies, tools, sub-agents, approvals, stop; survives a worker crash | Us, plus 1–2 friendly developers (`v0.1.0-alpha`) |
| **M2 · Build your own agent** | L3c | Add their own model (Ollama, OpenAI, Foundry, any compatible endpoint), create an agent with helpers and skills, without seeing Markdown | 2–3 non-technical testers (AC43) |
| **M3 · v0.1 for testers** | L5 | All of the above, plus optional dashboards and local Kubernetes, safe updates, feedback in two clicks | 5–10 external testers |
| **M4 · Closed beta** | P12 | The hosted, multi-user version: sign in, shared agents, the workspace key, fair scheduling | Invited beta users |

---

## Status

| Phase | Name | Status | Estimate |
|---|---|---|---|
| 0–6 | Runtime core (see [Done](#done-the-runtime-core-phases-06)) | ✅ Done | — |
| **L1** | Containerise & one-command setup | ✅ Done ([plan](plans/phase-L1.md), [summary](progress/phase-L1.md)) | ~14–18 h |
| **L2** | Chat UI (Nuria) → M1 | ✅ Done ([plan](plans/phase-L2.md), [summary](progress/phase-L2.md)) | ~18–24 h |
| **L3a** | Agent Studio: agents & helpers | ✅ Done ([plan](plans/phase-L3a.md), [summary](progress/phase-L3a.md)) | ~22–28 h |
| **L3b** | Agent Studio: your own model | ✅ Done ([plan](plans/phase-L3b.md), [summary](progress/phase-L3b.md)) | ~14–18 h |
| **L3c** | Agent Studio: skills & "describe your agent" → M2 | ✅ Done ([plan](plans/phase-L3c.md), [summary](progress/phase-L3c.md)); M2 after the tester sessions | ~16–20 h |
| **L4** | **Dashboards & local Kubernetes** | ⏳ Next | ~16–22 h |
| L5 | Release v0.1 & feedback loop → M3 | — | ~10–14 h |
| P7–P12 | Hosted beta → M4 | After the feedback | ~160–200 h |
| P13–P16 | Sandboxes, research agent, evals, AKS | After the beta opens | ~65–90 h |

Legend: ⏳ next · 🚧 in progress · ✅ done · ⏸ blocked

**M1 reached.** **To M2 (build your own agent): ~30–38 h.** **To M3 (v0.1): ~56–74 h.** Estimates are focused hours and rough; we correct them as we go.

---

## The local release

The full design is in [plans/local-release.md](plans/local-release.md). Everything runs in Docker on the tester's machine, for one user, with no login.

**Re-ordered (2026-10-17):** the chat UI comes **before** the Studio backend. The API already has everything a chat UI needs (sessions, the SSE stream with `Last-Event-ID`, approvals, cancel, agents), so a UI on top of it gives a working end-to-end product (M1) about 45 h sooner. The Studio then plugs into a UI that testers already use.

### L1 — Containerise & one-command setup ✅
The `runtime` image (non-root, read-only, tini); the Compose `app` profile (`migrate`, `api`, 2 workers) under least-privilege logins; `setup.sh` / `setup.ps1`; `runtime smoke` and `runtime doctor`; the container e2e; CI with image scanning; multi-arch release workflow.
**Done:** a fresh clone reaches a passing chat turn in 48 s cold on CI, using only Docker.
**Open:** the first `v*` tag (multi-arch publish); a real Windows run of `setup.ps1`.

### L2 — Chat UI (Nuria) ✅ → M1
**Goal:** open `http://localhost:<port>` after `./setup.sh` and chat.
- **The app:** React + TypeScript strict + Vite + Tailwind + TanStack Query; an API client generated from the OpenAPI spec (R6.5).
- **The chat view (R12.11):**
  - the sessions sidebar;
  - streaming replies;
  - tool-call cards and sub-agent cards with live progress;
  - the approval card and the stop button;
  - safe Markdown (no raw HTML);
  - a "What happened?" panel per turn.
- **The stream client:** an SSE hook with `Last-Event-ID` resume; pure reducers unit-tested with Vitest.
- **The `ui` image:** unprivileged nginx serving the static build and proxying `/api` (SSE buffering off), so there's one origin and no CORS. Added to the Compose `app` profile; `setup.sh` prints its URL and the smoke test checks it.
- **Tests:** Playwright against the real container stack, 5× (send, stream, kill a worker mid-turn, approve, stop, reload mid-reply); in CI.

**Done when:** **AC20** (resume the conversation after a reload and a lost stream) passes in the browser, and the Playwright flows pass 5/5 against the Compose stack.

**Re-cut (2026-10-17): the Studio by feature, not by layer.** L3 (backend) + L4 (screens) became three slices, each with its backend *and* its screens, so every PR adds something to click.

### L3a — Agent Studio: agents & helpers · ~22–28 h ([plan](plans/phase-L3a.md))
- **Agents in the database as versions** (draft → published → archived; a published version is immutable); built-in agents stay files and can be copied.
- **Every turn pins its agent by hash** (R15.4, finished here): publishing never changes a running conversation; the next turn uses the new version.
- **The form:** name, purpose, instructions, tools as plain-language cards, helpers (sub-agents) with their own instructions and tools, limit presets, protections. One validator for files and the Studio, with issues shown next to each field.
- **Test chat, then publish:** draft turns get a test budget, and approval-gated tools are simulated. Plus history and restore, import/export of `.agent.md`, and idempotent sends.

**Done when:** **AC47**, and a person builds, tests and publishes an agent with a helper without seeing Markdown (5/5 in the browser).

### L3b — Agent Studio: your own model · ~14–18 h
- **Settings → Models:** connections (Ollama / OpenAI / Foundry / compatible), the key encrypted with the local key (AES-256-GCM), **Test** (the capability check), defaults.
- **A model per agent and per helper** in the form.

**Done when:** **AC44** (a local Ollama and a Foundry or OpenAI key, used by different helpers in one conversation) and **AC45** (the key appears nowhere).

### L3c — Agent Studio: skills & "describe your agent" · ~16–20 h → M2
- **Instruction-only skills:** create or upload, the scan, attach to agents and helpers.
- **"Describe your agent":** the builder agent drafts the form. Plus "improve my instructions".

**Done when:** **AC43**: a non-technical tester creates, tests and publishes an agent with a helper and a skill, without help.

### L4 — Dashboards & local Kubernetes · ~16–22 h
- `./setup.sh --observability`: OpenTelemetry → Jaeger, Prometheus, Grafana dashboards (runs, queue, workers, model calls, cost); links from "What happened?" to the trace (R2.7, R7.1, R7.2).
- `./setup.sh --kubernetes`: a kind cluster, a Helm chart, kube-prometheus-stack; the pod-kill demo.

**Done when:** **AC8** (one trace spans every hop); both modes work from a clean machine.

### L5 — Release v0.1 & feedback loop · ~10–14 h → M3
- In-app "Send feedback" (a pre-filled GitHub issue or a download; nothing sent without a click); issue templates.
- `./setup.sh --update` completed: backup, then pull and migrate; an upgrade from the previous tag tested in CI.
- Opt-in, content-free telemetry; docs ([local-release §4.9](plans/local-release.md)).
- Tag `v0.1.0`.

**Done when:** 5–10 external testers have installed it and their feedback is collected.

---

## The hosted beta (after the feedback)

Designed in [architecture/beta-platform.md](architecture/beta-platform.md), and **re-planned after M3's feedback.** Much of the local release carries over unchanged: the images, the UI, the Studio, connections, dashboards and the Helm chart.

| Phase | Name | Closes gap | Gate |
|---|---|---|---|
| P7 | Identity & tenancy: OIDC, workspaces, roles, audit log | G1, G8 (audit) | AC48 |
| P8 | Model connections & keys: Key Vault envelope encryption, quotas | G2 | AC44, AC45 |
| P9 | Studio for teams: sharing agents in a workspace, skill trust | G9, G3 | AC43 (API), AC47 |
| P10 | Fair, safe scheduling: lanes, per-tenant caps, per-connection limits, retention | G4, G5, G6 | A flood in workspace A doesn't move p95 queue wait in B |
| P11 | UI for teams: sign-in, sharing, the workspace key, roles | G10 | AC43, AC20 |
| P12 | Beta deployment on Azure: IaC, Container Apps, Key Vault, telemetry, SLOs, load test | G7, G8 | Launch checklist; **closed beta opens** (M4) |

**After the beta opens:**

| Phase | Name | Gate |
|---|---|---|
| P13 | Sandboxes, then skills with scripts (CR-002, G11) | AC22–AC24, AC46 |
| P14 | Research agent, as a Studio template | AC1, AC7 |
| P15 | Evals & CI quality gate, with injection evals | AC9, AC30 |
| P16 | Kubernetes on AKS (the scale-up path; optional) | AC11–AC17, AC21, AC25 |

### Where the original phases 7–13 went

| Original phase | Now |
|---|---|
| 7 Sandboxes | P13: the beta has instruction-only skills, so code execution waits |
| 8 Research agent | P14: built as a Studio template |
| 9 Observability | L4 (local dashboards), then P12 (hosted telemetry and SLOs) |
| 10 Evals & CI gate | P15 |
| 11 UI | L2 (chat), L3a–L3c (Studio), P11 (teams) |
| 12 Kubernetes | L4 (kind + Helm, locally), then P16 (AKS) |
| 13 Release v1.0.0 | L5 is v0.1 for testers; v1.0 comes once the beta is stable |

---

## Done: the runtime core (phases 0–6)

| # | Phase | What it delivered | Summary |
|---|---|---|---|
| 0 | Foundations | Repo layout, uv, config, Compose (Postgres + Redis), migrations, CI | [phase-00](progress/phase-00.md) |
| 1 | Durable single run | Run state machine, checkpointer, persisted events, leases and heartbeat, agent definitions | [phase-01](progress/phase-01.md) |
| 2 | Distributed workers | Redis Streams work queue, reclaim, fencing on every write, graceful release, least-privilege roles, kill switch (AC2, AC5) | [phase-02](progress/phase-02.md) |
| 3 | Streaming across replicas | Publish-after-persist, replay + dedup + gap back-fill, SSE with `Last-Event-ID` (AC3) | [phase-03](progress/phase-03.md) |
| 4 | Tools & human-in-the-loop | Tool registry and policy, idempotent tool calls, durable approvals, hooks, scripted model (AC4) | [phase-04](progress/phase-04.md) |
| 5 | Sub-runs, sub-agents & backpressure | Child runs and fan-in, admission control, the in-process sub-agent orchestrator (AC6, AC40–AC42) | [phase-05](progress/phase-05.md) |
| 6 | Chat sessions, guardrails, real models | Sessions and transcript, budgets and loop detection, retries and breaker, OpenAI / Ollama / Foundry, token streaming, the chat agent (AC18, AC19, AC26–AC28, AC33–AC35, AC37, AC39) | [phase-06](progress/phase-06.md) |

---

## How we work

### Who builds what
- **Claude writes the code:** all of it, task by task, with tests. Before a core distributed piece, Claude first explains the concept and the design, then implements it.
- **Sofiane reviews** each phase's PR, asks about anything unclear, and approves or requests changes.

### Each phase follows the same loop
1. **Plan:** research, design, tasks, and measurable success criteria in `docs/plans/phase-XX.md`.
2. **Build:** task by task, with tests; `ruff`, `mypy --strict` (and `tsc --strict`, ESLint and Vitest for the UI) clean; conventional commits.
3. **Validate end to end** with real processes or containers, each scenario **5×**, and in CI.
4. **Summary:** `docs/progress/phase-XX.md`, with every success criterion's measured result.
5. **Close:** one PR; merged when Sofiane says so; `CHANGELOG.md`; tag `phase-XX` on `main`; this file's status table updated.

### Definition of done (every phase)
- [ ] Every requirement in the phase is implemented, or deferred with a reason in its summary
- [ ] Unit and integration tests pass; the e2e scenarios pass 5/5 and are scripted (`make …`)
- [ ] Linters, type checkers and CI are green
- [ ] Best practices applied and design patterns named in `docs/design.md`
- [ ] The summary is written

### Branching & commits
- **Nothing is committed directly to `main`.** Every change goes on a `<type>/<topic>` branch; a pre-commit hook blocks commits on `main`.
- **One PR per phase,** or per standalone change, merged with a merge commit (per-task commits stay visible) once CI is green.
- **Small conventional commits** (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`, `refactor:`).
- **Hooks:** `make hooks` once per clone (gitleaks, formatting, file hygiene); CI runs the same checks.
- **Supply chain:** dependencies locked with a 2-week cooldown; GitHub Actions pinned to commit SHAs; base images pinned by digest.

---

## Backlog (picked up when time allows)

| Item | Source |
|---|---|
| Run live view with React Flow, fleet panel | R6.1, R6.6 |
| Context-window summarisation | R12.8 |
| `deep_research` tool from chat | R12.9 |
| `fetch_url` with an egress allowlist | R13.8 |
| WebSocket endpoint | §5, CR-001 D3 |
| Judge calibration (Cohen's κ) | R7.5 |
| gVisor runtime, sandbox warm pool | R13.9 |
| `setup.ps1` tested on a real Windows machine | L1 |
