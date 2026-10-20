# What runs where, and how to delete it

Nuria runs entirely on your computer, in Docker.

## What runs

| Part | What it does | Reachable from |
|---|---|---|
| The app (UI) | The page you use, and the way in to the API | `127.0.0.1` only: this computer, not your network |
| 2 API servers, 2 workers | Your chats and agents. The workers run the steps of each reply | Inside Docker only |
| Postgres | Everything that's kept: chats, agents, skills, settings | Inside Docker; `127.0.0.1` for developer tools |
| Redis | The work queue (holds nothing that can't be rebuilt) | Inside Docker; `127.0.0.1` for developer tools |
| *Optional:* Ollama | A local model | `127.0.0.1` |
| *Optional:* Jaeger, Prometheus, Grafana (`--observability`) | Traces, metrics, dashboards | `127.0.0.1` |

The containers run as ordinary users, not root, on a read-only filesystem.

## What leaves your computer

- **Your messages, sent to the model you chose.** With the demo model or Ollama, nothing leaves. With OpenAI, Azure or another service, each turn is sent to that service under your account and its privacy terms.
- **Downloads from GitHub:** Nuria's code and images, when you install or update.
- **Nothing else, and nothing on its own.**
  - Feedback opens GitHub's page only when you click. You see the text first, and submit it there yourself.
  - The usage counts (**Settings → Privacy**, off unless you turn them on) are only ever attached to feedback you send.

## Where your keys are

- **Model keys** you add under **Models** are stored in the database, **encrypted** with `NURIA_SECRET_KEY` from `.env`. They're never shown again and never written to logs.
- **Local passwords** for Postgres and Grafana are generated for this machine at setup, and kept only in `.env`.
- **`.env` holds the secrets.** It's readable only by you, and never part of a backup or a diagnostics file. Keep it safe: anyone with `.env` and a backup can open your saved keys.
- **Diagnostics** (`./setup.sh --doctor`) remove every password and key before writing the file.

## What agents can do

- **Tools that touch the outside world need you.** Anything that sends something somewhere (like *notify*) waits for your **Approve**.
- **Budgets.** Every reply has a limit on steps, tool calls, tokens and cost, and stops at it.
- **Other content is treated as data.** Text that comes back from tools and skills is marked as data, never instructions.
- **Skills with scripts are kept but never run.** There's no sandbox for them yet.

## Delete everything

```bash
./setup.sh --reset        # Windows: .\setup.ps1 -Reset   (asks first)
```

This deletes every chat, agent, skill, setting and downloaded model. Then delete:
- the folder, which holds `.env` and `backups/`;
- the images, if you want the disk space back: `docker image prune -a`.

On Kubernetes (`--kubernetes`), `infra/kind/cluster.sh down` deletes the cluster and everything in it.
