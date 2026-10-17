# Choosing a model

Agents need a model to think with. Choose one when setup asks, or change it any time with `./setup.sh --model …`. In the next version this moves into the app (Settings → Models).

| Choice | Command | You need | Notes |
|---|---|---|---|
| **Demo model** | `--model scripted` | Nothing | Scripted answers, offline. Good for trying the app; it doesn't really understand you |
| **Local (Ollama)** | `--model ollama` | ~6 GB free RAM | Free and private. Recommended: `qwen2.5:7b` (calls tools reliably). Smaller machines: `--model-name qwen2.5:3b` (less reliable with tools) |
| **OpenAI** | `--model openai` | An API key from https://platform.openai.com | Default model `gpt-4o-mini`; another: `--model-name gpt-4o` |
| **Azure AI Foundry** | `--model foundry` | A deployed model in Foundry | See below |
| **Other OpenAI-compatible** | `--model compatible` | Base URL (+ key) + model name | vLLM, LM Studio, OpenRouter, Groq, Mistral, a LiteLLM gateway… |

## Azure AI Foundry

1. In the Foundry portal, deploy a model (e.g. `gpt-4o-mini`) and open your project's **Overview**.
2. Copy the endpoint and a key. Use the **OpenAI-compatible v1** endpoint, which looks like `https://<resource>.openai.azure.com/openai/v1/`. The exact host can differ by resource type, so use what the portal shows.
3. Run:
   ```bash
   ./setup.sh --model foundry
   # or without questions:
   ./setup.sh --non-interactive --model foundry \
     --base-url "https://<resource>.openai.azure.com/openai/v1/" \
     --model-name "<your deployment name>" --api-key "<key>"
   ```
   The deployment name is used as the model.

## Your key

- **Where it's stored:** setup writes your key into `.env` (readable only by your user). It's never printed, and it's sent only to the provider you chose.
- **Keep it out of git:** `.env` is git-ignored; don't share it.
- **To remove the key,** delete its line from `.env` and run `./setup.sh` again.

After any change, setup runs a real chat turn on the new model to check it works.
