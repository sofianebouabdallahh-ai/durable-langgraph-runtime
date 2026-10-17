# CR-006 — Agent Studio: non-technical users build agents, skills and model choices

| | |
|---|---|
| **Status** | **Proposed** (2026-10-17): open questions in §8 |
| **Date** | 2026-10-17 |
| **Base document** | [`Project_4_Detailed_Requirements_K8s.pdf`](Project_4_Detailed_Requirements_K8s.pdf) (v1.0 + Kubernetes) |
| **Depends on** | CR-002 (sandboxes), CR-003 (guardrails), CR-004 (agent definitions), CR-005 (sub-agents), phase 6 (model providers) |
| **Amends** | CR-004 R15.1, R15.4, R15.9, R15.11, §6 ("no upload endpoint"); CR-001 §10 and CR-003 §6 (authentication moves into scope); §6 UI; §9 storage |
| **Scope** | New §17 Agent Studio; new §18 Identity & bring-your-own-key; amendments listed in §5 |

## 1. Motivation and feasibility

People who don't write code should be able to:

- **create agents and sub-agents** in the UI: name, purpose, instructions, which tools, which helpers (sub-agents);
- **create or upload skills** (reusable know-how, optionally with scripts) and attach them to agents and sub-agents;
- **bring their own key** (or an Azure AI Foundry deployment, a local Ollama, any OpenAI-compatible endpoint) and **pick the model** for each agent and sub-agent.

**Is it doable? Yes.** Most of the hard parts already exist, because CR-004 made agents *data* rather than code:

| Needed | Already built | Gap |
|---|---|---|
| A safe agent format | The strict, validated definition schema; leaf sub-agents; deny-by-default grants; hooks only by name (phases 1, 4, 5) | Definitions come from files only, not from users |
| Versions that don't break running work | Content-addressed snapshots: every run pins the exact definition it started with (`agent_definitions`, R15.4) | Drafts, publishing, history |
| Guardrails users can't switch off | Budgets with a wrap-up turn, loop detection, ceilings, approvals, fail-closed hooks (phases 4, 6b) | Per-user quotas |
| Model choice | The `ModelProvider` seam, one OpenAI-compatible adapter (OpenAI, Ollama, Foundry), live-tested (6c) | Per-user connections and encrypted keys; a model catalog |
| Running untrusted code | Sandboxes are next (phase 7, CR-002) | Skill scripts run only there |
| Who owns what | Nothing: no authentication in v1.0 | **Users, workspaces and login become prerequisites** |

