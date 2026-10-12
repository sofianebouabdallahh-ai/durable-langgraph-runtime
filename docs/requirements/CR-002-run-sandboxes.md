# CR-002 — Per-run sandbox containers

| | |
|---|---|
| **Status** | Accepted (2026-10-11) — option B |
| **Date** | 2026-10-11 |
| **Depends on** | CR-001 (chat sessions) |
| **Scope** | New §13 Sandboxing; amendments to R3.4, R9.4, §10 (R10.1, R10.3, R10.11), §8, §11 |

## 1. Motivation

The base spec says plainly (R9.4) that tools *"execute with network access and no sandbox"*. We want each agent run to be isolated in its own container, so that:

- **T1 — Prompt injection.** A document or search result that tricks the model into running hostile tool input can't reach our database, secrets or network.
- **T2 — Cross-run leakage.** One run, or one user's session, can't see another run's files or memory.
- **T3 — Resource exhaustion.** A runaway tool (infinite loop, memory hog, fork bomb) can't take down the worker and the other runs on it.
- **T4 — Secret exposure.** Tool code never sees `OPENAI_API_KEY`, database passwords or a Kubernetes token.

## 2. Decision

### D1 — Isolate *tool execution* per run, not the whole agent loop *(accepted)*

There are two ways to read "each agent run in its own container":

| | **A. The whole run in its own container** | **B. Each run gets its own sandbox container for tools (recommended)** |
|---|---|---|
| What's inside the container | LangGraph loop, LLM calls, checkpointer, tools | Only sandboxed tool execution (`run_python`, …) |
| Does the container need DB credentials + LLM key? | **Yes**: it writes checkpoints and calls the model, so the secrets are inside the box with the untrusted input. **Fails T4.** | **No**: secrets stay in the trusted worker; the sandbox has none |
| Network | Needs Postgres, Redis and LLM egress, so it can reach the database. **Weak on T1.** | `none`: no network at all |
| Fit with the runtime (§2) | Breaks it: the worker pool, KEDA scaling on queue lag, the lease/heartbeat loop and graceful hand-off all assume long-lived workers. Every turn would pay a container cold start (~2–5 s with Python + LangGraph imports) | Keeps it intact: workers, leases, fencing and scaling are unchanged. The sandbox is a tool backend |
| Spawning containers | Every worker needs the Docker socket or the K8s API, which is root-equivalent on the host | Only one small service (`sandboxd`) holds that privilege, behind a narrow API |

**Decision:** option **B**. The danger in an agent is not its graph code (which is ours) but what its tools do with model-chosen input. Option A puts the secrets and the untrusted input in the same box, so it is *less* safe while costing more. Option B gives every run its own disposable container with no network and no secrets, and the trusted code stays outside.

**Consequence:** the current tools (`search` on fixtures, `retrieve`, `save_finding`, `save_note`) execute no untrusted code, so a sandbox would have nothing to contain. This CR therefore adds a code-execution tool, `run_python`, which is the realistic dangerous tool and the reason sandboxes exist.

## 3. New section — §13 Sandboxing

### R13.1 Tool isolation class — MUST
Each tool in the registry (R3.4) declares `isolation: "in_process" | "sandbox"`.
- `in_process`: trusted tools that need the database (`retrieve`, `save_finding`, `save_note`, fixture `search`).
- `sandbox`: tools that execute model-generated input (`run_python`; `fetch_url` per R13.8). The wrapper sends them to the run's sandbox. Policy, idempotency, tracing and transcript writes still happen in the worker, around the sandbox call.

### R13.2 One sandbox per run — MUST
- A sandbox is created **lazily**, on the run's first `sandbox` tool call, and is labelled `run_id`, `epoch` and `session_id`.
- It is **destroyed** when the run leaves `running` (terminal, interrupt, `waiting_children`, graceful release). The next turn, or the run resumed after approval, gets a fresh one.
- **It holds nothing that can't be rebuilt.** Files in the sandbox are scratch space. Anything that must outlive the run is returned as a tool result and stored in Postgres. This keeps the rule "Postgres is the only source of truth" (§2).
- Child runs (R2.8) get their own sandboxes. Sandboxes are never shared between runs.

### R13.3 Sandbox hardening — MUST
Every sandbox container:

