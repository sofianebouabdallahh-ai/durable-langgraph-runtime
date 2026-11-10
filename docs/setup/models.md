# Choosing a model

Agents need a model to think with. Add the ones you want in Nuria, under **Models** in the sidebar: a local Ollama, an OpenAI key, an Azure AI Foundry deployment, or any OpenAI-compatible service. Pick a **default**, and in the Studio give each agent and each helper its own model if you like.

Setup still asks for one model to start with (see [Without the app](#without-the-app)); everything below can then be done in the app.

## Add a model

**Models → Add a model**, then choose the kind:

| Kind | You need | Notes |
|---|---|---|
| **Ollama** | Ollama running on this computer, ~6 GB free RAM | Found automatically: the address and your pulled models are filled in. Recommended: `qwen2.5:7b` (calls tools reliably). Smaller models often can't use tools, and the test will say so |
| **OpenAI** | An API key from https://platform.openai.com | E.g. `gpt-4o-mini`, `gpt-4o` |
| **Azure AI Foundry** | A deployed model and its key | See [below](#azure-ai-foundry) |
| **Other service** | Its address (+ key) + a model name | vLLM, LM Studio, OpenRouter, Groq, Mistral, a LiteLLM gateway… anything that speaks the OpenAI API |

**Save and test** saves the connection and checks it in one step. The check sends one tiny request with a tool and expects the model to call it, so it proves the address, the key, the model *and* tool use at once. It answers in plain words:

| You see | Meaning |
|---|---|
| **Ready: it answers and uses tools** | Good to go |
| The key was refused | Wrong or expired key |
| This model isn't available there | A typo in the model name, or (Foundry) a deployment name that doesn't exist |
| This model doesn't use tools | It chats, but agents can't work with it: pick a bigger model |
| Couldn't reach … | Wrong address, or the service isn't running |
| Didn't answer in time | Too slow (30 s for a cloud model; 5 minutes for a local one, whose first call loads it into memory) |

**A local model's first answer is slow.** Ollama loads the model into memory on its first request, and unloads it after 5 idle minutes. So the first answer after a break can take a minute or more on a busy laptop; the next ones are quick. Nuria gives a local model (Ollama, or any model on this machine or your network) 5 minutes per call (`LOCAL_MODEL_TIMEOUT_S`), against 1 minute for a cloud one (`MODEL_TIMEOUT_S`). To keep a model loaded longer, set `OLLAMA_KEEP_ALIVE` (e.g. `1h`) where Ollama runs.

**Make a local model fast enough to use.** Measured on a MacBook (Apple silicon, 16 GB) with `qwen2.5:7b`:

| Where Ollama runs | Speed | A chat turn with tools |
|---|---|---|
| The Ollama app on the Mac (uses the GPU) | about 17 tokens a second | 30 s to 2 min |
| Ollama in Docker (CPU only on a Mac) | about 3 tokens a second | several minutes, often too slow |

- **On a Mac, install the Ollama app** ([ollama.com/download](https://ollama.com/download)), not the Compose `llm` profile: Docker on a Mac can't use the GPU. Setup finds the app on port 11434 and warns when it's a container.
- **Give it a big enough context:** `OLLAMA_CONTEXT_LENGTH=8192` where Ollama runs (the stack's own Ollama sets it). Ollama's default, 4096 tokens, cuts an agent's instructions, tools and history short, without saying so.
- **A turn on a local model gets 15 minutes** (`LOCAL_TURN_TIMEOUT_S`, never above `RUN_TIMEOUT_S`), against the agent's own limit for a cloud one: it reads and writes far slower. Its other budgets (steps, tokens, tool calls) stay the same.

A card per connection then shows its status, its models, and **Test** (try another model), **Edit** and **Remove**.

## The default model, and a model per agent

- **Default model** (top of the Models page): what Nuria and every agent use unless told otherwise. "The model chosen in setup" means the one from `.env`.
- **In the Studio,** an agent's **Model** section and each helper's card have a picker: *Default*, or any model of a connection. A main agent on a big model with a helper on a small, cheap one works fine.
- **Publishing** an agent needs every model it uses to have passed its test. The Studio names the one that hasn't.
- **A conversation keeps its model.** Each message's models are fixed when it's sent, so changing the default, or the agent, doesn't change a reply in progress. The next message uses the new choice.
- Under each reply, the chat shows which model answered.

## Azure AI Foundry

1. In the Foundry portal, deploy a model (e.g. `gpt-4o-mini`) and open your project's **Overview**.
2. Copy the endpoint and a key. Either the resource endpoint (`https://<resource>.openai.azure.com`) or the OpenAI-compatible one (`…/openai/v1/`) works: Nuria adds `/openai/v1` when it's missing.
3. **Models → Add a model → Azure AI Foundry**: paste the endpoint and key, and type your **deployment name** as the model.

## Context window

How much a model takes in one request. Nuria fits every call to it, and summarises a
long chat's older turns once it reaches 60 %, so a chat never gets stuck on "the
conversation is too long".

- **Default:** 128,000 tokens for a hosted model, 8,192 for one on your machine (Ollama's
  usual setting).
- **Set it:** Settings → Models → your connection → **Context window → Set**. Use the
  number your provider or `ollama show <model>` gives. Started Ollama with
  `OLLAMA_CONTEXT_LENGTH=32768`? Enter 32768.
- A turn keeps the window it started with, like its price.

## Your keys

- **Encrypted on this machine.** Each key is encrypted (AES-256-GCM) with its own data key, which is itself encrypted with a master key: `NURIA_SECRET_KEY` in `.env`, generated by setup. A copied database row can't be opened anywhere else, not even in another row.
- **Never shown again, never logged.** After saving, the app only says "A key is saved" with a short fingerprint, so you can tell two keys apart. To change a key, **Edit** and type the new one: it replaces the old one.
- **Keep `.env` safe.** Without its `NURIA_SECRET_KEY`, saved keys can't be opened: you would have to re-enter them. `.env` is git-ignored and readable only by you; don't share it.
- A key is sent only to the address of its own connection.

## Without the app

Setup picks the starting model (shown as "The model chosen in setup"). Change it any time with `./setup.sh --model …`; after a change, setup runs a real chat turn to check it works.

| Choice | Command | Notes |
|---|---|---|
| **Local (Ollama)**, the default | `--model ollama` | Free and private. Uses the Ollama app if it's running (and downloads `qwen2.5:7b` into it, asking first), else Ollama in Docker. `--model-name qwen2.5:3b` for smaller machines |
| **OpenAI** | `--model openai` | Default `gpt-4o-mini`; another: `--model-name gpt-4o` |
| **Azure AI Foundry** | `--model foundry` | `--base-url "https://<resource>.openai.azure.com/openai/v1/" --model-name "<deployment>" --api-key "<key>"` |
| **Other OpenAI-compatible** | `--model compatible` | Base URL (+ key) + model name |
| **Demo model** | `--model scripted` | Scripted answers, offline, nothing to download. For looking around; it doesn't really understand you |

This key is stored in `.env` itself (not encrypted by Nuria); delete its line and run `./setup.sh` again to remove it. Agent files can also name a connection directly: `model: my-foundry:gpt-4o` (`<connection>:<model>`, the connection's id as shown on its card).
