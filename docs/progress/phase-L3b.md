# Phase L3b — Agent Studio: your own model

**Completed:** 2026-10-17 · **Branch:** `feat/l3b-your-own-model` · **Plan:** [plans/phase-L3b.md](../plans/phase-L3b.md) · **Guide:** [Choosing a model](../setup/models.md) · **Tests:** backend 421 · UI unit 51 · browser 4 new scenarios (models)

## What we built

**In Nuria, people now bring their own models.** **Models** in the sidebar lists the connections, with the **default model** at the top. **Add a model** offers four kinds:
- **Ollama:** found on this computer, with the address and the pulled models filled in;
- **OpenAI:** a key and a model;
- **Azure AI Foundry:** an endpoint, a key and a deployment name (`/openai/v1` is added when missing);
- **Other service:** any OpenAI-compatible address.

**Save and test** saves and checks in one step. The check is one tiny request with a `ping` tool, and the model must call it. That proves the address, the key, the model and tool use at once. Failures are explained in plain words: "The key was refused", "This model isn't available there", "This model doesn't use tools", "Couldn't reach…", "Didn't answer in time".

**A model per agent and per helper.**
- The Studio's **Model** section, and each helper's card, have a picker: *Default*, or any model of a connection.
- A model that isn't tested yet is marked; a missing connection is named next to the field.
- **Publishing needs every chosen model to have passed its test.**
- The chat shows which model answered each reply.

**Keys are encrypted on this machine, and never come back out** (R18.3, AC45).
- **Envelope encryption:** each key gets its own AES-256-GCM data key, wrapped by a key-encryption key derived from `NURIA_SECRET_KEY`. Setup generates the master key, also into an existing `.env`.
- **Bound to its place:** the ciphertext is authenticated with `workspace : connection : purpose`, so a copy moved to another row, workspace or purpose won't open.
- **Never returned:** the API only says `has_key`, with an 8-character keyed fingerprint so you can tell keys apart.

**A conversation keeps its model.**
- When a turn is created, every model its agent bundle names is resolved to a connection and model and stored on the run (`runs.model_bindings`), next to the bundle hash from L3a.
- The worker uses those bindings: changing the default, or a worker crash and reclaim, doesn't switch a turn's model.
- Keys are opened in memory in the worker, one adapter per connection version. The circuit breaker is per connection.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | **Add a model without a terminal** | ✅ Browser: Models → Other service → Save and test → *Ready*, set as the default, a chat answered by it. Live: a real Ollama (`qwen2.5:7b`) found by discovery, tested, set as the default, answered a chat |
| SC2 | **AC44: different models in one conversation** | ✅ Integration and browser: a Studio agent on connection A with a helper on connection B; the fake's call log shows `fake-a` and `fake-b` served with different keys in one turn |
| SC3 | **AC45: the key appears nowhere** | ✅ Not in API responses (connections, default, transcript, run, run events, agents), the pages, the database rows (only ciphertext), the logs (caplog in integration; `docker logs` of api, worker and ui in the browser test), nor the doctor report (`NURIA_SECRET_KEY` is `[REDACTED]`) |
| SC4 | **Ciphertext bound to its place** | ✅ Unit: another row, workspace or purpose, tampering, another master key: all fail. Integration: a ciphertext copied to another connection can't be opened |
| SC5 | **The test tells the truth** | ✅ Ready / key refused / model not available / doesn't use tools / couldn't reach, against the fake; OpenAI without a key is refused (422) |
| SC6 | **Pinned models** | ✅ Integration: the default changed while a turn was queued; it ran on its bound model, the next turn on the new default |
| SC7 | **Publish needs tested models** | ✅ Integration: an untested model blocks publishing, named in the blocker; a missing connection is an issue at `model` |
| SC8 | **Keys survive restarts, not leaks** | ✅ A new key replaces the old one (the fingerprint changes; the old key is refused by a locked fake). A worker started after the crash (SC9) opens the key from the database |
| SC9 | **Durability unchanged** | ✅ Browser: the worker running a turn on a user's connection is killed mid-turn, and the default changed meanwhile; the turn finishes on the same connection (one connection in the fake's log), one reclaim, screen = transcript |
| SC10 | Quality | ✅ Backend `make check` (421), UI check, CI green, axe clean on Settings → Models |
| SC11 | Docs | ✅ [Choosing a model](../setup/models.md) (UI first, setup flags as the alternative); design patterns; this summary |

## Bugs found by testing

- **Studio agents' helpers were invisible to real models.** Only the demo model knew them; a real model had a `spawn_subagent` tool and no idea who to spawn. Agents with helpers now get a "## Your helpers" section in their prompt.
- **A working Ollama would have failed its test.** The live check took 31 s: the first call loads the model into memory. Local models now get 120 s, others 30 s.
- **Smaller fixes:**
  - example URLs were pre-filled as values: they are now placeholders;
  - "The model chosen in setup (scripted)" now reads "the offline demo model";
  - a collapsed helper card now shows its model;
  - each connection card shows its id (for agent files: `model: <id>:<model>`).

## Decisions & trade-offs

- **`<connection>:<model>` in definitions.** The schema already accepted `name:model`; it now means a connection. Files and exports stay readable, and a missing connection is an ordinary validation issue.
- **Bind at turn creation, not at each call.** It matches L3a's pin-by-hash: what a turn runs is fixed when it's queued.
- **A fake OpenAI-compatible server in CI,** so routing, the test and crash recovery on a user's connection are proven without a real model or a key. The live proof uses the local Ollama; Foundry and OpenAI live need a key.
- **Locally, any URL is allowed** (Ollama is on the host). The hosted beta needs an egress allow-list (P8).

## Known issues & follow-ups

- **Not run live:** Azure AI Foundry and OpenAI (needs your key; the Foundry route was proven in phase 6c).
- **Losing `.env` loses the master key:** saved keys must then be re-entered (said in the guide). Key Vault replaces the local master key in the beta (P8).
- **Next: L3c,** skills and "describe your agent" (reaches M2).
- **Carried over:**
  - the first `v*` tag;
  - `setup.ps1` on a real Windows machine;
  - an archive button in the Studio.

## How to try it

```bash
./setup.sh                          # then Models → Add a model
make ui-e2e ARGS=tests/models.spec.ts   # needs the test profile: the fake model
```