| Control | Setting |
|---|---|
| Image | `sandbox-python`: slim Python 3.12, a fixed set of libraries (e.g. `numpy`, `pandas`), no compilers, no shell utilities beyond what Python needs. Under 200 MB. Scanned by Trivy in CI |
| User | Non-root UID; `no-new-privileges`; all capabilities dropped; default seccomp profile |
| Filesystem | Read-only root; `/workspace` and `/tmp` are `tmpfs` with a size cap (64 MB) |
| Network | `none` (Docker) / deny-all NetworkPolicy, ingress and egress (Kubernetes) |
| Resources | CPU 0.5, memory 256 MB, `pids` limit 64 |
| Environment | Empty: no secrets, no service account token |
| Per call | Wall-clock timeout (default 10 s, max 60 s); stdout/stderr capped at 64 KB and truncated with a marker |

Violating a limit (timeout, OOM, pids) returns a **tool error** that the agent sees (like a policy `Deny`, R3.2). It never crashes the worker.

### R13.4 `sandboxd` — the sandbox manager — MUST
A separate small service is the **only** component allowed to create containers. Workers call it over HTTP:

| Endpoint | Purpose |
|---|---|
| `POST /sandboxes` | `{run_id, epoch, session_id?}` → `{sandbox_id}`. Idempotent per `(run_id, epoch)` |
| `POST /sandboxes/{id}/exec` | `{epoch, code, timeout_s}` → `{stdout, stderr, exit_code, duration_ms, truncated, limit_hit?}` |
| `DELETE /sandboxes/{id}` | Destroy. Idempotent |
| `GET /healthz` · `GET /readyz` · `GET /metrics` | As in §5 |

**Fencing (extends R2.3):** `sandboxd` rejects `exec` with `409 stale_epoch` when the caller's epoch is lower than the newest sandbox epoch for that run, and it destroys the older sandbox when a newer epoch creates one. A zombie worker can't run code in a sandbox that now belongs to a reclaimed run.

Two pluggable backends, chosen with `SANDBOX_BACKEND`:
- **`docker`** (Compose): uses the Docker Engine API through a **socket proxy** that allows only container create, start, exec, inspect and delete. `sandboxd` never mounts the raw socket. The README states that Docker socket access is root-equivalent on the host, and why the proxy narrows it.
- **`kubernetes`**: creates a **Pod** per sandbox in the namespace `agent-sandboxes`, and execs with the `pods/exec` subresource. Its ServiceAccount has a namespaced Role limited to `pods` (create, get, list, delete) and `pods/exec` (create), in that namespace only.

### R13.5 Garbage collection — MUST
Every 30 s, `sandboxd` deletes sandboxes whose run is no longer `running` in Postgres, whose epoch is lower than the run's current epoch, or that are older than the run timeout (R1.7). This covers a worker killed in the middle of a run, which never gets to call `DELETE`. Orphans must be gone within 60 s.

### R13.6 Durability interplay — MUST
- **`run_python` is idempotent through R2.6:** the key includes the code, so after a reclaim a `done` call returns the stored result (`cached: true`) and doesn't re-execute.
- **A call that was in progress when the worker died re-executes in the *new* sandbox,** because its old key has a lower epoch (R2.6). Since the sandbox is stateless across epochs, code that depends on files written by an *earlier* call in the same run may then fail. That error goes to the agent as a normal tool error, and the agent can retry. This limitation is documented, and fixing it is on the roadmap (§7).
- If `sandboxd` is unavailable, the tool call fails with a retryable error. The run does **not** fail unless the agent gives up (max tool calls) or the run timeout hits.

### R13.7 `run_python` tool — MUST
`run_python(code: str)`, with `isolation: sandbox`, `side_effect: false` and `cache: true`. It is available to the chat agent (CR-001 R12.9) and to the research critic or synthesiser (optional). Results are rendered in the chat UI as a code/output card.

### R13.8 `fetch_url` with controlled egress — SHOULD
`fetch_url(url)` runs in the sandbox with egress allowed **only** through an HTTP proxy with a domain allowlist (`SANDBOX_EGRESS_ALLOWLIST`). Direct egress stays blocked. This lets research fetch real pages without giving model-chosen URLs a path to internal services such as Postgres, Redis, `sandboxd` or cloud metadata at `169.254.169.254`.

### R13.9 Stronger runtimes & warm pool — SHOULD
- **gVisor:** on Kubernetes, sandbox Pods use `runtimeClassName: gvisor` when it is available, which adds a user-space kernel between the code and the host. The README explains how containers and gVisor (or microVMs) differ as isolation boundaries.
- **Warm pool:** `sandboxd` keeps N pre-started sandboxes so the first `run_python` of a run skips the container cold start. Each sandbox is assigned to a run once and never reused.

