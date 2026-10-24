# Phase L8 plan — Tools from anywhere: MCP servers

**Goal:** an agent can use tools from **MCP servers** (the Model Context Protocol, the
standard way tools are shared), added in a few clicks, with the same protections as
Nuria's own tools: approvals, budgets, results treated as data, durable across crashes,
audited, and safe from a server that changes its tools behind your back.

**Why:** today an agent can only use the seven tools built into Nuria. MCP opens thousands
of ready-made tools (GitHub, Notion, databases, docs search, internal services) without
writing code. It was ranked first in L7's list of what agent platforms have that Nuria
doesn't (`phase-L7.md` §7).

**Requirements:** R3.4 (every tool through the pipeline), R14.9 (deny by default), R14.10
(risk classes), R14.11 (strict arguments), R14.15 (tool output is data), R14.17 (audit),
R2.6 (idempotency), R15.4 (pinned bundles); prepares P7 (who may add a server) and P13
(sandboxed local servers).

---

## 1. Research findings (2026-10-23)

**The spec.** MCP's current version is **2026-07-28**, under the Linux Foundation.
([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog))
- **Stateless now:** no `initialize` handshake and no session id. Each request carries its
  version and capabilities; servers implement `server/discover`.
- **Transports:** **Streamable HTTP** for remote servers, **stdio** for local ones. The older
  HTTP+SSE transport is deprecated.
- **Tools:**
  - `inputSchema` and `outputSchema` take any JSON Schema 2020-12 keyword; results can carry
    `structuredContent`.
  - The hints `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint` are
    **untrusted unless the server is trusted**.
  - Tool names are only unique within a server; clients should prefix them.
- **Change notifications:** a client can subscribe to `tools/list_changed`
  (`subscriptions/listen`). List results are cacheable (`ttlMs`).
- **Authorization:**
  - OAuth 2.1 with PKCE and protected-resource discovery (RFC 9728).
  - The `resource` parameter (RFC 8707) and issuer checks (RFC 9207) are required.
  - Clients register with Client ID Metadata Documents; dynamic registration is deprecated.
  - Many servers also accept a plain token in a header; stdio servers take credentials from
    their environment.
- **Deprecated:** sampling, roots and logging. Server-initiated requests became
  multi-round-trip ("input required") results.

**The Python SDK.** `mcp` **2.3.0** (2026-10-02; 2.2.0 2026-09-07; the 1.x line is in
maintenance).
- **v2 is a different API:** a top-level `Client` (URL, stdio parameters, or an in-memory
  server for tests), `mode="auto"` (new stateless protocol, falling back to the old one),
  float-second timeouts, and snake_case fields.
- **Dependencies:** `httpx2` (not our `httpx`), `jsonschema`, `pyjwt`, plus the server-side
  `starlette` and `uvicorn`.
- **Release dates vs our cooldown:** 2.3.0 is after our cutoff (2026-09-27), so it needs a
  per-package exception like certifi's; 2.2.0 fits as-is.
- **`langchain-mcp-adapters` is pinned to `mcp<2`,** and LangChain's replacement
  (`langchain.mcp`) is beta. Both turn MCP tools straight into LangChain tools, which would
  **skip our ToolPipeline**. We use the SDK directly, behind a small adapter of our own.

