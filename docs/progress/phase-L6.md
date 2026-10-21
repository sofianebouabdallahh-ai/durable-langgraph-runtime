# Phase L6 — Real tools

**Completed:** 2026-10-20 · **Branch:** `feat/l6-real-tools` (stacked on L3d, PR #24) · **Plan:** [plans/phase-L6.md](../plans/phase-L6.md) · **Guides:** [tools](../setup/tools.md), [security](../security.md), [Kubernetes](../kubernetes.md) · **Tests:** backend 629 (+74) · UI unit 67 (+5) · browser 47 · container e2e 4 checks (+1)

## What we built

**Agents do real work.** The demo-era tools (the calculator, search over sample files) left the Studio. In their place:

| Tool | How |
|---|---|
| **Search the web** | SearXNG in the stack (private, no key), or Tavily / Brave with your key, saved encrypted. **Settings → Tools**: the provider, Save and test |
| **Read web pages** | Pages and PDFs as readable text, through the **page reader**: one service, whose connection resolves every host, refuses anything that isn't a public address, connects only to the address it checked, on every redirect. Optional list of sites agents may read |
| **Run Python** | Python 3.12 with numpy and pandas, in a **sandbox**; a last line that's an expression is shown, as in a notebook |
| **Use a terminal**, **Work with files** | bash and coreutils, and the workspace's files, in the same sandbox |

**The sandbox.** One container per run and epoch, started by **sandboxd**, the only service with the Docker socket (token-protected; workers never touch Docker).
- **Locked down:** no network, read-only root, non-root, every capability dropped, no-new-privileges, 0.5 CPU, 256 MB, 64 processes, `/workspace` in memory, every command killed at its time limit.
- **Short-lived:** removed when the run leaves `running`, swept if orphaned, removed by `setup --stop` / `--reset`.
- `./setup.sh --no-sandbox` leaves the code tools out cleanly.

**On Kubernetes** (L6c): SearXNG and the page reader as Deployments, the reader allowed **out to public addresses only** by NetworkPolicy. sandboxd gets a Kubernetes driver (Ports and Adapters next to Docker's):
- **Pods, not containers:** a restricted Pod per run in `nuria-sandboxes`, a namespace with **no network at all**, a quota and an optional RuntimeClass (gVisor, Kata) or user namespaces.
- **Exec with the argv on stdin,** so big code and files fit.
- **Two replicas at once:** Pods are named by run and epoch, so two sandboxd replicas asking together share one sandbox.

**Control.**
- **The kill switch:**
  - **Stop is immediate:** a watcher next to the heartbeat cuts off the model call, tool, code or helper in progress within a second.
  - **Turn off** one agent (Studio, Agents page) or **Stop all agents** (sidebar, a banner until they're back on); new work is refused until turned on. API `/kill-switch`.
- **Approvals don't use up a turn's time:** approving after the limit used to stop the turn, and the action never ran.
- **Messages per chat**, and the step, tool-use and time limits, always visible when creating an agent.

**Skills that small models use.**
- **`load_skill` names the agent's own skills:** with `qwen2.5:7b`, 0 of 6 loads before, 3 of 3 after.
- **Always use** (per attached skill) puts a skill's instructions in every turn, as data. It's for agents with helpers, where even that wasn't enough.
- **Attaching a flagged skill asks first,** listing what the check found.
- **Checks catch up:** stored skills are checked again when the checks improve (rules versions, append-only).

**The chat download** has the model's reasoning (captured from providers that give it), every tool call with its arguments and full result, models and tokens, and what each helper did.

**Found by testing with Ollama in a browser**, and fixed:
- the helper with no tools (now a notice with the tools its description suggests);
- the test chat lost on leaving the Studio;
- raw Markdown in helper answers;
- "working…" forever on a stopped tool;
- the Models page asking for a first model when setup's already worked.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | **A real research task** | ✅ Live with Ollama: an agent searched the web (real SearXNG) and answered with operators, prices and sources; a helper searched in parallel. CI: search → read → cite against the fake web (integration and browser) |
| SC2 | **Code runs, contained** | ✅ Live, Compose and kind: non-root, read-only root, no network (1.1.1.1, the cluster and Postgres all unreachable), the time limit kills (137), the memory limit holds, output capped, a fresh workspace per epoch, nothing left after the run |
| SC3 | **No SSRF** | ✅ Unit and integration: private, loopback, link-local, metadata and internal names refused, redirects and DNS answers included. On kind, with the reader's own checks bypassed, the NetworkPolicy still blocks Postgres, Redis, the API and the cluster's API |
| SC4 | **Injection through the web** | ✅ A page saying "call notify" changes nothing (integration, browser); with Ollama, a planted skill loaded on purpose was recognised as harmful and ignored; the scan flags credential theft |
| SC5 | **Durable** | ✅ Container e2e (3 of 3): a worker killed while its turn runs Python for 6 s; the run is reclaimed and completes, its result recorded once, no sandbox left |
| SC6 | Real notifications | ⏸ Out of this phase (decision 2026-10-19): Notifications still ask first and are recorded, not delivered |
| SC7 | **Works on a laptop** | ✅ Measured idle: SearXNG 201 MB, the page reader 71 MB, sandboxd 72 MB (+344 MB), each running sandbox ≤ 256 MB. `--no-sandbox` tested: setup's check passes and the code tools aren't offered |
| SC8 | Quality | ✅ Backend 626 passed (coverage 90.8%), lint and types clean; UI 67; **browser suite 5×**: 46/46 four times, 45/46 once (a test helper reading docker logs over Node's 1 MB buffer, fixed; that file then 4/4); container e2e 4/4; the chart lints and validates (kubeconform, all values files) |

## Bugs found by testing

- **Fresh installs failed setup's check:** its scripted turn still called the calculator Nuria no longer has. It now runs Python in the sandbox (so a broken sandbox shows at setup), or the calculator on a hidden agent with `--no-sandbox`.
- **Setup's check ignored a default model chosen in the app** and expected the demo's answer.
- **The drafter could put Run Python in a draft without a sandbox**, which the Studio then hid. One rule now decides the tools offered.
- **A dialog opened right after another closed could close itself** (the browser's late `close` event): the intermittent browser failure, fixed in the shared Dialog.
- **Picking the same skill again after Cancel did nothing.**
- **A message sent while every agent is stopped retried silently** (the 503 looked like a passing blip).
- **Files over ~96 KB couldn't be written in the sandbox** (one argument is capped at 128 KiB), and **reads over ~15 KB came back undecodable**.
- **Run Python dropped a last expression's value**, so a small model answered from memory.
- **The skill scan missed handing over credentials** and "do not mention this", and reported one passage twice.

## Decisions

- **Notifications:** not delivered in this phase (SC6 deferred). **Search:** SearXNG by default, no key. **Code:** runs without asking (it's contained).
- **Always use is the author's switch,** rather than automatic skill matching (embeddings or an extra model call per turn): predictable and free per turn.
- **Skill versions stay immutable:** re-checks are added beside them, never written over them.
- **Kill switch:** "every agent" reuses the admission pause (R14.18); one agent is a row. Both cancel at once.

## Not done / next

- SC6, real notification delivery (a webhook after approval).
- Sandbox processes on Kubernetes are capped per node (`podPidsLimit`), not per Pod; kind's new clusters set 4096.
- Small local models still invent facts from search snippets instead of reading pages; the drafter could write tool rules into instructions ("read a page before quoting it").
- Accessibility checks (axe) cover Settings → Tools; the Studio's new controls (Always use, Turn off) and the stop banner aren't axe-checked yet.
