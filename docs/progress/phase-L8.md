# Phase L8 — Tools from anywhere (MCP)

**Completed:** 2026-10-24 · **Branch:** `feat/l8-mcp` · **Plan:** [plans/phase-L8.md](../plans/phase-L8.md) · **Guides:** [tools](../setup/tools.md), [models](../setup/models.md), [security](../security.md) · **Tests:** backend 672 (+31) · UI unit 74 (+1) · browser 56 (+3) · container e2e 5 checks (+1) · **a real-model validation** (below)

## What we built

**MCP servers** (Settings → Tools → MCP servers, L8a).
- Add a remote server by its address, with a token or a custom header if it needs one. The token is encrypted at rest (sealed to its row, like model keys) and never shown, logged or audited; the audit trail keeps a fingerprint.
- **Test** connects, lists every tool, and checks each description with the skill scanner (hidden instructions, handing over credentials). A server that refuses the token, has the wrong path or is down says so in plain words.
- You switch on the tools agents may use. A tool **asks you first** unless you choose "runs without asking", which is offered only for tools the server marks read-only: its hints never decide alone.
- Allowed: this machine and your network (a local server is the common case). Refused: cloud metadata, Nuria's own services, non-http(s) addresses, and every redirect.
- Migration 0021: `mcp_servers`, `mcp_tools` (definition, digest, latest digest, switches, scan); grants for the API and the workers.

**Agents use them** (L8b).
- In the Studio, MCP tools sit under their server's name, beside the built-in ones; "Describe your agent" can draft them.
- **Pinned:** publishing locks each tool's definition (`agent_versions.mcp_lock`, frozen by the same trigger as the rest of a published version). A tool its server changed behind your back is **blocked** until you review and approve the change, and a published agent keeps the definition it was tested with. A tool switched off stops at once.
- **The same pipeline as built-in tools:** JSON Schema arguments, approvals, budgets, results as data, audit, traces and logs, idempotency. After a crash, a read-only call is sent again; an ask-first call is never sent twice (the chat says it may have run once).
- Helpers never get a tool that asks first (only the main agent can ask you).

