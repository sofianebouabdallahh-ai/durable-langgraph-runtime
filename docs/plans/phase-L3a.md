# Phase L3a plan — Agent Studio: agents & helpers

> **Status: delivered.** Results: [progress/phase-L3a.md](../progress/phase-L3a.md). (The plan's `AgentCatalog` is named `AgentResolver` in the code, to avoid confusion with the tool `Catalog`.)

**Goal:** in Nuria, a person who doesn't code can:
- **create an agent and its helpers** (sub-agents) with a form: name, purpose, instructions, tools, helpers, limits, protections;
- **try it** in a test chat;
- **publish** it as a version;
- then chat with it like any other agent.

They can copy a built-in agent to start from it, see and restore earlier versions, and import or export `.agent.md` files. No Markdown is needed at any point.

**Part of:** the [local release](local-release.md), re-cut into feature slices (each with its backend *and* its screens): **L3a agents & helpers** → L3b your own model → L3c skills & "describe your agent" → milestone **M2**.

**Requirements:**
- CR-006 R17.1 (definitions from the database, versions), R17.2 (the form, without the model and skills rows, which come in L3b and L3c), R17.3 (test, then publish; "describe it" is L3c);
- **AC47** (immutable versions; a conversation keeps its version during a publish, the next turn uses the new one);
- the part of **AC43** that doesn't need skills;
- CR-004 **R15.4** (runs pin their definition by hash);
- G3 (untrusted instructions), in its local form.

---

## 1. Research findings

| Topic | Finding | Consequence |
|---|---|---|
| **Runs don't pin their definition yet** | `agent_definitions` (content-addressed) and `runs.agent_hash` exist since phase 2, and `AgentDefinitionRepository.snapshot()` is tested, **but nothing calls it**. A turn runs whatever definition the worker loaded at startup | L3a finishes R15.4 first: **every turn pins its agent by hash at creation, and the worker builds the agent from that snapshot.** It's the foundation for AC47, and it makes built-in agents safe across rolling upgrades too, R15.4's original intent |
| The agent registry is static | `GraphRegistry` is built once at startup from `backend/agents/`; the executor and the services call `graphs.get(name)` | An **agent catalog** in front of it resolves a name to a definition (built-in from files, user agents from the published version in Postgres) and a hash to a compiled graph, cached by hash |
| Sub-agents aren't in the main agent's hash | `canonical_content` deliberately leaves sub-agents out of the main agent's content | A turn pins a **bundle**: a content-addressed row `{main: hash, helpers: {name: hash}}`. Changing a helper changes the bundle, so the turn's whole team is fixed |
| One validator | `load_agents` parses files, then `_check_common` checks the catalog (tools, hooks), the ceilings and the placeholders. It works on files only | Split it into a **file-independent `validate_definition`** used by the file loader *and* the Studio, so there is one definition of "valid". Issues carry a field path, which the UI shows next to the field in plain words |
| Helpers' safety rules exist | Sub-agents can't use approval-gated tools; they are leaves (no nested helpers) | The form enforces the same rules through the same validator; the UI only offers allowed tools for helpers |
| Test chats and approvals | R17.3: drafts use a small test budget; approval-gated tools are **simulated** | Test-chat turns run with a playground budget; after you approve, the pipeline **records but doesn't execute** an external side effect (`{simulated: true}`), so no notification ever leaves a test chat |
| Display names | Agent names are kebab-case ids (`chat`), and the UI maps `chat` → "Nuria" in code | An optional `display_name` in the definition (`Nuria` for `chat`; "Trip planner" for a user agent whose id is `trip-planner`). The id is fixed at creation, because sessions refer to it |
| Import / export | Agents are folders: `agent.md` + one sub-folder per helper (CR-005) | Export a version as that folder, zipped (or a single `.agent.md` without helpers). Import validates with the same validator. Zip safety: size and file-count limits, no paths outside the folder, only `agent.md` files read |
| A gap left from L2 | A send that fails in a ~1 s proxy race isn't retried, because sends aren't idempotent | An **`Idempotency-Key`** on `POST /sessions/{id}/messages` (unique per session); the UI retries a failed send with the same key |

## 2. Design

```
 Studio UI ──► /studio/agents …          ┌──────────── agent catalog (async) ─────────────┐
   form (draft, autosaved) ─► validate ──┤ resolve(name | draft) → definition → bundle hash│
   test chat (playground) ───────────────┤ spec(hash) → compiled graph (cached by hash)    │
   publish ─► immutable version          │   built-in: backend/agents/ (files, read-only)  │
                                         │   user:     agent_versions (Postgres)           │
 send a message ─► resolve + snapshot ───┘ ─► run.agent_hash (the bundle) ─► worker builds from it
```

### 2.1 Data (migration 0010)
- **`agents`:**
  - `id`;
  - `workspace_id` (`'local'` today, so the beta's tenancy is an expand migration);
  - `name` (the kebab-case id, unique across built-ins and user agents, fixed);
  - `created_at`, `archived_at`.
- **`agent_versions`:**
  - `agent_id`, `number`, `state` (`draft | published | archived`);
  - `document` (the form's content as JSON);
  - `bundle_hash`, `changelog`, `tested_hash` (the draft hash that completed a test turn);
  - `created_at`, `published_at`.
  - **At most one draft per agent** (a partial unique index).
  - **A trigger rejects any change to a published version's content** (AC47 enforced by the database, not just the API).
- **`agent_definitions`** gains the `bundle` kind (`{main, helpers}` by hash).
- **`sessions`** gains `playground_of` (a test chat for an agent's draft; hidden from the chat list).
- **`runs`** gains a unique `(session_id, idempotency_key)`.
- **Grants:** least-privilege grants for the API login (agents and versions) and the worker login (read only).

### 2.2 Backend
- **`validate_definition(document, catalog, ceilings) → AgentDefinition | issues`:** the file loader uses it too. **Pattern: Specification**, one rule set for both sources.
- **`AgentCatalog`** (async), with methods:
  - `resolve(name, draft_of=None)`;
  - `snapshot(definition) → bundle hash`;
  - `spec_for(hash)`;
  - `list()`.

  **Patterns:**
  - **Registry + Repository**, for the two sources behind one interface;
  - **Flyweight / memoised factory**, since graphs are compiled once per hash.
- **Turns pin by hash:**
  - `SessionService.send` resolves the agent (the draft for a test chat) and snapshots it, then creates the run with `agent_hash`;
  - the executor, `turn_end` and `session_end` all build from `run.agent_hash`;
  - plain graphs (toy, fan-out) keep using the static registry.
- **Version lifecycle** (**State** pattern):
  - draft → published → archived;
  - "edit" on a published agent creates a draft from it;
  - "restore" creates a draft from an earlier version;
  - **publish** requires a valid draft and a completed test turn on *this* draft's hash (409 with the reason otherwise).
- **Test chats:**
  - `POST /studio/agents/{id}/playground` gives a session bound to the draft;
  - its turns get the playground budget (`PLAYGROUND_*` settings, within the ceilings) and `simulate_side_effects`;
  - the pipeline stops after approval for `external_side_effect` tools and returns `{simulated: true, would_have: args}`.
- **API (`/studio`, the published OpenAPI contract):**
  - `GET /studio/catalog`: tools in plain words with risk and "allowed for helpers", the protections (built-in hooks as toggles), the limit presets and the ceilings;
  - `GET/POST /studio/agents`: create blank, or as a copy of a built-in or user agent;
  - `GET /studio/agents/{id}`: the draft, the published version, the history;
  - `PUT …/draft`: save and validate; returns issues by field;
  - `POST …/publish`, `…/archive`, `…/versions/{n}/restore`;
  - `GET …/versions/{n}/export`, `POST /studio/import`;
  - `POST …/playground`.
- **`GET /agents`** lists built-in and published user agents (with `display_name`, `source`, `version`). Sessions can be created with any of them.

### 2.3 Studio UI
- **Agents page:**
  - "Your agents" (status: Draft, Published v3, Unpublished changes) above "Built-in";
  - **New agent**;
  - **Copy** on any agent;
  - **Edit** on yours.
- **The editor** (`#/agents/<name>/edit`), a form with a live test chat beside it:
  - **Basics:** name (the id is derived and shown), what it's for.
  - **Instructions:** a large editor with tips and buttons that insert placeholders ("today's date", "its tools").
  - **Tools:** plain-language cards with a toggle, a risk badge ("Asks you first") and an optional per-message cap.
  - **Helpers:** cards; *Add helper* opens the same form, limited to a helper's options (no approval-gated tools, no helpers of its own).
  - **Limits:** presets (Quick / Standard / Thorough), with "Custom" revealing the numbers.
  - **Protections:** toggles for the built-in hooks ("Hide secrets in tool data", on by default; "Summarise the chat when it ends").
  - **Model:** "Uses Nuria's model" (the picker arrives in L3b).
  - **Autosave** (debounced) with "Saved"; every validation issue sits next to its field, in plain words.
  - **Publish** (with an optional "what changed" line) is enabled once the draft is valid and tested. Until then a checklist says what's missing.
  - **History:** versions with their changelog, *Restore*, *Export*. *Import* sits on the Agents page.
- **Patterns:**
  - the form is a pure reducer over the document (**Reducer**);
  - autosave is a **debounced command**;
  - the test chat reuses `ChatView` (**Composition**).

## 3. Tasks

| # | Task | Verification |
|---|---|---|
| L3a.1 | `validate_definition` (file-independent), `display_name`, the loader on top of it | Existing loader tests unchanged; new tests for each rule via documents |
| L3a.2 | Migration 0010 (agents, versions, the immutability trigger, bundles, `playground_of`, idempotency), grants | Migration up/down; trigger test; least-privilege test |
| L3a.3 | `AgentCatalog` + **turns pin by hash**; executor, `turn_end` and `session_end` from the snapshot | Integration: a built-in file changed after a turn is queued → the turn runs the old definition |
| L3a.4 | Studio service and API: drafts, validate, publish (with its preconditions), archive, restore, copy | Integration and API tests; problem+json errors |
| L3a.5 | Test chats: the playground session, its budget, simulated side effects | A notify approved in a test chat writes no outbox row; the budget applies |
| L3a.6 | Import / export (md and zip) with zip safety | Round trip gives an equal canonical definition; malicious zips rejected |
| L3a.7 | Idempotent sends (API + UI retry) | The same key twice gives one turn; the UI retries a 502 without a duplicate |
| L3a.8 | Studio UI: agents page, editor, helpers, presets, protections, autosave and issues, test chat, publish, history, import/export | Vitest for the form reducer and mapping; component tests |
| L3a.9 | Playwright e2e (§4) 5×; a11y on the Studio pages | 5/5; in CI |
| L3a.10 | Docs: "Build your own agent" guide; patterns; summary; PR | |

## 4. Success criteria

| # | Criterion | How | Pass when |
|---|---|---|---|
| SC1 | **Build without code** | Playwright: New agent → name and purpose → instructions → two tools → one helper with its own instructions and tool → Quick preset → test chat → publish → chat with it from Home | Done through the form only (no Markdown on screen); the published agent answers using its helper; **5/5** |
| SC2 | **One validator** | The same invalid inputs through files and the Studio: unknown tool, an approval tool on a helper, over a ceiling, unknown placeholder, empty instructions, a name taken by a built-in | Identical issues from both; the UI shows each next to its field in plain words |
| SC3 | **AC47: immutable versions** | Publish v2 while a turn on v1 is running; then send another turn | The running turn finishes on v1 (its `agent_hash`); the next uses v2; an `UPDATE` of a published version's content is rejected by the database |
| SC4 | **Turns pin by hash (R15.4)** | Queue a turn, change the built-in agent's file (or a user draft), let a worker run it | It runs the snapshot it was created with |
| SC5 | **Test chats are safe** | In a test chat, approve a notification; exceed the test budget | No notification is recorded (simulated); the turn stops at the test budget; test chats don't appear in the chat list |
| SC6 | **Publish needs a test** | Publish an untested or invalid draft; edit after testing | Refused with the reason; editing after a test requires a new test |
| SC7 | **Copy, history, restore** | Copy a built-in; publish v1, v2; restore v1 | The built-in is unchanged and still read-only; restoring v1 creates a draft equal to v1; history shows changelogs |
| SC8 | **Import / export** | Export a version and import it; then malicious zips (zip-slip, too big, too many files, non-Markdown) | Equal canonical definition; every malicious zip rejected, nothing written |
| SC9 | **Durability unchanged** | Kill the worker mid-turn in a chat with a user agent | The turn completes on the same version; no duplicates |
| SC10 | **Idempotent sends** | The same `Idempotency-Key` twice; a send through a forced 502 | One turn; the UI's retry creates no duplicate |
| SC11 | Quality | CI | Backend `make check`, UI check, browser suite 5× (including the Studio flows), axe clean on the Studio pages |
| SC12 | Docs | Follow the "Build your own agent" guide on a clean stack | Works without unwritten steps |

## 5. Risks

| Risk | Mitigation |
|---|---|
| Pinning by hash touches the executor's core path | Done first (L3a.3), behind the existing durability suites (crash, release, approval, sub-agents) and the browser chaos tests |
| A user's instructions try to break the rules (G3) | Instructions never change the harness: grants, budgets, approvals and hooks come from validated fields, not text; length limits; output stays sanitised; tool results remain data |
| The form gets too technical | Plain words, presets, defaults that work; advanced numbers only under "Custom" |
| Old sessions point at agents that change | Each turn pins its own version; a session keeps working across publishes; archiving an agent stops new chats but keeps old ones readable |

## 6. Out of scope (next slices)
- **The model picker and connections:** L3b.
- **Skills, "describe your agent" and "improve my instructions":** L3c.
- **Sharing agents with other people, and roles:** the hosted beta (P7, P9).