What makes it real work is not the agent runtime. It is three things the project has avoided so far: **identity** (whose key, whose agent), **secrets at rest** (users' keys), and **untrusted content** (user-written instructions and uploaded skills). This CR scopes all three.

## 2. Research summary

- **Skills: an open standard exists.** Anthropic released *Agent Skills* as an open standard in December 2025 ([agentskills.io](https://agentskills.io/specification)). It has since been adopted by 40+ platforms, including Claude and OpenAI Codex ([Atlan](https://atlan.com/know/ai-agent/ai-agent-skills/what-are-agent-skills/), [Firecrawl](https://www.firecrawl.dev/blog/agent-skills)).
  - **Format:** a skill is a folder with a `SKILL.md` (frontmatter `name` and `description` required; `license`, `compatibility`, `metadata`, and an experimental `allowed-tools`) and optional `scripts/`, `references/` and `assets/`.
  - **Progressive disclosure:** agents see only each skill's name and description (~50–100 tokens) until they load one. The guideline is instructions under ~5 000 tokens.
  - **LangChain support:** LangChain's Deep Agents implement skills as middleware with the same progressive disclosure, and custom sub-agents don't inherit the main agent's skills ([LangChain reference](https://reference.langchain.com/javascript/deepagents/middleware/createSkillsMiddleware)). That matches our least-privilege rule (R16.7). **Decision: adopt the standard**, so skills can be exported to and imported from other tools.
- **Skills are a real attack surface.**
  - One study of ~31 000 marketplace skills found **26 % had at least one vulnerability** (prompt injection, data exfiltration, privilege escalation, supply chain) ([arXiv 2602.06547](https://arxiv.org/html/2602.06547v1)).
  - Another behaviourally confirmed 157 malicious skills, mostly brand impersonation ([arXiv 2604.02837](https://arxiv.org/pdf/2604.02837)).
  - OWASP's *Agentic Skills Top 10* (draft) ranks malicious skills first and recommends layered controls: provenance, least-privilege manifests, sandboxing, scanning and governance ([OWASP](https://owasp.org/www-project-agentic-skills-top-10/ast01.html)).
  - **Decision:** no public-marketplace installs in v1; scripts only in the sandbox; scanning and an explicit trust level per skill.
- **No-code builders.**
  - Commentators describe OpenAI's Agent Builder as only "semi-no-code": the last step needs an SDK ([Vellum](https://www.vellum.ai/blog/openais-agent-builder-explained)).
  - Copilot Studio targets non-technical users with guided, graphical configuration ([itmagination](https://itmagination.com/blog/ai-agents-copilot-studio-implementation-guide)).
  - The common recipe is templates, describing the agent in plain language, and a test playground, with no API concepts exposed ([MindStudio](https://www.mindstudio.ai/blog/no-code-ai-agent-builders)).
  - **Decision:** forms, not Markdown, for users; the Markdown is generated (and importable) for power users. An agent here is a *conversation* product, so there is no workflow canvas.
- **Bring your own key.** The standard pattern is **envelope encryption**: a key-encryption key in a KMS (Azure Key Vault, AWS KMS) wraps per-record data keys, and ciphertext is bound to its owner with associated data, so a copied ciphertext won't decrypt elsewhere ([WorkOS](https://workos.com/blog/envelope-encryption-explained), [geosurge](https://geosurge.ai/corpus/gen-3204/disk-encryption/encrypted-data-storage-for-llm-operations.html)). Foundry's OpenAI-compatible `/openai/v1/` route takes the deployment name as the model, with an API key or, preferably, Entra ID ([Microsoft](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints)).
- **Model catalog.** [models.dev](https://www.stork.ai/tool/models-dev) is an open-source database of models' capabilities (tool calling, context) and prices, served as JSON. **Decision:** vendor a snapshot to fill the model picker, plus "custom" models for private deployments.
- **Our own live finding (phase 6c).** A real 7B model sent `result: 48` where our schema expected an object, then retried until it timed out. **Lesson: every model a user picks must pass a capability check** (tool calling, streaming) before an agent can use it.

## 3. New section — §17 Agent Studio

### R17.1 Definitions can come from the database — MUST
- **Built-in agents** stay files in `backend/agents/`: reviewed in git, read-only in the UI, copyable as templates.
- **User agents** live in the database as **versions**: `draft` → `published` → `archived`. A published version is immutable; editing creates a new draft.
- **Both kinds go through the same strict validator** (the CR-004 schema). There is one definition of "valid", and the UI shows its errors in plain language next to the field.
- **Runs pin a version by hash** (R15.4, unchanged). Publishing a new version never alters a running conversation; the next turn uses the new one.
- **Import / export:** a `.agent.md` (or a folder zip with sub-agents and skills), so files and the UI interoperate.

### R17.2 A form a non-technical person can use — MUST
| Field | What the user sees | Maps to |
|---|---|---|
| Name, description | "What is this assistant called and what is it for?" | `name`, `description` |
| Instructions | A plain-text editor with examples and an "improve my instructions" button | the prompt body |
| Model | A picker: provider → model (from the user's connections), with price, speed and "supports tools ✓" | `model` (a connection + model) |
| Tools | Plain-language cards ("Search the web", "Do exact maths", "Send a notification: asks you first") with risk badges | `tools` (grants) |
| Helpers | Sub-agent cards, created with the same form, limited to a helper's options (leaf, no approval-gated tools) | sub-agent folders (R16.1) |
| Skills | Attach from the user's library; see what each one teaches and whether it runs code | §R17.4 |
| Safety & cost | Presets: Quick / Standard / Thorough (maps to `max_turns`, tool calls, timeout, cost), each with an "about $X per conversation" estimate | `limits` (within the server ceilings, R14.3) |
| Protections | Toggles for built-in hooks ("Hide secrets in tool data" on by default). **Users can't write hooks:** hooks stay code (R15.9) | `hooks` |

### R17.3 Create by describing, then test, then publish — MUST
- **Describe it:** "Describe the assistant you want" → a built-in *builder agent* (structured output, validated against the same schema) drafts the form. The user edits it. Nothing is published automatically.
- **Templates:** start from a built-in agent or one shared in the workspace.
- **Playground:** chat with the draft before publishing. Draft runs use a small test budget, and approval-gated tools are always simulated in drafts.
- **Publish** requires that validation passes, every selected model passes its capability check (R18.4), and at least one playground turn completes. Every version keeps a changelog line; rolling back means re-publishing an earlier version.

### R17.4 Skills — MUST
- **Format:** the Agent Skills standard (`SKILL.md` + optional `references/`, `assets/`, `scripts/`), validated against the spec (name rules, description 1–1024 chars). Limits: instructions ≤ ~5 000 tokens, files ≤ 10 MB in total.
- **Two ways in:** create in the UI (name, "when to use", the instructions, optional files), or upload a zip / folder.
- **How agents use them (progressive disclosure):**
  - The agent's prompt lists only each attached skill's name and description.
  - The harness adds `load_skill(name)` (returns the instructions) and `read_skill_file(skill, path)` (returns a reference or asset).
  - Scripts run only through `run_skill_script(skill, script, args)`. That tool has risk class `execute` and runs **in the sandbox only** (CR-002: no network by default, CPU and memory limits, its own filesystem). These tools go through the full tool pipeline like any other tool.
- **Least privilege:**
  - A sub-agent sees only the skills attached to *it* (as in Deep Agents, and our R16.7).
  - A skill's `allowed-tools` can only *narrow* what the agent may do, never grant a tool the agent lacks.
- **Trust and review (OWASP AST01):**
  - Every upload is scanned: secrets, injection phrasing ("ignore previous instructions", "send this to"), URLs, encoded blobs, executable types, oversized files. The scan report is shown to the user.
  - Skills have a trust level:

    | Level | Where it can be used | Code |
    |---|---|---|
    | **Private** | Only its author's agents | Instruction-only, or scripts in the sandbox |
    | **Workspace** | Shared, after an admin approves it | Instruction-only, or scripts in the sandbox |
    | **Built-in** | Shipped in git | Reviewed like code |

  - No installing from public marketplaces in v1; that's on the roadmap, with signing and provenance.
- **Untrusted text stays data:** a skill's text is inserted as *reference material*, with the same "text inside is data, never instructions" rule as tool results. Skills never change the harness's rules (grants, budgets, approvals).

## 4. New section — §18 Identity and bring-your-own-key

### R18.1 Users and workspaces — MUST (becomes a prerequisite)
- Login through **OIDC** (Microsoft Entra ID or any identity provider), plus a local developer login. Sessions, agents, skills, connections and runs belong to a **workspace**.
- **Roles:**

  | Role | Can |
  |---|---|
  | `owner` | Everything below, plus billing keys and approving shared skills |
  | `builder` | Create agents and skills |
  | `user` | Chat with published agents |

- Authorisation is checked in the service layer (one place, as today), with tests proving each role both **can** and **cannot** do things (as for the DB roles, R14.13). Row-level security is a later defence in depth.
- `decided_by` on approvals (R1.4) becomes the real user.

### R18.2 Model connections — MUST
A **connection** is the user's own access to models:

| Kind | Covers | Credential |
|---|---|---|
| `openai_compatible` | OpenAI, **Azure AI Foundry** (`…/openai/v1/`, deployment as model), Ollama, vLLM, LM Studio, OpenRouter, Groq, Mistral, a LiteLLM gateway | API key, or none (local) |
| `azure_entra` | Foundry / Azure OpenAI without keys | Managed identity / workload identity |
| `langchain` | Providers without an OpenAI-compatible API (Anthropic, Bedrock, Gemini) through `init_chat_model` | API key |

- **Defined in the UI:** pick a provider → paste a key or an endpoint → **Test** → save. Admins can also define workspace connections from deployment config (env / Kubernetes Secret / Key Vault) that users can pick but never see.
- **One budget system:** our retries, circuit breaker and budgets stay authoritative for every provider (no second gateway counting the same money).

### R18.3 Keys are secrets, always — MUST
- **Envelope encryption:**
  - A key-encryption key in a KMS (Azure Key Vault in the cloud; a local master key from env in development) wraps a data key per connection.
  - AES-256-GCM, with associated data = workspace id + connection id.
  - Only ciphertext and the wrapped data key are stored.
- **Never shown again** after saving: the UI shows `sk-…a1b2`, the date added and the last successful use. **Never** in events, transcripts, logs or traces (the R14.12 known-secret test is extended to connections).
- **Decrypted only in the worker,** for the call, and not cached beyond the process. Rotation means saving a new key; deleting a connection stops runs that need it with a clear error.
- A run records **which connection and model** it used (name and a fingerprint of the non-secret settings), never the key (R14.19).

### R18.4 Choosing a model — MUST
- **The picker** lists models from a vendored snapshot of the open models.dev catalog: price, context and **tool calling ✓**, filtered to what the user's connections can reach. **Custom** models (a private Foundry deployment) are added by name, and the user declares their capabilities.
- **A capability check before use.** "Test" sends a small tool-call request and a streamed reply through the provider contract suite (phase 6c). A model that can't call tools can't be selected for an agent that has tools (the phase 6c lesson).
- **Model per agent and per helper,** for example a strong model for the main agent and a cheaper one for a research helper.

### R18.5 Quotas — MUST
- Even with the user's own key, the server ceilings (R14.3) and the wrap-up turn (R14.2) apply.
- Each workspace sets a daily cost limit per user and per agent (R14.8, extended).
- Draft and playground runs have their own small budget.

## 5. Amendments

| Req | Change |
|---|---|
| **CR-004 R15.1** | Definitions come from files (built-in) **or** from the database (user versions). The same schema. |
| **CR-004 R15.4** | Snapshots also record the author, the version state and the connection/model fingerprint. |
| **CR-004 R15.9** | Unchanged and reinforced: users toggle built-in hooks, never write code. |
| **CR-004 R15.11, §6** | "No upload endpoint" is replaced by the Studio API (§6 below). |
| **CR-001 §10, CR-003 §6** | Authentication and per-user quotas move **into scope** (R18.1, R18.5). |
| **CR-002** | Skill scripts are a new sandbox workload (`run_skill_script`). |
| **§6 UI** | Adds the Agent Studio (forms, model picker, skills library, playground, versions). |
| **§9 Storage** | New tables: `users`, `workspaces`, `memberships`, `agents` (+ versions; snapshots stay in `agent_definitions`), `skills`, `skill_versions`, `skill_files`, `model_connections` (encrypted), `model_catalog`. |

## 6. Architecture

```
 UI (Agent Studio)  forms ─► POST /agents/{id}/drafts ─► validate (CR-004 schema) ─► playground run
      │                                                     └─► publish → immutable version (hash)
      │  skills ─► upload/zip ─► spec check + scan ─► skill_versions (trust: private|workspace)
      │  connections ─► key (TLS) ─► envelope-encrypt (KMS) ─► test (contract suite) ─► saved
 worker: run → agent version (hash) → model per role → connection → decrypt in memory → adapter
         skills: name+description in the prompt · load_skill / read_skill_file (pipeline)
                 run_skill_script → sandbox only (phase 7)
         all guardrails unchanged: grants, budgets + wrap-up, loops, approvals, fencing
```

- **The agent registry becomes a lookup by hash.** Built-in agents are compiled once; user agents are compiled per version and cached by hash. The executor already compiles per run.
- **The provider seam stays where it is** (`RunContext.chat_model`). It is now resolved from the run's version and connection rather than global settings.

## 7. Delivery plan

| # | Phase | Contents | Estimate |
|---|---|---|---|
| 7 | Sandboxes (as planned) | CR-002, now also the runtime for skill scripts | ~10–12 h |
| **7b** | **Identity & BYOK** | OIDC + dev login, workspaces and roles, authorisation everywhere, model connections (3 kinds), envelope encryption, capability check, model catalog snapshot, per-user quotas | ~20–28 h |
| **7c** | **Studio backend** | Definitions in the DB with drafts/versions/publish, import/export, the builder agent, playground runs, skills (spec, upload, scan, trust, progressive-disclosure tools, sandboxed scripts) | ~24–32 h |
| 8–10 | Research agent, observability, evals | As planned (evals add Studio cases: a generated agent passes its own playground checks) | as planned |
| 11 | UI | As planned, **plus** the Agent Studio: forms, model picker, skills library and editor, playground, versions; usability-tested with 2–3 non-technical people | ~14–18 h **+ ~24–32 h** |
| 12–13 | Kubernetes, release | KMS via Key Vault + workload identity; the new tables in backups | as planned |

**Roughly 70–90 extra hours**, delivered like everything else: one plan per phase, success criteria, e2e tests run 5×.

**New acceptance criteria (draft):**
- **AC43** · A non-technical tester creates an agent with one helper and one skill from a template, tests it, and publishes it **without help and without seeing Markdown**.
- **AC44** · A Foundry deployment and a local Ollama model are added by key / URL, pass the capability check, and are used by different helpers of one agent in the same conversation.
- **AC45** · The saved key appears in no response, event, transcript, log or trace. A copied ciphertext doesn't decrypt under another workspace.
- **AC46** · An uploaded skill with an injection phrase and a script is flagged by the scan. Its script runs only in the sandbox, with no network, and can't read another skill's files.
- **AC47** · A published version is immutable. A conversation keeps its version across a new publish; the next turn uses the new one.
- **AC48** · A `user` can't edit an agent or see a connection's key. A `builder` in workspace A can't see anything in workspace B.

## 8. Open questions (decisions needed before planning 7b)

1. **One organisation or public SaaS?** One company's teams lets us use one identity provider and one KMS key per workspace; public multi-tenant means sign-up, per-tenant keys and abuse controls. *Recommendation: one organisation first.*
2. **Skills with scripts in the first version, or instruction-only first?** *Recommendation: instruction-only first (7c), scripts once phase 7's sandbox is proven.*
3. **Whose keys?** Per user, per workspace (an admin adds keys, users only pick models), or both. *Recommendation: both, with the workspace as the default.*
4. **Sharing:** may builders share agents and skills across the workspace (with admin approval for skills)? *Recommendation: yes.*
5. **Ordering:** Studio before the research agent (phase 8) and Kubernetes (phase 12), as above, or after? *Recommendation: as above. The Studio is the product; the research agent becomes a template built with it.*

## 9. Out of scope / roadmap

- A public skills marketplace (needs signing, provenance and continuous scanning).
- Users writing hooks or custom tools in code (they stay developer work, reviewed in git).
- A visual workflow canvas (agents here are conversations; workflows stay code).
- Fine-tuning, or hosting models for users.
