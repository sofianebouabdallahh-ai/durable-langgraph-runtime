# Local release plan: clone it, run it, tell us what you think

**Status:** Accepted (2026-10-17); **L1 delivered** ([summary](../progress/phase-L1.md)); **L2 is the chat UI** (re-ordered, §5) · **Comes before:** the [beta platform](../architecture/beta-platform.md), which waits for this release's feedback · **Builds on:** phases 0–6 · **Product scope:** [CR-006](../requirements/CR-006-agent-studio.md), in single-user form

## 1. Goal

Anyone can **clone the repository, run one setup command, and use the product on their own machine**, everything in Docker. They:
- chat with agents;
- build their own agents, sub-agents and instruction-only skills in the UI;
- plug in their own model: a local Ollama, an OpenAI key, an Azure AI Foundry deployment, any OpenAI-compatible endpoint;
- optionally watch it all run on a local Kubernetes cluster with dashboards.

Their feedback decides what the hosted beta becomes.

**What "done" means:**
- A tester with Docker installed goes from `git clone` to a working chat in the browser in **under 10 minutes**, without installing Python, Node, uv or make, and without editing a file by hand.
- They can build an agent in the UI without seeing Markdown.
- They can send us feedback in two clicks.

## 2. Who it's for

Early testers: developers, and curious non-developers, who are comfortable installing Docker Desktop and pasting one command. Tested on:

| OS | Requirements | Notes |
|---|---|---|
| macOS (Apple Silicon, Intel) | Docker Desktop or OrbStack, 8 GB RAM free (16 GB with a local model) | For local models, the **native Ollama app** (GPU); Ollama in Docker is CPU-only on a Mac |
| Windows 10/11 | Docker Desktop with WSL 2 | `setup.ps1`; Ollama for Windows uses the GPU natively |
| Linux | Docker Engine + Compose v2 | Ollama in Docker can use an NVIDIA GPU (`--gpus`) |

## 3. What changes from today

| Today | Local release |
|---|---|
| Needs `uv`, `make`, Python on the host | **Only Docker.** API, workers and UI are images; a setup script does the rest |
| `.env` copied from an example; secrets typed by hand | Setup **generates** strong local passwords and asks a few questions |
| No UI: the API, `runtime chat`, curl | **A web UI**: chat + Agent Studio (single user) |
| Model chosen by environment variables | **Settings → Models** in the UI: add a connection, test it, pick per agent |
| Agents are files in `backend/agents/` | Built-in agents stay files; **user agents and skills are stored locally** (in Postgres), with import/export |
| Observability later | Optional dashboards (Grafana, Jaeger) in Compose, or a local Kubernetes mode with its own monitoring |
| Feedback by talking to us | **In-app feedback**, a diagnostics bundle, GitHub issue templates |

**Deliberately not in the local release** (they belong to the hosted beta, where several people share one system): login and roles (G1), Key Vault encryption (G2: locally the key never leaves the machine), fair multi-tenant scheduling (G4), and the Azure deployment (G7).

## 4. Design

### 4.1 One command

```bash
git clone https://github.com/<org>/durable-langgraph-runtime && cd durable-langgraph-runtime
./setup.sh          # macOS / Linux        (Windows: .\setup.ps1)
```

The setup script is idempotent, so it is safe to run again:
1. **Checks prerequisites:** Docker running, Compose v2, free ports (3000, 8000), disk and RAM. It prints a clear fix for each failure (with OS-specific links).
2. **Creates `.env`** from `.env.example` if it doesn't exist:
   - generates random Postgres and Redis passwords and the local encryption key;
   - sets the file to user-only permissions (`chmod 600`; the ACL equivalent on Windows).
   - It never overwrites an existing value.
3. **Asks** (or takes flags, for scripted installs):
   - **Model:**
     - *Local (Ollama)*: detects a native Ollama, or offers the Compose profile on Linux.
     - *OpenAI*: an API key.
     - *Azure AI Foundry*: endpoint + key + deployment.
     - *Other OpenAI-compatible*: base URL + key.
     - *Skip*: the scripted demo model, so it works with nothing at all.
   - **Mode:** *Compose* (default), or *local Kubernetes* (§4.6).
4. **Pulls or builds the images,** starts the stack, waits for health, runs migrations (`runtime db upgrade`), loads the built-in agents and the search fixtures.
5. **Runs a smoke check:** a scripted chat turn end to end. With a real model, also the model's capability check (tool call + streaming).
6. **Opens `http://localhost:3000`.**

The same steps are also Make targets for contributors (`make setup`, `make start`, `make stop`, `make update`, `make doctor`, `make reset`).

### 4.2 Images

| Image | Contents | Notes |
|---|---|---|
| `runtime` | The Python backend: API, worker, CLI (one image, command decides the role) | Multi-stage: `uv sync --frozen` in a builder, slim runtime stage; **non-root**, read-only root filesystem, healthcheck; pinned base digest |
| `ui` | The web UI, built static, served by a small web server that proxies `/api` to the API | Same origin: no CORS; SSE buffering off |
| (existing) `postgres` (pgvector), `redis`, optional `ollama` | | Pinned versions (the 2-week cooldown rule) |

