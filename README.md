# Nuria

**Agents that finish what they start.**

Nuria lets you chat with AI agents and build your own, on your own machine. It runs on a durable, distributed runtime for [LangGraph](https://github.com/langchain-ai/langgraph) agents. Workers can crash, freeze or be restarted in the middle of a reply, and the reply still finishes: no step is lost, no tool runs twice, and nothing reaches the outside world without your approval.

[![ci](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/sofianebouabdallahh-ai/durable-langgraph-runtime)](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/releases)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> **Status: v0.2.0, the first public release.** It runs on one machine for one person, with no login, using only Docker. A hosted, multi-user version comes after the testers' feedback ([roadmap](docs/roadmap.md)). Testing for us? See the [tester guide](docs/setup/testers.md); feedback is two clicks away in the app.

| Home | A chat waiting for your approval | An agent and its helpers |
|---|---|---|
| ![Home](docs/images/home.png) | ![A chat waiting for approval](docs/images/chat-ui.png) | ![The Nuria agent](docs/images/agent.png) |

**Contents:** [Why](#why-this-exists) · [What the platform gives you](#what-the-platform-gives-you) · [Try it](#try-it-only-docker-needed) · [What you can do](#what-you-can-do) · [How it's built](#how-its-built) · [What it survives](#what-it-survives) · [The core mechanisms](#the-core-mechanisms) · [The agent harness](#the-agent-harness) · [Safety](#safety-by-design) · [How it's tested](#how-its-tested) · [Developers](#developer-quickstart) · [Docs](#documentation)

---

## Why this exists

Most agent frameworks run an agent as one long function call inside one process. That works in a notebook. It breaks when:

- the process crashes halfway through a ten-minute task;
- an agent waits **hours** for a person to approve a step, and the server restarts in the meantime;
- a worker freezes (a GC pause, a VM stall), its job is handed to another worker, and then it wakes up and keeps writing as if it still owned the job: a **"zombie"**;
- a tool that sends an email or charges a card is retried after a crash, and runs **twice**;
- you deploy a new version while agents are mid-reply.

This repository is a runtime that handles all of these. LangGraph defines what an agent does. The runtime decides where it runs, who owns it, how it resumes, and which writes count. **Nuria** is the app built on top of it: a chat, an Agent Studio, tools and dashboards. It exists so people can actually use the runtime, and it gives the runtime real work to prove itself on.

## What the platform gives you

You describe **what** an agent should do. The platform takes care of running it **safely, within limits, and to the end**.

| | What you get | How |
|---|---|---|
| **Durable execution** | A reply survives a crashed, frozen or restarted worker, a restart while it waits for you, and a rolling upgrade | Every step checkpointed in Postgres; leases with fencing tokens; idempotent tool calls ([details](#the-core-mechanisms)) |
| **Bounded execution** | Every agent has a **maximum number of turns** (model calls), plus limits on tool calls (in total and **per tool**), tokens, cost in USD and wall-clock time. Every helper has its own turn limit | Checked in code before every model and tool call. One wrap-up turn at 80%, a hard stop at 100%; loops detected; limits can only be tightened ([details](#budgets-and-limits)) |
| **Tools** | Web search, reading pages and PDFs, Python, a terminal and files, notes, notifications | Built in, nothing to configure; search runs locally (SearXNG) |
| **MCP servers** | Any remote [MCP](https://modelcontextprotocol.io) server's tools, next to the built-in ones | Tested and scanned when added; tokens encrypted; each tool's definition pinned when you publish |
| **Safe execution** | Model-written code can't reach your network, your files or your keys | A fresh sandbox per turn: no network, read-only, non-root, 256 MB, half a CPU, 64 processes, killed at its time limit |
| **Human in the loop** | Anything that reaches the outside world waits for your **Approve**, for as long as you need | Durable pauses that hold no worker; approvals fail closed |
| **Least privilege** | An agent can use only the tools you gave it; helpers can't ask for approval; nothing the model writes can change that | Deny-by-default grants, risk classes, strict argument schemas, one fixed tool pipeline ([details](#the-tool-pipeline)) |
| **Only you drive it** | Only Nuria's own pages reach it: a web page you visit can't, even by rebinding its DNS to your computer. A saved key is only sent where you entered it for | Host allow-list (421), cross-site browser requests refused (Fetch Metadata), keys bound to their address, every outbound address resolved and checked |
| **Prompt-injection resistance** | A web page or tool result saying "ignore your instructions" can't grant a tool or skip an approval, and can't make the agent read an address that would carry your chat out | Untrusted text marked as data, policy enforced outside the model, page addresses nobody gave the agent ask first |
| **Agents without code** | Agents and helpers built in a form, drafted from a sentence, tested, versioned, exported | The Agent Studio; agents are data, and a published version is frozen |
| **Any model** | Ollama, OpenAI, Azure AI Foundry, any OpenAI-compatible service; a different model per agent or helper | Model bindings pinned per turn; retries with backoff; a circuit breaker per connection |
| **Skills** | Reusable know-how, loaded when needed or always used | The Agent Skills format; scanned for hidden instructions and leaked credentials |
| **Full visibility** | Every turn's steps, tools, tokens, cost and errors; who changed what; traces, logs and metrics | Activity, an append-only audit trail, OpenTelemetry + Grafana |
| **Stop buttons** | Stop one reply, turn off one agent everywhere, or stop all agents | A kill switch kept in Postgres, so it holds across restarts |
| **Runs anywhere** | Your laptop (Docker Compose) or Kubernetes, with the same images | Helm charts, autoscaling on the queue backlog, graceful drains |

## Try it (only Docker needed)

```bash
git clone --branch v0.2.0 https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime.git nuria
cd nuria
./setup.sh            # Windows: .\setup.ps1
```

Then open **http://localhost:3000** (setup opens it for you).

**Tested on macOS and Linux. Windows is experimental:** `setup.ps1` hasn't been run on a real Windows machine yet. Running the Linux setup inside WSL is the safer route ([Windows guide](docs/setup/windows.md)). If something breaks, please [open an issue](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/issues) with the output.

What `./setup.sh` does:
1. checks Docker, finds free ports, and generates private passwords for this machine (kept only in `.env`);
2. asks which model to use:
   - **Ollama**, the default: free and private on your machine, downloaded for you if needed;
   - OpenAI, Azure AI Foundry, or any OpenAI-compatible service, with your own key;
   - an offline demo model that needs nothing;
3. downloads the release images (or builds them with `--build`), starts everything in Docker, and runs a real chat turn to prove it works.

First time? **Get started** on Home walks you through choosing a model and building your first agent, with a tool and a helper ([guide](docs/setup/getting-started.md)).

| Command | What it does |
|---|---|
| `./setup.sh --chat` | Chat in the terminal instead of the browser |
| `./setup.sh --observability` | Also start Grafana, Tempo, Loki and Prometheus: traces, logs and metrics for every turn |
| `./setup.sh --kubernetes` | Run the same app on a local Kubernetes cluster (kind + Helm) instead of Compose |
| `./setup.sh --update` | Update to the latest release; backs up your data first |
| `./setup.sh --doctor` | Write a diagnostics file with every password and key removed |
| `./setup.sh --reset` | Delete everything (asks first) |

Guides for each OS, models, tools and troubleshooting: [docs/setup/](docs/setup/).

## What you can do

### Chat with agents
- Replies **stream in** word by word. Tool calls show as cards, and helpers (sub-agents) show their progress live.
- **Anything that reaches the outside world waits for your Approve**, with the tool's exact arguments shown.
- **Stop** ends a reply at once and keeps what was written so far.
- **What happened?** tells each reply's story: which steps ran, which tools, how long each took, what it cost, and, if a worker crashed, which worker took over.
- 👍 / 👎 on replies, and a download of any chat.

### Build your own agents: the Agent Studio
- **A form, not code.** Name, instructions, model, tools, limits. No Markdown, no YAML, no Python ([guide](docs/setup/agents.md)).
- **Helpers (sub-agents).** The main agent hands focused tasks to helpers, each with its own instructions and tools, and they run in parallel.
- **Describe your agent.** Write a sentence ("an agent that plans trips and checks the weather"), and a builder agent drafts the whole thing: instructions, tools and helpers. **Improve** reviews the instructions you wrote.
- **Test, then publish.** Try a draft in a test chat, and give it **tests**: the tools it should use, the approvals it asks for, what its answer says, or a rubric a model grades. With tests, publishing waits until each one passes on that exact draft; a 👎 on a reply can become a test. Publishing freezes a version, so later edits never change the agent people already use. Import and export agents as files.
- **Bring your own model.** Ollama, OpenAI, Azure AI Foundry, or any OpenAI-compatible service. Keys are stored encrypted and never shown again. Each agent, or each helper, can use a different model ([models](docs/setup/models.md)).
- **Skills.** Reusable know-how in the [Agent Skills](https://agentskills.io) format: written in a form, uploaded, or imported. Every skill is checked for hidden instructions and leaked credentials when it's saved. An agent loads a skill when it needs it, or always uses it ([skills](docs/setup/skills.md)).

### Give agents real tools
| Tool | What it does |
|---|---|
| **Search the web** | A private search engine (SearXNG) runs with Nuria: no key, no account. Tavily or Brave if you have a key |
| **Read web pages** | Pages and PDFs as text, so the agent can quote and cite them. Public websites only |
| **Run Python / use a terminal / work with files** | In a **disposable sandbox** per turn: no network, no secrets, read-only, with CPU, memory, process and time limits |
| **Notes** | Things you ask the agent to remember, which it can read back later, in any chat with it |
| **Notifications** | Sending a message to someone, to your webhook. Always asks you first ([notifications](docs/setup/tools.md#notifications)) |
| **Tools from MCP servers** | Anything a [Model Context Protocol](https://modelcontextprotocol.io) server offers: docs search, issue trackers, databases, your own services |

**MCP servers** are added in Settings → Tools, by address, with a token if they need one. Nuria tests the connection and checks each tool's description for hidden instructions. Every MCP tool **asks you first** unless you mark a read-only one "runs without asking". Publishing pins each tool's exact definition, so a server that changes a tool behind your back gets that tool blocked until you review the change ([tools guide](docs/setup/tools.md)).

### See everything
- **Activity:** every turn, across every chat and agent, with its steps, tools, tokens, cost and errors.
- **Who changed what:** an append-only audit trail of every change to agents, skills, models, settings, approvals and the kill switch, with what each looked like before.
- **Traces, logs and metrics** (`--observability`): one id finds every log line of a turn, across the API and the workers, linked to its trace in Grafana ([observability](docs/setup/observability.md)).
- **Kill switch:** **Turn off** stops one agent everywhere; **Stop all agents** stops every agent, until you turn them back on.

---

## How it's built

```mermaid
flowchart LR
    B["Browser<br/>Nuria UI"] -->|"HTTP + SSE"| P["nginx proxy<br/>127.0.0.1:3000"]
    P --> API["API × 2<br/>FastAPI, stateless"]
    API -->|"1 · create run,<br/>read events"| PG[("Postgres<br/>the source of truth")]
    API -->|"2 · enqueue a hint"| RS[["Redis Stream<br/>work queue"]]
    RS -->|"3 · deliver"| W["Workers × 2<br/>LangGraph + harness"]
    W -->|"4 · fenced writes"| PG
    W -->|"5 · publish after commit"| PS(("Redis<br/>Pub/Sub"))
    PS -->|"6 · wake the stream"| API
    W --> M["Model<br/>Ollama · OpenAI · Azure · …"]
    W --> T["Tools<br/>search · pages · MCP servers"]
    W --> SD["sandboxd"] --> SB["Sandbox per turn<br/>no network"]
```

| Part | Role |
|---|---|
| **UI** (React + TypeScript) | The app. Its nginx serves the page and proxies the API, so everything is one origin on `127.0.0.1` |
| **API** (FastAPI, 2 replicas) | Creates runs, handles approvals and cancels, and streams events over SSE. **Stateless:** any replica serves any stream, with no sticky sessions |
| **Workers** (2 processes, 4 runs each by default) | Pull work from the queue and execute LangGraph graphs under a lease |
| **Postgres** | Everything that's kept: runs and their state, events, transcripts, LangGraph checkpoints, the tool ledger, agents, skills, keys (encrypted), the audit trail |
| **Redis** | Transport only: a Stream delivers work to workers, and Pub/Sub wakes the API replica a client is connected to. It holds **nothing that can't be rebuilt** from Postgres |
| **sandboxd** | The only part with the Docker socket (or, on Kubernetes, the right to create pods). Starts a disposable sandbox for each turn that runs code |
| **SearXNG, the page reader** | Web search and page reading, behind an allow-list that refuses private and internal addresses |

### The life of one chat turn

1. **You send a message.** The API stores it and creates a **run** (one turn on the chat's LangGraph thread) in the same transaction. It pins the exact agent version, skills, MCP tool definitions and model this turn will use, then drops a hint on the Redis Stream.
2. **A worker claims it.** It takes a **lease** on the run, which increments the run's **epoch** (its fencing token), and starts the graph with `durability="sync"`: every LangGraph step is checkpointed before the next one starts.
3. **Each step commits as one unit.** The checkpoint, the events it produced and any tool results are written in one Postgres transaction, checked against the epoch. Only after the commit are the events published to Pub/Sub.
4. **You see it live.** Your API replica receives the hint and reads the events from Postgres in order, without gaps or duplicates. It streams them to the browser over SSE. If the connection drops, the browser reconnects with `Last-Event-ID` and continues where it left off.
5. **A tool needs approval.** The run **pauses durably**: it moves to `waiting_approval`, and the worker releases its lease and moves on. Nothing is held in memory. You can approve a minute later or a day later, after a restart, from any replica. The run goes back on the queue, and any worker resumes it from its checkpoint.
6. **The reply completes.** The run ends `completed`, and the transcript is a projection of its events.

Runs follow a table-driven state machine ([`runs/state.py`](backend/src/agent_runtime/runs/state.py)). Waiting states always go back through `queued`, so a resumed run is always claimed again with a fresh lease, never continued in place:

```mermaid
stateDiagram-v2
    direction LR
    [*] --> queued
    queued --> running: lease taken (epoch + 1)
    running --> completed
    running --> waiting_approval: a tool needs you
    running --> waiting_children: fan-out
    running --> queued: lease lost or released
    waiting_approval --> queued: approved
    waiting_children --> queued: children done
    running --> failed: error, timeout, budget, loop
    running --> cancelled: Stop, approval rejected
    completed --> [*]
```

## What it survives

Each row is an automated scenario, run against real processes (`make demo-e2e`) or the real Compose stack (container e2e).

| What happens | What the runtime does | Result |
|---|---|---|
| A worker is **killed** (`SIGKILL`) mid-reply | Its lease expires (30 s by default). The reaper reclaims the message, and another worker resumes from the last checkpoint | The reply completes; no step is lost or repeated |
| A worker **freezes** (`SIGSTOP`) past its lease, then wakes up | Another worker takes over with a higher epoch. Every write the zombie tries carries the old epoch, so Postgres rejects it | The zombie writes nothing and notices it lost the run |
| A worker is **asked to stop** (`SIGTERM`, a deploy, a node drain) | It stops reading new work, finishes its current step, and hands each run back to the queue | Another worker picks the runs up within seconds |
| A worker is killed **during a tool call** | The tool ledger already holds the call's idempotency key. A read-only tool is called again; a tool with a side effect is never sent twice | No duplicate emails or charges. The chat says if a call may have run once |
| A run **waits hours for approval** and everything restarts | The pause lives in Postgres, not in a process | The approval resumes it on whichever worker is free |
| A worker dies **just as a tool asks for approval**, before the pause is saved | Each approval is bound to the interrupt that asked and to a hash of the call's arguments; a run resumes only with decisions that match | It asks you. An earlier approval is never reused |
| An **API replica dies** while you're watching a reply | The browser reconnects through the proxy to another replica with `Last-Event-ID` | The stream continues with no missing or duplicated events |
| **Redis loses a message**, or Pub/Sub is down | An outbox relay re-sends runs whose message was lost, and streams fall back to polling Postgres | Slower, never wrong |
| A **helper's worker crashes**, or a fanned-out child run's | Each child run has its own lease and checkpoint, and recovers on its own | The parent waits for its children and resumes when they finish |
| A **new version is deployed** mid-reply | Migrations are expand/contract, so old and new code run side by side during a rolling upgrade | Runs continue across the upgrade |
| **Postgres restarts** mid-reply (a failover, an upgrade) | A database or queue error is the infrastructure's, not the run's: the run goes back to the queue and resumes from its last checkpoint, up to 5 times | The reply completes. If it never heals, the turn fails with **Try again**, which continues where it stopped |

## The core mechanisms

**Postgres decides, Redis delivers.** A Redis message is only a hint that a run needs attention. The run's lease in Postgres decides who executes it. That makes duplicate messages, lost messages and racing recovery paths harmless: at worst, a worker finds the run already owned and acks the message.

**Leases with fencing tokens.** A worker holds a run through a lease that it renews every 10 s and that expires after 30 s. Every takeover increments the run's `epoch`, and every write (checkpoints, events, transcript, tool results) checks the epoch in the same transaction, under a row lock that conflicts with a takeover. A worker that lost its lease can still *execute* code, but it can no longer *persist* anything. The LangGraph checkpointer is wrapped in a **protection proxy** (`FencedCheckpointer`) that uses only LangGraph's public API, so an upgrade can't silently bypass the guard ([the spike that proved it](docs/design.md#spike-fencing-langgraph-checkpoints-phase-1-task-14)).

**Exactly-once events per committed step (transactional outbox).** The events a step produces are held in memory while the step runs, then committed inside that step's checkpoint transaction. A committed step always has its events. A step lost to a crash has none, and is simply run again. Every run's events carry a gap-free sequence number, which the stream relies on to detect holes and duplicates.

**Idempotent tool calls.** Delivery is at-least-once, so tools must be safe to retry. Every call gets a deterministic key: `sha256(run · node · call index · tool · canonical arguments)`. The key is recorded *before* the tool runs ("record, then act"). A finished call returns its stored result without running again. An interrupted call is either re-sent with the **same** key, so the tool can dedupe its own effect, or, if it has a side effect and asks first, never re-sent.

**Durable pauses.** Approvals use LangGraph's `interrupt()` and `Command(resume=…)`. A waiting run holds no lease, no worker slot and no memory, so a thousand runs can wait for approval at no cost.

**Approvals bound to the call.** Each approval is a row of its own, tied to LangGraph's interrupt id and to the sha256 of the call's real arguments. The run resumes with a map of decisions keyed by interrupt id, built only from rows that match both, so several approvals in one step each get their own decision, and nothing else (a crash, an earlier decision, a call that changed) can pass for one. Edited arguments go through the hooks and the policy again.

**Distributed fan-out vs. in-process helpers.** Two mechanisms, each for one job ([ADR-0005](docs/adr/0005-fan-out-child-runs.md)):
- **Child runs** spread a fan-out across the whole worker pool. Each child is a full run with its own lease and recovery. A fan-in counter, updated in the same transaction as each child's last transition, re-queues the parent exactly once.
- **Helpers (sub-agents)** run as concurrent tasks inside the main run's worker. They share its lease, which gives low latency and live progress.

LangGraph's `Send` runs every branch in one process, so it's used only for local fan-out.

**Live streaming with replay ([ADR-0004](docs/adr/0004-live-events-redis-pubsub.md)).** Each stream subscribes first, then replays from Postgres, drops duplicates, back-fills holes, and polls as a safety net. It's a pure, unit-tested algorithm (`StreamMerger`). Measured latency from commit to client: **p50 17 ms, p95 24 ms** (local, 2 replicas).

**Pinned by hash.** A turn uses exactly what it started with: the agent's definition (content-addressed), its skill versions, its MCP tool definitions and its model bindings, all pinned when the turn is created. Editing an agent, changing the default model or a crash and reclaim can never switch what an in-flight turn uses.

Each component in the code names the design pattern it applies (state machine, repository, unit of work, transactional outbox, protection proxy, competing consumers, bulkhead, circuit breaker, ports & adapters, and others). Each entry says where the pattern lives and why it's there: [docs/design.md](docs/design.md).

## The agent harness

The runtime above makes a run **durable**. The harness makes it **bounded**. An agent's control flow is chosen by a model, its inputs are untrusted (messages, web pages, tool results), and every step costs money. So the harness follows one rule ([CR-003](docs/requirements/CR-003-harness-guardrails.md)): **every guardrail is enforced in code, outside the model.** A prompt may explain a limit to the model, but a prompt never enforces one.

### Where it sits

```mermaid
flowchart LR
    EX["RunExecutor<br/>lease · epoch · checkpoints"] --> G["LangGraph graph<br/>create_agent"]
    G -->|"every model call"| MW["RuntimeMiddleware"]
    G -->|"every tool call"| MW
    MW -->|"charge budget, retry,<br/>pick the pinned model"| M["Model"]
    MW -->|"12 fixed stages"| TP["ToolPipeline"] --> T["Tool"]
    MW -.->|"turn and session hooks"| H["Hooks"]
```

LangGraph and LangChain's `create_agent` provide the agent loop: call the model, run the tools it asks for, repeat. [`RuntimeMiddleware`](backend/src/agent_runtime/tools/middleware.py) is an adapter that takes over both sides of that loop:
- **Model calls** are charged against the run's budget *before* they're made. Each is served by the model pinned for this turn, with retries and a circuit breaker.
- **Tool calls never use LangChain's own tool execution.** Every call goes through the `ToolPipeline`, including calls to tool names the model made up, which are denied and audited.

Everything run-specific (the run, its epoch, its budget, its grants, the agent's skills) reaches the middleware through LangGraph's runtime context. So the same graph code serves every agent, helper and turn.

### The tool pipeline

Every call, to a built-in tool or an MCP tool, runs through the same stages in a fixed order ([`tools/pipeline.py`](backend/src/agent_runtime/tools/pipeline.py)). The first stage that says no wins:

| # | Stage | What it does |
|---|---|---|
| 1 | **resolve** | An unknown tool (a hallucinated or injected name) is refused as `not_granted` |
| 2 | **schema** | Strict JSON Schema validation of the arguments: unknown fields, lengths, ranges. The model gets an error it can correct |
| 3 | **grant** | Deny by default: a tool not granted to this agent or helper is refused |
| 4 | **pre-tool hooks** | Registered code can continue, modify the arguments, deny, or ask you |
| 5 | **re-validate** | If a hook changed the arguments, they're validated again |
| 6 | **policy** | Allow, deny, or **ask you**. Asking pauses the run durably with `interrupt()`. On resume the whole pipeline runs again with your decision |
| 7–8 | **ledger + budget** | The idempotency key is recorded, and the call is charged, once. A finished call returns its stored result |
| 9 | **execute** | With a timeout; code goes to the sandbox |
| 10 | **post-tool hooks** | Can modify the result or withhold it (also for cached results) |
| 11 | **truncate** | At most 16,000 characters go back to the model, with a marker. The full result is stored |
| 12 | **mark as data** | The result is wrapped in delimiters it can't close, as untrusted data |

Every decision (allowed, denied and why, approval asked, budget charged) is an audit event, committed with the step's checkpoint.

**Risk classes set the default policy.** Configuration can make a class stricter, never looser:

| Class | Examples | Default |
|---|---|---|
| `read` | web search, read a page, load a skill | Runs |
| `write_internal` | notes, a helper's result | Runs, idempotent by key |
| `execute` | Python, the terminal, files | Runs, **in the sandbox only**, with a per-tool call cap |
| `external_side_effect` | notifications | **Asks you first**, always |

MCP tools ask first unless you mark a read-only one "runs without asking". The server's own hints never decide alone.

### Hooks: registered code, never inline

Agents are data (Markdown files, or rows from the Studio), and data can't execute code. An agent definition **refers to hooks by name**. The hooks themselves are Python, registered in the runtime ([`tools/hooks.py`](backend/src/agent_runtime/tools/hooks.py)).
- **Nine hook points:** `session_start`, `turn_start`, `pre_model`, `post_model`, `pre_tool`, `post_tool`, `turn_end`, `session_end`, `on_error`. A `post_model` hook can change the reply before you see it (the built-in `redact_secrets_in_reply` masks a key the model writes); `on_error` sees every failed turn.
- **Hooks can only tighten.** They can continue, modify, deny, or ask for approval. They can never grant a tool or skip a check.
- **They fail closed.** A hook that raises an exception or times out counts as a deny, so a broken redaction hook withholds data instead of leaking it.
- **They're deterministic.** On resume LangGraph runs the step again, and the hooks must decide the same way.

### Budgets and limits

**Every turn has a budget:** steps, model calls, tool calls (in total and per tool), tokens, cost in USD, and wall-clock time. The harness checks it before each model call and each tool call. In the Studio, each agent sets its **maximum turns**, its limits on tool calls, tokens, cost and time, and a cap per tool (for example, Python at most 10 times). Each helper has its own maximum turns, and at most 4 helpers run at once.
- **Ceilings are layered, and callers can only tighten them.** Server ceilings ≥ the agent's profile ≥ per-turn options. Every ceiling applies to every run, even an agent that sets no limits of its own. A request above a ceiling gets `422`, with the field and its maximum.
- **Soft limit, then the answer.** At 80% of any budget the agent gets **one wrap-up turn**: no tools, and a note asking for its best answer with what it has. The run then ends `failed`, with the reason (`budget:tool_calls`, `budget:cost`, …) **and that answer**. The wrap-up turn is the one call allowed past a limit, so a burst of parallel tool calls or a helper that used the budget up can't take the answer away. A tool call over budget isn't made: the model is told why.
- **Real prices.** Each turn pins a price per model: the one set in Settings → Models, else `MODEL_PRICES`, else Nuria's dated price list (matched by prefix, so `gpt-4o-mini-2024-07-18` is priced as gpt-4o-mini), else free for a model on your machine. A model with no known price gets a deliberately high estimate, shown as "estimated" in Activity, so a cost budget never silently counts $0.
- **Usage is durable.** Each model call's tokens and cost are written the moment it returns, in a fenced transaction, so a crash and reclaim continues the budget instead of resetting it, and a call made by a step that was then lost to a crash is still counted.
- **It rolls up.** A child run's or a helper's usage counts toward its parent's budget, so an agent can't escape its budget by fanning out. Fan-out is also capped in depth and in number of descendants.
- **Loops are caught.** The same tool with the same arguments: the second repeat is served from the ledger with a note saying so, and the third ends the run as `loop_detected`. A call that failed may be tried again; the third identical failure ends the run.
- **A global daily cost ceiling** can be set to stop new turns once it's reached.

### Long chats

A chat can go on for hundreds of turns ([H5](docs/progress/phase-H5.md)).
- **Each call fits the model's window.** Past 60% of it, old tool results are left out of what the model is sent (it's told it can call the tool again), then the longest older messages are cut to their start and end. The chat and its checkpoint keep everything.
- **Older turns become a summary.** When a chat reaches 60% of the window, a turn starts by folding the older turns into one summary, written by the agent's own model, charged like any call. The last turns and the new message stay word for word. It happens before the turn does anything, so ids and idempotency keys stay consistent.
- **"Too long" is recovered.** A model that says the request is too long gets it shortened and sent again, once.
- **Storage stays flat.** A finished turn keeps only its latest checkpoint, and its helpers' threads go. LangGraph stores the whole message list in every checkpoint, so without pruning a chat grows with the square of its turns. The worker can't delete checkpoints itself: one database function does only this.
- **Each connection has its context window** (Settings → Models). The default is 128,000 tokens, or 8,192 for a model on your machine.

### Models that misbehave

- **Retries only when it helps.** Rate limits, 5xx errors and timeouts are retried at most 3 times, with exponential backoff, full jitter and `Retry-After`. Errors that won't change (a bad request, a wrong key) fail at once. Every attempt counts toward the budget.
- **A circuit breaker per model connection.** One failing service doesn't stall turns that use the others.
- **Small-model repairs.** An empty reply (common when a local model's tool call can't be parsed) is asked for once more, with a note, and charged like any call. The builder agent fixes what a person would fix in a draft (a tool that doesn't exist, a tool that asks first given to a helper), and lists each fix.
- **Local models get more time per turn** (15 minutes), never past the run's own ceiling.

### Helpers (sub-agents)

Helpers run inside the main agent's run, through the same middleware, so the same pipeline, grants and budgets apply.
- **Each helper is charged twice:** to its own turn limit, and to the run's budget.
- **Helpers can't ask you.** A tool that asks first is only ever given to the main agent.
- **A turn guard on the main agent.** If it tries to give its final answer while helpers are still running, it waits for them, then gets one more model call that sees their results.

### Untrusted content

The harness assumes the model **will** follow injected instructions sometimes.
- Tool results, web pages, MCP results and on-demand skills reach the model as data, inside delimiters the text can't close. Look-alike tags are escaped, and every prompt ends with the rule for data.
- **Nothing the model says can change a grant, a budget or a policy, or approve a step.** Approvals come only through the API, from you.
- **The injection test cases assume a fully obedient model.** They check that the pipeline still denies, asks or limits.

### Stopping, and least privilege

- **Kill switch.** Stop one agent everywhere, or every agent, from the app. The state is in Postgres, so it holds across restarts and every replica.
- **Least privilege.** Each component connects to Postgres as its own role, with only the grants it needs. Migrations own the schema. The API can't delete runs, and sandboxd can read only a run's id, status and epoch.
- **The model never holds credentials.** Tools get keys and connections from the harness. Secrets never appear in prompts, tool results, events or transcripts, and a test feeds a known secret through every serializer to prove it.

### Tested without a model

A **scripted model** replays a fixed sequence of replies and tool calls. Every guardrail is tested with it: a runaway agent that never stops calling tools, an agent that repeats itself, an agent that follows injected instructions, a worker killed mid-tool-call. CI needs no key, and no luck.

**Agents have test suites** ([H6](docs/progress/phase-H6.md)). A case is a message and what should happen: tools called or never called, approvals asked, what the answer says or its JSON shape, and an optional rubric graded by the agent's own model. Each case runs as an ordinary turn, so it's durable and costed like one; a worker grades it when it ends. The built-in agents' suites (`backend/agents/<name>/evals/`) run in CI with `runtime eval`, and a harness change that, say, stops asking before `notify` fails them. A Studio agent with tests publishes only when every one passed on exactly that draft.

**Safe across deploys** ([H7](docs/progress/phase-H7.md)). The ledger finds a tool call by its place in the run, not its arguments, so a release that adds a defaulted argument can't make a done call happen again, while workers on the previous release still find every call (expand/contract). A run records the newest format that has had it, and a worker on older code leaves it to a newer one during a rolling upgrade. A side effect cut off by a crash isn't sent again unless its tool dedupes by the key; MCP servers receive the key on every call. The turn after one that stopped mid-tool tells the model what really happened to each call, from the ledger.

## Safety by design

Nuria assumes that **the model can be tricked**, and puts every safety decision in code the model can't talk its way past.

- **Text from tools is data, never instructions.** Tool results, web pages, MCP results and on-demand skills reach the model inside `<data>` delimiters that the text can't close. That's not the defense, though. A test suite of planted "ignore your instructions" cases assumes a *fully obedient* model, and checks that the pipeline still denies, asks or limits.
- **Local only.** Everything listens on `127.0.0.1`. Containers run as non-root on read-only filesystems.
- **Code never runs in Nuria's containers.** It runs in a sandbox with no network, no keys and none of your files, created for one turn and removed after it.
- **No SSRF.** The page reader and MCP client refuse private networks (where that's the rule), Nuria's own services and cloud metadata addresses. They check every redirect, and connect only to the address they checked.
- **Secrets stay secret.** Model keys and MCP tokens use envelope encryption (AES-256-GCM), each bound to its row and purpose. Logs never hold message text, tool arguments or keys: a redaction filter runs at the source, and again in the collector.
- **Nothing leaves without your click**, except your messages to the model you chose. With Ollama or the demo model, nothing leaves at all.

Details, what runs where, and how to delete everything: [docs/security.md](docs/security.md). To report a vulnerability: [SECURITY.md](SECURITY.md).

## Run it on Kubernetes

`./setup.sh --kubernetes` creates a local [kind](https://kind.sigs.k8s.io) cluster and installs two Helm charts. [`nuria-data`](infra/helm/nuria-data/) (Postgres, Redis) is installed first. [`agent-runtime`](infra/helm/agent-runtime/) (the app) follows, with its migrations as a pre-install hook. The setup is built the way it would be in production:

- **Workers scale on the queue's backlog** (KEDA on the consumer group's lag), not on CPU, because workers spend their time waiting on models. The API scales on CPU (HPA).
- **PodDisruptionBudgets and graceful hand-off.** A node drain moves runs to other workers between steps.
- **NetworkPolicies, deny by default.** Sandboxes are pods with no network at all.
- **One image everywhere.** Only the injected configuration differs ([ADR-0002](docs/adr/0002-configuration-and-secrets.md)).

[Kubernetes guide](docs/kubernetes.md).

## How it's tested

| Suite | What it covers | Size |
|---|---|---|
| Backend unit + integration | Against real Postgres and Redis, never mocks of them: the state machine, fencing (including a control test proving an unfenced zombie *does* corrupt a run), the pipeline, the stream merger, migrations | 864 tests |
| Runtime e2e (`make demo-e2e`) | Real worker and API processes, killed, frozen and drained mid-run | 15 scenarios |
| Container e2e | The Compose stack as testers run it: a worker killed mid-reply, mid-sandbox and mid-MCP-call; Postgres restarted mid-reply; a notification delivered to a webhook; least-privilege database logins; foreign hosts and cross-site requests refused | 8 scenarios |
| UI unit | Components and the stream reducer | 78 tests |
| Browser (Playwright) | The whole app in a real browser, against a scripted model | 60 tests |
| Kubernetes e2e | The Helm install on kind, a drain mid-reply | |

The tests use a deterministic **scripted model** and a **fake OpenAI-compatible server**, so CI needs no model and no key. Before a release, the whole flow also runs in a browser against a **real local model** (qwen2.5:7b on Ollama). Each phase's summary records what that run found, and how it was fixed ([L8](docs/progress/phase-L8.md)).

CI runs lint, `mypy --strict`, every suite and an image scan (Trivy). A release builds multi-arch images (amd64, arm64) with an SBOM and provenance.

---

## Developer quickstart

Requirements: [uv](https://docs.astral.sh/uv/), Docker (Desktop or OrbStack), GNU make. Node runs in a container.

```bash
make hooks     # once: pre-commit hooks, including a secret scanner
make up        # creates .env from .env.example, starts Postgres + Redis, migrates
make worker    # 2 worker processes that execute queued runs
make api       # HTTP API on http://127.0.0.1:8000 (docs at /docs); API_PORT=8765 to change
make ui-dev    # the UI with hot reload on http://127.0.0.1:5173
make run-toy   # create and execute one toy run in this process; prints its event log
make demo-e2e  # crash / zombie / release / multi-replica streaming scenarios (real processes)
make check     # lint + mypy --strict + agent validation + all tests
make help      # every target
```

`make down` stops the services and keeps their data; `make nuke` deletes the data too.

### Tech stack

| Layer | Choice |
|---|---|
| Agents | LangGraph 1.x, LangChain `create_agent` with runtime middleware, `langgraph-checkpoint-postgres` behind a fencing proxy |
| Backend | Python 3.12, FastAPI, psycopg 3 (async, pooled), Alembic, Pydantic settings; uv with a dependency cooldown |
| Data | Postgres 16 (pgvector image), Redis 7 (Streams + Pub/Sub) |
| Frontend | React 19, TypeScript, Vite, TanStack Query, Tailwind; types generated from the OpenAPI schema |
| Tools | SearXNG, a hardened page reader, the MCP Python SDK, Docker or Kubernetes sandboxes |
| Observability | OpenTelemetry → Collector → Tempo (traces), Loki (logs), Prometheus (metrics), Grafana |
| Delivery | Docker Compose profiles, kind + Helm + KEDA, GitHub Actions, GHCR, Trivy |

### Repository layout

A monorepo with one folder per deliverable ([ADR-0001](docs/adr/0001-repository-layout.md) explains why).

| Path | What |
|---|---|
| [`backend/src/agent_runtime/`](backend/src/agent_runtime/) | The runtime and the API. `runs/` (state machine, executor, leases, fan-out), `streaming/`, `tools/` (the pipeline), `subagents/`, `sessions/`, `agents/` (Studio, builder), `skills/`, `mcp/`, `models/`, `sandbox/`, `web/`, `api/` |
| [`backend/agents/`](backend/agents/) | Built-in agents as definition files: data, reviewed like code ([ADR-0003](docs/adr/0003-agents-as-definition-files.md)) |
| [`backend/migrations/`](backend/migrations/) | Alembic migrations, expand/contract |
| [`backend/tests/`](backend/tests/) | `unit/`, `integration/`, `contract/`, `e2e/` |
| [`frontend/`](frontend/) | Nuria, the React + TypeScript UI |
| [`sandbox/`](sandbox/) | The sandbox image |
| [`infra/`](infra/) | Docker Compose, the observability stack, kind and the Helm charts |
| [`docs/`](docs/) | Design, ADRs, requirements, plans, phase summaries, setup guides |
| `setup.sh`, `setup.ps1` | The one-command install for macOS, Linux and Windows |
| `Makefile` | The single entry point for development. Run `make` from the root |

### Configuration

All settings come from environment variables, validated at startup by [config.py](backend/src/agent_runtime/config.py). A setting that's invalid stops the process with the field named, instead of failing mid-run.

| Environment | Configuration | Secrets |
|---|---|---|
| Laptop | `.env` (from [.env.example](.env.example)), passed by `make` to `uv` and Compose | same `.env`, git-ignored |
| CI | workflow `env:` | GitHub Environment secrets; OIDC for cloud access |
| Kubernetes | ConfigMap from Helm values | K8s Secret (kind: `make k8s-secrets`; cloud: External Secrets) |

Details and rules: [ADR-0002](docs/adr/0002-configuration-and-secrets.md).

## Documentation

| If you want to… | Read |
|---|---|
| Install and use Nuria | [docs/setup/](docs/setup/): per OS, [models](docs/setup/models.md), [agents](docs/setup/agents.md), [skills](docs/setup/skills.md), [tools](docs/setup/tools.md), [observability](docs/setup/observability.md), [updating](docs/setup/updating.md), [troubleshooting](docs/setup/troubleshooting.md) |
| Understand the design | [docs/design.md](docs/design.md) (every pattern, where and why), [ADRs](docs/adr/) |
| See what was required | The [base spec](docs/requirements/Project_4_Detailed_Requirements_K8s.pdf) and [change requests](docs/requirements/) |
| See how it was built | The [roadmap](docs/roadmap.md), each phase's [plan](docs/plans/) and [summary](docs/progress/) (what was built, the test results, the bugs found, the decisions) |
| Know what changed | [CHANGELOG.md](CHANGELOG.md) |
| Check its security | [docs/security.md](docs/security.md), [SECURITY.md](SECURITY.md) |

## License

[Apache-2.0](LICENSE)