## 4. Amendments to existing requirements

| Req | Change |
|---|---|
| **R3.4** | Tool declaration adds `isolation` (R13.1). The wrapper routes `sandbox` tools through `sandboxd`, passing the run's epoch. |
| **R9.4** | Replace *"tools execute with network access and no sandbox"* with: *"tools that execute model-generated input run in a per-run sandbox with no network and no secrets (§13); trusted in-process tools still run with the worker's privileges. Containers are not a perfect boundary; see R13.9."* |
| **R10.1** | A fourth image: `sandbox-python`. The `sandboxd` service reuses the Python base image with a different entrypoint. |
| **R10.3** | New workloads: `sandboxd` (Deployment, 2 replicas, ClusterIP Service reachable only from workers) and the `agent-sandboxes` namespace. |
| **R10.8** | `sandboxd` gets a PDB. The `agent-sandboxes` namespace has a ResourceQuota (e.g. max 40 pods, 20 CPU, 10 Gi). |
| **R10.11** | `sandboxd` is the **only** app pod with `automountServiceAccountToken: true`, and its Role is namespaced (R13.4). `agent-sandboxes` enforces the `restricted` Pod Security Standard and a default-deny NetworkPolicy (this is a MUST here, even though NetworkPolicies are SHOULD elsewhere). |
| **R7.2** | Adds the metrics: sandboxes active, create latency (p50/p95), exec duration, limit hits by type, orphans collected, stale-epoch rejections. |
| **R2.7** | Adds the spans `sandbox.create` and `sandbox.exec` under `tool:{name}`. |

## 5. Tests (§8) and acceptance criteria (§11)

**Unit:** stale-epoch `exec` is rejected; `POST /sandboxes` is idempotent; the GC selects the right orphans; `isolation: sandbox` routes to `sandboxd`; an exceeded limit becomes a tool error.

**Integration (Compose):** a series of escape tests run as `run_python` input. Each must fail safely: connect to Postgres or Redis by service name; read `/proc/1/environ` or any env var for secrets; write outside `/workspace`; fork bomb; allocate 1 GB; `sleep 120`.

- **AC22 · Isolation.** `make demo-sandbox-escape`: every escape test above fails safely, while the worker and other runs keep running. The script prints PASS/FAIL per test.
- **AC23 · One sandbox per run.** Two concurrent sessions each write `/workspace/x` with different content. Each reads back only its own value, and `sandboxd` reports two different containers.
- **AC24 · Crash cleanup.** `SIGKILL` the worker during a `run_python` call. The orphaned sandbox is deleted within 60 s; the reclaimed run gets a sandbox with `epoch + 1`; the old epoch's `exec` returns `409`.
- **AC25 · Cluster.** On kind, sandbox Pods run in `agent-sandboxes` under `restricted` PSS with deny-all networking. `kubectl auth can-i` shows that the worker ServiceAccount can't create pods and that `sandboxd` can only do so in `agent-sandboxes`.

## 6. Impact on the phase plan

| # | Phase | Change |
|---|---|---|
| 4 | Tools & HITL | The registry includes the `isolation` field from the start |
| **7** | **Sandboxes (new, after the chat agent)** | `sandbox-python` image, `sandboxd` with the Docker backend, `run_python`, GC, fencing. AC22–AC24 |
| 8+ | Research agent and later | Renumbered by one |
| K8s | Kubernetes | Kubernetes backend, namespace, RBAC, NetworkPolicy, quota. AC25 |

Estimated additional effort: **~20–25 focused hours** (Docker backend ~10 h, Kubernetes backend + RBAC ~8 h, escape tests and docs ~5 h).

## 7. Out of scope / roadmap

- **Session-scoped sandboxes:** files and Python variables that persist across turns, like a notebook. This needs workspace snapshots in object storage so that sandboxes stay rebuildable.
- **MicroVM isolation** (Firecracker / Kata Containers).
- **Evaluating `kubernetes-sigs/agent-sandbox`** (a Sandbox custom resource for this use case) as a replacement for the hand-written Kubernetes backend, once the hand-written backend has taught us what it abstracts.
- **Running the whole agent loop per container** (option A), if a future threat model needs isolation of *our* code, e.g. user-uploaded graphs.