- **Published images:** CI builds multi-arch images (amd64 + arm64) on every tag and pushes them to GitHub Container Registry. Setup pulls by default (fast) and builds locally with `--build` (for contributors). Images are scanned in CI (e.g. Trivy), and an SBOM is attached to each release.

### 4.3 Compose stack

```
 browser ─► ui :3000 ─► api :8000 ─► postgres (volume)   redis (volume)
                            │
                 worker ×2 (concurrency 4)  ─► model: Ollama (host or profile) / OpenAI / Foundry / …
 profiles:  llm (Ollama in Docker, Linux+GPU)   observability (otel-collector, Prometheus, Grafana, Jaeger)
```

- **Ports bind to `127.0.0.1` only.** Nothing is reachable from the network unless the user changes it on purpose (documented, with a warning).
- **Volumes:** `postgres-data`, `redis-data`, `ollama-models`. `make stop` keeps data; `make reset` deletes it, with a confirmation.
- **Restart policy** `unless-stopped`, so it survives a reboot. Workers are disposable (the runtime's whole point: kill one and watch the run continue).

### 4.4 Single-user mode

The runtime is built for many users and workers, but the local release has **one user and no login**.
- A `local` workspace and a `local` user exist from the first migration, and everything is created under them. (The identity layer from the beta plan, P7, will put real users where `local` is; the schema is the same.)
- **Model connections** (R18.2) are stored in Postgres, the key encrypted with the **local key** that setup generates in `.env` (AES-256-GCM). It's the same envelope design as the beta, with Key Vault replaced by a file-based key. Keys never leave the machine except to the model provider; they are never shown again in the UI and never logged.
- **The Agent Studio** (R17.1–R17.4, instruction-only skills): drafts, versions, publish, playground, import/export of `.agent.md` and skill folders. Built-in agents are read-only and copyable.

### 4.5 The UI (first version)

- **Chat:**
  - sessions sidebar; streaming replies; tool-call cards (args, result, duration, cached);
  - sub-agent cards with live progress; the approval card; the stop button.
  - It's the R12.11 chat view.
- **Agent Studio:**
  - the form from R17.2 (name, purpose, instructions, model, tools as plain-language cards, helpers, skills, cost presets);
  - "describe your agent" (the builder agent drafts the form);
  - the playground; versions; import/export.
- **Skills library:** create or upload (zip / folder), the scan report, attach to agents and helpers.
- **Settings → Models:** add a connection (provider templates for Ollama / OpenAI / Foundry / custom), **Test**, choose defaults.
- **Built for people who don't code:** plain words (no "run", "epoch" or "lease" in the main screens); a "What happened?" panel per turn for the curious (events, usage, cost).
- **Engineering standard as in R6.5:**
  - React + TypeScript strict; a client generated from the OpenAPI spec;
  - the SSE hook with `Last-Event-ID` resume;
  - pure reducers unit-tested with Vitest;
  - Playwright for the main flows;
  - sanitised Markdown rendering (no raw HTML).

### 4.6 Watching it run: dashboards or local Kubernetes

- **Compose + dashboards** (`./setup.sh --observability`, the default for the curious):
  - OpenTelemetry collector → **Jaeger** (traces: turn → model call → tool) and **Prometheus** → **Grafana**.
  - Pre-built dashboards: queue depth and wait, runs by status, reclaims, model latency, tokens and cost, throttles.
  - Links from the UI's "What happened?" panel to the trace.
- **Local Kubernetes** (`./setup.sh --kubernetes`):
  - The same images on a local cluster: Docker Desktop's built-in Kubernetes, or **kind / k3d** (the script creates one).
  - A **Helm chart** installs the stack; **kube-prometheus-stack** adds monitoring.
  - Users can open **Headlamp** (or k9s) to watch pods.
  - `make k8s-demo-podkill` deletes a worker pod mid-turn: the turn completes elsewhere. Phase 12's chaos demos come down to a laptop.
  - This mode is optional and documented as "for the curious"; Compose stays the default.

### 4.7 Updating and keeping data

- **Releases are tags** (`v0.1.0`, …) with a changelog. `./setup.sh --update` (or `make update`):
  - pulls the new tag's images;
  - **backs up the database first** (`pg_dump` to `backups/`);
  - runs migrations (expand/contract, so an update never breaks data);
  - restarts.
- **Export / import:** agents, skills and conversations to a zip, to move machines or share an agent.

### 4.8 Feedback and diagnostics

- **"Send feedback"** in the UI: a short form (what were you doing, what happened, how did it feel, a 1–5 rating). It opens a pre-filled **GitHub issue**, or, if the tester prefers, downloads it to send by email. Nothing is sent without the user's click.
- **`./setup.sh --doctor` / `make doctor`:** a diagnostics bundle (versions, service health, recent logs, configuration with **all secrets redacted** by the same redaction as the runtime's, R14.12). It is written to a zip the user can attach to an issue.
- **GitHub issue templates:** bug, idea, "my agent didn't do what I expected" (with an export of the agent and the turn).
- **Telemetry:** **off by default.** If a tester opts in, it is anonymous usage counts only (feature used, errors by type, versions), never content, keys or prompts. It is documented field by field.

### 4.9 Documentation

- **README → "Try it"** at the top: prerequisites, the one command, a screenshot.
- `docs/setup/`: macOS, Windows (WSL 2), Linux; local models (which Ollama model for how much RAM; native vs Docker); adding OpenAI / Foundry / others; troubleshooting (ports in use, Docker not running, out of memory, a model that can't call tools).
- **"Your first agent"** tutorial: build a helper, attach a skill, test, publish.
- **A tester guide:** what we want feedback on, and how to send it.
- **A security note:** what runs locally, where keys are stored, how to delete everything.

## 5. Phases

| Phase | Name | Contents | Estimate | Done when |
|---|---|---|---|---|
| **L1** | **Containerise & one-command setup** | Dockerfiles (`runtime`, later `ui`), the full Compose stack (api, workers, profiles), `setup.sh` / `setup.ps1` (checks, generated `.env`, model questions, smoke test), `doctor`, multi-arch images to GHCR in CI, image scanning | ~14–18 h | Clone → working chat (API + `runtime chat`) on macOS, Windows and Linux with only Docker |
| **L2** | **Chat UI** | The chat view of §4.5 (sessions, streaming, tool and sub-agent cards, approval, stop, "What happened?"), the SSE hook, the `ui` image in the `app` profile, Playwright against the Compose stack | ~18–24 h | AC20 in the browser; a working end-to-end product (milestone M1) |
| **L3a** | **Agent Studio: agents & helpers** | Agents in the DB as versions, turns pinned by hash, the form (tools, helpers, presets, protections), test chat, publish, history, import/export ([plan](phase-L3a.md)) | ~22–28 h | AC47; build, test and publish an agent with a helper without Markdown |
| **L3b** | **Agent Studio: your own model** | Model connections stored encrypted (local key) + Test; a model per agent and helper | ~14–18 h | AC44, AC45 |
| **L3c** | **Agent Studio: skills & "describe your agent"** | Instruction-only skills (spec, upload, scan, attach); the builder agent; "improve my instructions" | ~16–20 h | AC43 with 2–3 non-technical testers (M2) |
| **L4** | **Dashboards & local Kubernetes** | Observability profile with dashboards; Helm chart; kind mode; kube-prometheus-stack; pod-kill demo | ~16–22 h | `--observability` and `--kubernetes` both work from a clean machine |
| **L5** | **Release v0.1 & feedback loop** | Docs (§4.9), issue templates, in-app feedback, update + backup, opt-in telemetry, the first tagged release | ~10–14 h | 5–10 external testers installed it; feedback collected (M3) |

**Re-cut (2026-10-17):** the Studio is built by feature (agents → models → skills), each slice with its backend and its screens, instead of a backend phase followed by a screens phase.

**Re-ordered (2026-10-17):** the chat UI moved ahead of the Studio backend. The API already serves everything a chat UI needs, so this reaches a working product in the browser about 45 h sooner, and the Studio then plugs into a UI testers already use. The [roadmap](../roadmap.md) tracks the status.

**≈ 105–140 focused hours to v0.1.** Each phase keeps the working agreement: plan → success criteria → build → e2e 5× → summary → PR.

**After feedback:** the [beta platform](../architecture/beta-platform.md) (identity, Key Vault, fair scheduling, Azure). Much of L1–L5 carries over unchanged: the images, the UI, the Studio, connections, dashboards and the Helm chart.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Docker setup differs per machine (ports, memory, Apple Silicon, WSL) | Prerequisite checks with exact fixes; tested on all three OSes in CI (setup in a fresh VM / runner) and by hand before each release |
| Local models are slow or can't call tools | Setup recommends a model for the machine's RAM; the capability test refuses models that can't call tools; the native Ollama app on macOS/Windows |
| Testers expose ports or keys by accident | `127.0.0.1` binding; generated secrets; `.env` permissions; keys encrypted at rest, never shown again; a security note |
| Updates break someone's data | A backup before every update; expand/contract migrations; tested upgrade from the previous tag in CI |
| A large first download (images + a model) | Pull pre-built images; model optional (the scripted demo works offline); sizes stated up front |

## 7. Decisions needed

1. **Distribution:** pre-built images on GitHub Container Registry (fast; recommended) or build on the tester's machine?
2. **Kubernetes mode:** Docker Desktop's built-in Kubernetes, or kind/k3d created by the script (recommended: kind; same on every OS)?
3. **Feedback channel:** GitHub issues (recommended: public and traceable), or a private form?
4. **License for testers:** the repository is MIT today. Keep it open, or make it private with invited testers?
