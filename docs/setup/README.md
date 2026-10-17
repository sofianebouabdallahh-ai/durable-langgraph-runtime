# Run it on your machine

Everything runs in Docker on your computer: the database, the queue, the API and two workers. Your conversations, agents and keys stay on this machine. You need **only Docker**; no Python, Node or developer tools.

| Your computer | Guide |
|---|---|
| Mac (Apple Silicon or Intel) | [macos.md](macos.md) |
| Windows 10 / 11 | [windows.md](windows.md) |
| Linux | [linux.md](linux.md) |

Then:
- **Pick a model** ([models.md](models.md)): the offline demo model, a free local model (Ollama), OpenAI, Azure AI Foundry, or any OpenAI-compatible service.
- **If something goes wrong:** [troubleshooting.md](troubleshooting.md).

## The short version

```bash
git clone https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime.git
cd durable-langgraph-runtime
./setup.sh            # Windows (PowerShell): .\setup.ps1
```

The setup script:
1. checks Docker and finds free ports;
2. creates your private `.env`, with passwords generated just for this machine;
3. asks which model to use;
4. starts everything and runs a real chat turn to prove it works.

When it says **Ready**, open the address it prints, or chat right away in the terminal:

```bash
./setup.sh --chat     # type your messages; Ctrl-D to leave
```

| Command | Does |
|---|---|
| `./setup.sh` | Start (again). Safe to run any time: it never overwrites your settings or passwords |
| `./setup.sh --model ollama` | Switch the model (`scripted`, `ollama`, `openai`, `foundry`, `compatible`) |
| `./setup.sh --stop` | Stop everything; your data is kept |
| `./setup.sh --update` | Back up the database, get the latest version, migrate, restart |
| `./setup.sh --doctor` | Make a diagnostics file (passwords and keys removed) to attach to a GitHub issue |
| `./setup.sh --reset` | Delete everything: conversations, agents, downloaded models (asks first) |

**Privacy:**
- Ports are opened on `127.0.0.1` only, so nothing is reachable from your network.
- Your API keys are kept in `.env`, readable only by your user, and are sent only to the model provider you chose.
- Nothing is sent to us.
