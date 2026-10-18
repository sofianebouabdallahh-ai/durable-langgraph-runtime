# Run Nuria on your machine

Everything runs in Docker on your computer: the app, the database, the queue, two API servers and two workers. Your conversations, agents and keys stay on this machine. You need **only Docker**; no Python, Node or developer tools.

| Your computer | Guide |
|---|---|
| Mac (Apple Silicon or Intel) | [macos.md](macos.md) |
| Windows 10 / 11 | [windows.md](windows.md) |
| Linux | [linux.md](linux.md) |

Then:
- **Pick a model** ([models.md](models.md)): the offline demo model, a free local model (Ollama), OpenAI, Azure AI Foundry, or any OpenAI-compatible service.
- **Watch it work** ([observability.md](observability.md)): traces, metrics and a Grafana dashboard.
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
4. starts everything, runs a real chat turn to prove it works, and opens the app.

When it says **Nuria is ready**, the app is at **http://localhost:3000** (or the address it prints, if 3000 was taken). Write your first message (or pick a suggestion). **Agents**, in the sidebar, is where you build your own: see [Build your own agent](agents.md). You can also chat in the terminal:

```bash
./setup.sh --chat     # type your messages; Ctrl-D to leave
```

The API and its interactive docs are behind the same address: http://localhost:3000/docs.

| Command | Does |
|---|---|
| `./setup.sh` | Start (again). Safe to run any time: it never overwrites your settings or passwords |
| `./setup.sh --model ollama` | Switch the model (`scripted`, `ollama`, `openai`, `foundry`, `compatible`) |
| `./setup.sh --port 3100` | Put the app on another port |
| `./setup.sh --observability` | Also traces, metrics and a dashboard: see [observability.md](observability.md) (`--no-observability`: off) |
| `./setup.sh --kubernetes` | Run it on a local Kubernetes cluster instead: see [kubernetes.md](../kubernetes.md) |
| `./setup.sh --stop` | Stop everything; your data is kept |
| `./setup.sh --update` | Back up the database, get the latest version, migrate, restart |
| `./setup.sh --doctor` | Make a diagnostics file (passwords and keys removed) to attach to a GitHub issue |
| `./setup.sh --reset` | Delete everything: conversations, agents, downloaded models (asks first) |

**Privacy:**
- Ports are opened on `127.0.0.1` only, so nothing is reachable from your network.
- Your API keys are kept in `.env`, readable only by your user, and are sent only to the model provider you chose.
- Nothing is sent to us.
