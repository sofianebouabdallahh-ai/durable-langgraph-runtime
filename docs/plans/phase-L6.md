# Phase L6 plan — Real tools

**Goal:** agents do real work.

| Tool | What it does |
|---|---|
| **Web search** | Searches the web |
| **Read a web page** | Reads a page |
| **Run code** (Python) | Runs code |
| **Shell** (bash) | Runs commands |
| **Files** | Keeps files while they work |
| **Notifications** | Reach people for real |

The demo-era tools leave the Studio's catalogue: the calculator, and search over the sample documents. Notes stay, because they're real.

**Why:** the current tools were built to prove the runtime (budgets, approvals, idempotency, crash recovery), not to be useful:
- **search** reads a few fixture files;
- **notify** only writes to an outbox table;
- **calculator** is arithmetic.

People building agents (L3) expect the tools agents have everywhere else.

**Requirements:**
- CR-002 (accepted, option B): §13 sandboxing, R13.1–R13.8, so code runs in **a per-run sandbox with no network and no secrets**;
- R3.4 (the tool registry), R14.9–R14.15 (grants, risk classes, untrusted data), R9.4 (the security posture text);
- CR-006 R17.2 (tools as plain-language cards).

---

## 1. Research findings

| Topic | Finding | Consequence |
|---|---|---|
| **Search without a key** | [SearXNG](https://docs.openwebui.com/features/web-search/searxng) is a self-hosted metasearch engine that runs in Docker. JSON output must be switched on in `settings.yml`; its rate limiter can be off on a private instance ([Cherry Studio guide](https://docs.cherry-ai.com/docs/en-us/websearch/searxng)) | **Default:** a SearXNG container in the stack, private to the internal network, JSON on, nothing to sign up for. Fits "local first, no key" |
| **Search with a key** | Hosted search APIs for agents: Tavily (a free monthly allowance, extract included), Brave (now credit-based, ~$5 / 1,000 requests with monthly credits), Exa, Linkup ([Parallel](https://parallel.ai/articles/best-free-web-search-api), [Firecrawl](https://www.firecrawl.dev/blog/brave-search-api-alternatives)). Terms change often | **Optional:** Tavily or Brave with a key in **Settings → Tools**, encrypted like model keys (L3b's envelope encryption). One `SearchProvider` port, three adapters |
| **Reading pages safely** | A URL chosen by a model is a server-side request forgery (SSRF) risk: Postgres, Redis, `sandboxd`, cloud metadata (`169.254.169.254`). CR-002 R13.8 wants egress only through a controlled path | A small **fetch service** (`fetcher`), the only service that reaches the internet for tools. It resolves DNS itself and refuses private, loopback, link-local and metadata addresses, re-checking every redirect. Size, time and content-type caps. It returns readable text (HTML → text; PDFs as text), marked as untrusted data (R14.15). Optional allowlist (`TOOLS_WEB_ALLOWLIST`) |
| **Code and shell** | CR-002 option B: a per-run container for tool execution; only one small service (`sandboxd`) holds the Docker socket; secrets never inside | **`sandboxd`** with a narrow API: create, exec, destroy. Each sandbox: non-root, read-only root, `/workspace` and `/tmp` as capped tmpfs, `--network none`, CPU, memory and pids limits, a per-call timeout, no environment secrets. **One sandbox per run**, created on first use, destroyed when the run leaves `running` (R13.2). Image: Python 3.12 with common data libraries plus bash and coreutils (no compilers, no network tools) |
| **On Kubernetes** (L4b) | Pods instead of containers; `runtimeClassName: gvisor` when available (R13.9) | `sandboxd` gets a Kubernetes driver (a Strategy behind the same API): sandbox Pods in their own namespace, deny-all NetworkPolicy, restricted Pod Security |
| **Notifications for real** | Slack, Teams, Discord and most chat tools accept an incoming webhook (one URL); email needs SMTP | `notify` delivers to a **webhook** (the URL saved encrypted, a domain allowlist) or **SMTP email**. It still always asks first, and test chats still simulate (R17.3) |
| **Small local models** | 7B models call simple tools well; long multi-step tool use is shakier | Clear, short tool descriptions; the L3b capability test unchanged; tools' results truncated and marked as data |

## 2. Design

```
 worker ── ToolPipeline (grants, policy, approvals, idempotency, budgets, data marking) ──┐
   │ in_process: notes, files metadata                                                    │
   │ web: web_search ──► SearchProvider ──► searxng (default) | tavily | brave (key)       │
   │      read_webpage ──► fetcher (SSRF guard, caps, text) ──► the internet              │
   │ sandbox: run_python, run_shell, read_file, write_file, list_files                    │
   │      ──► sandboxd (API) ──► one container per run: no network, no secrets, limits    │
   └ notify ──► webhook / SMTP (asks first; simulated in test chats)                      ┘
```

### 2.1 Tools (what the Studio offers)

| Card | Tool(s) | Risk class | Notes |
|---|---|---|---|
| **Search the web** | `web_search(query, k)` | read | Titles, URLs, snippets; cite the URLs |
| **Read web pages** | `read_webpage(url)` | read | Readable text, capped; untrusted data |
| **Run code** | `run_python(code)` | execute (sandbox) | stdout, stderr, files created; 30 s default |
| **Use a terminal** | `run_shell(command)` | execute (sandbox) | bash in the same sandbox; no network |
| **Work with files** | `read_file`, `write_file`, `list_files` | execute (sandbox) | In the run's `/workspace`; gone when the run ends (return what matters) |
| **Notes** | `save_note` | write_internal | Kept |
| **Notifications** | `notify` | external_side_effect | Real delivery; always asks first |

- **Leaving the catalogue:** `calculator` and fixture `search`. They stay registered for the tests, the demo model and existing agents' files, but aren't offered for new agents.
- **Nuria (the built-in chat agent):** gets web search, page reading and code. Its helpers become a web researcher and a data analyst that runs code.
- **The demo model:** gets rules for the new tools, so offline still shows them.

### 2.2 Services and settings
- **New Compose services in profile `app`:**
  - `searxng` (pinned by digest; internal network only);
  - `fetcher` (our image);
  - `sandboxd` (our image, the only one with the Docker socket, internal only).
- **Settings → Tools:**
  - each tool's status (search: SearXNG reachable or the keyed provider tested; sandbox: ready; notifications: a channel set up and tested);
  - the search provider and its key;
  - the notification webhook or SMTP;
  - an optional web allowlist.
- **Setup:** pulls the sandbox image and checks `sandboxd`; `--no-sandbox` turns code tools off on machines that can't run them (the cards then say why).
- **Kubernetes (L4b chart):** `searxng` and `fetcher` Deployments; `sandboxd` with the Kubernetes driver and its own namespace and RBAC. NetworkPolicies: only `fetcher` and `searxng` have internet egress.

## 3. Tasks

| # | Task | Verification |
|---|---|---|
| L6.1 | `SearchProvider` port (searxng, tavily, brave); `web_search`; the SearXNG service with its config | Contract test of each adapter against a fake; SearXNG live locally |
| L6.2 | `fetcher` service + `read_webpage`: SSRF guard, redirects, caps, text extraction | Unit and integration: localhost, private ranges, `169.254.169.254`, the stack's hostnames, a redirect to a private address, DNS rebinding (resolve once, connect to that IP) are all refused; big and slow pages capped |
| L6.3 | `sandboxd` (Docker driver), the sandbox image, `run_python`, `run_shell`, the file tools; lifecycle per run; cleanup of orphans | Escape tests: no network, no secrets in the environment, root read-only, a fork bomb and a memory hog contained, timeouts kill; created lazily, destroyed when the run leaves running; a crash mid-call → reclaim → a fresh sandbox, the call re-run once (idempotency) |
| L6.4 | Real `notify`: webhook and SMTP, encrypted settings, an allowlist; test chats simulate | Integration against a fake webhook and a fake SMTP; approval still required |
| L6.5 | Settings → Tools (status, provider and key, channel), the Studio's cards, Nuria and its helpers updated, demo rules | Vitest; browser |
| L6.6 | Kubernetes: chart objects for the services, the `sandboxd` Kubernetes driver | kind: a code tool runs in a sandbox Pod; NetworkPolicies verified |
| L6.7 | Browser e2e 5× (search → read → code, with fakes in CI and a live run locally); injection cases through web pages; docs (Tools guide, security posture R9.4), summary, PR | 5/5 |

## 4. Success criteria

| # | Criterion | Pass when |
|---|---|---|
| SC1 | **A real research task** | An agent searches the web, reads two pages and answers with citations (live, local; CI with fakes) |
| SC2 | **Code runs, contained** | `run_python` / `run_shell` work; the escape tests pass: no network, no secrets, limits hold, nothing outlives the run |
| SC3 | **No SSRF** | Every internal or private target is refused, including via redirects and DNS tricks |
| SC4 | **Injection through the web** | Planted instructions in a page change nothing the harness enforces (the R14.15 gate, extended to pages) |
| SC5 | **Durable** | A worker killed mid-`run_python`: the turn completes, the code ran to completion once per execution, and the result is recorded once |
| SC6 | **Real notifications, still asked** | A webhook receives the message only after approval; test chats never send |
| SC7 | **Works on a laptop** | The new services fit beside the stack (memory measured); `--no-sandbox` degrades clearly |
| SC8 | Quality | Backend, UI, browser 5×, container e2e, the kind job green |

## 5. Risks

| Risk | Mitigation |
|---|---|
| The Docker socket is root-equivalent | Only `sandboxd` mounts it, with a narrow API (no arbitrary images or mounts), internal network only; on Kubernetes, scoped RBAC instead |
| Search engines rate-limit SearXNG | Results cached briefly; a keyed provider as the fallback; the tool says plainly when search is unavailable |
| Small models misuse a shell | The sandbox makes mistakes harmless; per-call timeouts and budgets; the shell is opt-in per agent |
| Licences | SearXNG is AGPL, but it runs as a separate, unmodified service: we don't link it |

## 6. Decisions to make
1. **Default search:** SearXNG in the stack, no key (recommended), or a keyed service by default.
2. **Code and shell:** run without asking, since they're sandboxed with no network (recommended), or ask first like notifications.
3. **Notifications:** webhook first (recommended: one URL works for Slack, Teams and Discord), then email.
4. **Order:** web tools (L6a: search, pages) first, then the sandbox (L6b: code, shell, files), then real notifications (L6c). Each is shippable on its own.

**Estimate:** about 22–28 h (L6a ~7 h, L6b ~12 h, L6c ~4 h, plus Kubernetes and docs).