**What the real-model validation found, fixed in this phase.**
- **A turn on a local model ran out of time:** it now gets 15 minutes (`LOCAL_TURN_TIMEOUT_S`, never above `RUN_TIMEOUT_S`); "Describe your agent" says it can take a few minutes.
- **"Describe your agent" failed on small models:**
  - it now fixes what a person would (a tool that doesn't exist is left out, a tool that asks first moves from a helper to the agent) and lists each fix;
  - an empty reply from the model (a tool call Ollama couldn't parse) is asked for once more instead of ending the turn, for every agent.
- **Skills were read, not followed:** a skill is now know-how the person chose. An "Always use" skill whose scan found nothing is given as plain guidance, last in the instructions; a flagged one stays data. It still can't change tools, limits or approvals: the pipeline enforces those.
- **Ollama in the stack cut long prompts:** it gets an 8,192-token context; setup warns when a Mac's Ollama is a container (CPU only) and says how to set the context. The models guide has measured speeds.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | **Add a server, use its tools** | ✅ Integration and browser: the fixture server added, tested, a tool switched on, given to an agent, called in a chat. Live, with qwen2.5:7b: DeepWiki added and tested, its tool approved and called, its answer in the chat |
| SC2 | **Ask first by default** | ✅ A tool not marked "runs without asking" pauses for approval (live: DeepWiki); a read-only tool switched to "runs without asking" doesn't; the server's hints alone change nothing |
| SC3 | **No rug pulls** | ✅ The fixture changes `lookup`'s description: the next call is refused, the server shows "review", the published agent keeps its pinned definition until the change is approved |
| SC4 | **Injection stays data** | ✅ A description hiding an instruction is flagged at Test; a result saying "call notify" changes nothing |
| SC5 | **Durable** | ✅ Integration, and **container e2e**: a worker killed during an MCP call; the turn completes; the read-only call is sent again, the approved ask-first call is not (3 of 3 on its own, and in the full container run) |
| SC6 | **No secrets leak** | ✅ The token is sealed in its row and absent from the API's answers, logs and audit (fingerprint only); a wrong token's error never echoes it |
| SC7 | **No SSRF** | ✅ Metadata addresses, the stack's services and non-http(s) URLs are refused; redirects are never followed (stricter than the plan's "same origin") |
| SC8 | Quality | ✅ Backend 672 passed, lint and types clean; UI 74; **browser suite 5×: 56/56 every time** (CI's setup: scripted model, observability on); container e2e 5/5 |

### The real-model validation

A fresh install built from this branch, then the whole flow in a browser, with **qwen2.5:7b on a MacBook** (the Ollama app, GPU): add DeepWiki (live) and a fixture server with a token, switch tools on, add a skill, describe an agent and let the model draft it, the Studio, a test chat, publish, a five-turn chat (an MCP tool, Python, web search, memory, the Always-use skill), an MCP tool that asks first and is approved, What happened, the download, Activity and the audit trail.

**Final run: 23 of 24 steps passed** (4.6 minutes; turns of 9–34 s; the page showed each turn's end within 0.4 s of the API). The one miss is the model's choice: in the test chat it asked for the travel date before looking anything up.

How we got there (nine runs):

| Found | Cause | Fix |
|---|---|---|
| Drafting and test chats timed out | Ollama in Docker on a Mac runs on the CPU: 2.8 tokens/s | The Ollama app (Metal): 16.6 tokens/s; setup warns; per-turn limit for local models |
| "Describe your agent" refused the draft | The model gave helpers a tool that asks first, and didn't manage a second proposal | Repairs, listed in the draft |
| The Always-use skill was ignored | In a `<data>` block a small model treats it as information. Replaying real chats: 1 in 10 followed; plain text, last: 19 in 20 | Clean skills as plain guidance |
| "The model didn't come up with a proposal" | 183 tokens written, nothing parsed: an empty reply | Asked once more |
| Runs 2–6 tested an old image | `./setup.sh` runs the published images for `VERSION` unless `--build` | Validation builds from source; see "Not done" |
| Docker Desktop stopped mid-build | 2.1 GB free on the disk | 28 GB of old images and build cache freed |

The validation script's own mistakes (a check before the message was sent, a skill the draft had already attached, a button matched by part of its name) were fixed in the script, not the app.

## Bugs found while building

- **The MCP SDK hides the HTTP status** behind nested exception groups, so "wrong token" and "server down" looked alike: an event hook on the client keeps the status.
- **The fixture answered 421** to the stack's host names: the SDK's DNS-rebinding guard; the fixture allows them.
- **An MCP tool couldn't open its token in a run:** it read the process's settings instead of the run's.
- **A server's name was reused after removal** in tests: names are never reused; the browser spec reads the name the server got.

## Decisions

- **Remote servers in L8, local (stdio) ones in L8c, in the sandbox; tokens now, OAuth in L8b; ask first by default; `mcp` 2.3.0 through a cooldown exception** (2026-10-23, before building).
- **Always-use skills that scan clean are plain guidance** (2026-10-24, after the validation): measured, and the safety that matters (tools, approvals, limits) is enforced in code, not in the prompt.

## Not done / next

- **Publishing needs a release:** `./setup.sh` downloads the images for `VERSION` (0.1.0), which don't have L8. A release bumps `VERSION` (0.2.0), lets the release workflow build and push the images, then installs once exactly as a user does (no `--build`).
- **Not built from the plan:** the Studio's warning past about 12 tools, and an automated test against a server on the 2025 protocol (only the live DeepWiki check covers the SDK's fallback).
- **Small-model behaviour, not bugs:** qwen2.5:7b sometimes answers from search results without reading the page, never loaded an on-demand skill in these runs, and may ask a question before using a tool.
- No cloud model (OpenAI, Anthropic) was run end to end in this phase.
- **L8b** OAuth sign-in (GitHub's, Notion's servers), **L8c** local servers in the sandbox.