**Security** ([spec best practices](https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices),
[OWASP MCP Top 10](https://owasp.org/www-project-mcp-top-10/), beta).
- **Tool poisoning:** instructions hidden in a tool's description or schema, which the model
  reads.
- **Rug pulls:** a tool's definition changes after you approved it. **Shadowing:** one
  server's tool impersonates another's.
- **Prompt injection through results.**
- **Token passthrough** (forbidden) and the confused deputy.
- **SSRF:** through the server URL and OAuth metadata discovery.
- **Local servers are code:** run them sandboxed, never on the API host. Pin packages and
  images.
- **No normative pinning:** the spec defines none. Clients hash definitions at approval time
  and block on change.

**What others do.**
- **The common shape:** add a server by URL (and token), see its tools, switch tools on one
  by one, and approve calls (Claude Code, VS Code, Cursor, ChatGPT developer mode, Open WebUI,
  LibreChat).
- **Local stdio servers are optional and sandboxed.** ChatGPT and Open WebUI take remote
  servers only; n8n has no stdio.

**Test fixtures.**
- A small server built with the SDK's `MCPServer`, in-memory for unit tests and as a
  Compose service for end to end.
- `@modelcontextprotocol/server-everything`, for coverage.
- DeepWiki (`https://mcp.deepwiki.com/mcp`, free, no auth) for a live demo.

## 2. Design

### 2.1 Servers and their tools (a connection, like a model's)

Settings → **Tools → MCP servers**, beside Web search:

1. **Add a server:**
   - a name and its address (`https://…/mcp`);
   - optionally a token, sent as `Authorization: Bearer …` or a header you name;
   - saved **encrypted** like model keys (envelope, `NURIA_SECRET_KEY`), never shown again.
2. **Test** lists its tools. Each tool shows its name, description, arguments and the hints
   the server gives. Descriptions and schemas go through the **skill scanner**: hidden
   instructions, credential grabs, "don't tell the user".
3. **Switch tools on, one by one.** Each tool has **Ask first** (the default) or **Runs
   without asking**. "Runs without asking" is offered only for a tool the server marks
   read-only, and it's your choice, not the server's.
4. **Pinning:** what you switched on is saved with a **hash** of its name, description,
   schemas and hints.

**Tables** (migration 0021):
- `mcp_servers`: name, display name, URL, sealed token, header name, status, last tested,
  archived.
- `mcp_tools`: server, tool name, definition (JSON), hash, enabled, ask policy, scan report,
  `seen_at`.

**Audit actions:** `mcp_server.added`, `.changed`, `.removed`; `mcp_tool.enabled`,
`.disabled`, `.approved_change`.

### 2.2 Agents use them (Studio, pipeline, worker)

- **Names:**
  - A tool is `mcp__<server>__<tool>` (prefixed, so two servers can't shadow each other).
  - In the Studio, MCP tools are listed under their server's name, beside the built-in tools.
  - Only switched-on tools can be given to an agent.
- **Publishing pins them:** a published agent's bundle locks each MCP tool's hash, as it
  already locks skill versions.
- **Each call, in the worker:**
  1. The run's MCP tools come from its locked definitions: one `ToolSpec` each, in a
     per-run registry layered over the built-in one.
  2. The arguments are validated against the tool's **JSON Schema**: a second validation
     path next to Pydantic models, same strictness, same errors the model can correct.
  3. The **policy** asks first unless the tool is switched to "runs without asking". The
     risk class is `external_side_effect` by default and `read` only when you said so.
  4. The call is sent **statelessly**: one request with the SDK's `Client`, the token added,
     a timeout (`MCP_TIMEOUT_S`, 60 s) and a result size cap. The definition is checked
     against the server's **current** one first: if it changed, the call is refused
     ("this tool changed on its server: review it") and the server is marked for review.
     **Rug-pull protection.**
  5. The result's text and `structuredContent` become the result; `isError` becomes a tool
     error. Then the usual steps run: secret filter, truncation, and **marked as data**.
- **Crashes:** the call is recorded under its idempotency key before it's sent, as every
  tool call is.
  - A call that finished is replayed from the record, never sent again.
  - A call cut off by a crash is sent again only if you marked the tool "runs without
    asking" (read-only). Otherwise the run asks you again, saying it may have run once
    already.
- **Test chats** don't call tools that ask first: they simulate them, as with notify today.
- **Observability:** spans `tool:mcp__…` with `gen_ai.tool.name` and the server; log lines
  with `mcp_server`; Activity's tools table shows them like any tool.

### 2.3 Where a server may be

- **The URL you add is allowed,** including `localhost` and `host.docker.internal` (an MCP
  server running on your laptop is the common case).
- **Always refused:** cloud metadata (169.254.0.0/16), the stack's own services (Postgres,
  Redis, the API, sandboxd), and non-http(s) schemes.
- **Redirects:** only to the same origin (the SDK's default since 2.2), checked again.
- **The hosted beta (P7+)** will restrict servers to public addresses, through the page
  reader's egress rules.

### 2.4 Not in this phase (decisions below)

- **Local (stdio) servers,** e.g. `npx @modelcontextprotocol/server-github`. They are code
  on your machine, so they'd run in **sandboxd** with network allowed (a new sandbox
  profile). Proposed: **L8c**.
- **OAuth sign-in** (needed by GitHub's, Notion's and similar hosted servers). Proposed:
  **L8b**, with Client ID Metadata Documents, PKCE and tokens stored per issuer, encrypted.
- **Resources and prompts:** tools only, for now. Elicitation ("input required") becomes
  a tool error that says what the server wanted.

## 3. Tasks

| # | Task | Est. |
|---|---|---|
| L8a | `mcp` SDK (cooldown exception), migration 0021, `McpService` (add, test, discover, scan, pin, encrypt), API, Settings → Tools → MCP servers, audit | ~8 h |
| L8b | Agents: names, Studio picker, publish locks, per-run registry, JSON Schema validation, the MCP executor (stateless call, change check, size cap, timeout), policy and crash rules, test-chat simulation, observability | ~10 h |
| L8c | A fixture MCP server (Compose `test` profile), the demo model learns to call an MCP tool, docs (guide: add a server, security), a DeepWiki walkthrough | ~4 h |
| L8e | Tests (below), browser 5×, summary, PR | ~4 h |

**Estimate:** about 25–28 h. OAuth would add about 8–10 h, local stdio servers in the
sandbox about 10–12 h.

## 4. Success criteria

| # | Criterion | How it's checked |
|---|---|---|
| SC1 | **Add a server, use its tools** | Browser: add the fixture server, Test lists its tools, switch one on, give it to an agent, chat: the call and its result appear. Live: DeepWiki answers a question about a repository |
| SC2 | **Ask first by default** | A tool not marked "runs without asking" pauses for approval; a read-only tool you switched to "runs without asking" doesn't; a hint from the server alone changes nothing |
| SC3 | **No rug pulls** | The fixture changes a tool's description: the next call is refused, the server shows "review", and a published agent keeps its pinned definition until you approve and republish |
| SC4 | **Injection stays data** | A description with hidden instructions is flagged at Test; a result saying "call notify" changes nothing (as in L6 SC4) |
| SC5 | **Durable** | Container e2e: a worker killed during an MCP call; the turn finishes; a read-only call is replayed or re-sent once, an ask-first call asks again |
| SC6 | **No secrets leak** | The token is encrypted at rest and absent from logs, traces, the audit trail, the chat download and diagnostics |
| SC7 | **No SSRF** | Metadata addresses, the stack's services and non-http(s) URLs are refused; an off-origin redirect is refused |
| SC8 | Quality | Backend, UI, browser 5×, container e2e, the kind job green |

## 5. Risks

- **The SDK is young (v2: July 2026)** and pulls `httpx2`, `starlette` and `uvicorn`. We
  use only its client, behind one adapter module. If it breaks, the adapter is about 150
  lines of JSON-RPC over HTTP.
- **Servers still on the 2025 protocol:** `mode="auto"` falls back to the session-based one.
  We test against both (`server-everything` speaks both).
- **Small local models and many tools:** `qwen2.5:7b` gets worse as tools grow. The Studio
  shows a tool count and warns past about 12.
- **Annotations lie:** we never trust them for safety. They only decide what we *offer*
  you ("runs without asking" for read-only tools).

## 6. Decisions (2026-10-23)

1. **Remote servers in L8;** local (stdio) servers come in L8c, in the sandbox.
2. **Tokens and headers in L8;** OAuth sign-in in L8b.
3. **Ask first by default:** you may switch a tool the server marks read-only to "runs
   without asking"; the server's hints never decide alone.
4. **`mcp` 2.3.0**, through a per-package cooldown exception.
