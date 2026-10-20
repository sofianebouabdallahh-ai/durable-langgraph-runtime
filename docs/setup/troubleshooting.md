# Troubleshooting

**First:** `./setup.sh --doctor` writes `diagnostics-<date>.tar.gz`, with versions, service health and recent logs, **with every password and key removed**. Attach it to a GitHub issue.

| Message / symptom | Fix |
|---|---|
| `Docker isn't installed` | Install Docker Desktop (macOS, Windows) or Docker Engine (Linux): see your OS guide |
| `Docker is installed but not running` | Start Docker Desktop and wait until it says it's running; on Linux `sudo systemctl start docker` |
| `port … is used by another program; … will use …` | Nothing to do: setup picked a free port and saved it. The address it prints at the end is the right one |
| `port … is already used by another program` (with `--port`) | Choose another port, or stop the program using it |
| The page says "Connection lost. Reconnecting…" | Usually a second: an API replica restarted and the page moved to another. If it stays, `./setup.sh` (it restarts what stopped) |
| The page says "Can't reach the server" | The stack is stopped: `./setup.sh` |
| The replies look odd ("Demo model") | You're on the offline demo model, which follows simple rules. Connect a real one: `./setup.sh --model ollama` (or `openai`, `foundry`) |
| `the stack didn't become healthy` | Run `./setup.sh --doctor`; often Docker needs more memory (Docker Desktop → Settings → Resources: 4 GB or more) |
| `the smoke test failed: … are the workers running?` | `docker compose -f infra/compose/docker-compose.yml --env-file .env --profile app ps`; then `./setup.sh` again |
| The local model is very slow | On a Mac or Windows, use the native Ollama app (GPU) rather than Ollama in Docker; or a smaller model (`--model-name qwen2.5:3b`) |
| The model never uses tools / answers oddly | Small models are unreliable with tools; try `qwen2.5:7b` or a hosted model |
| `couldn't download the published images; building them here instead` | Fine: it builds locally (a few minutes, once) |
| `NURIA_SECRET_KEY must be a random secret of at least 32 characters` (adding a model) | Your `.env` has a short key. Put a long random one in (`python3 -c 'import secrets;print(secrets.token_hex(24))'`), then `./setup.sh`; re-enter any saved model keys |
| `the backup failed, so nothing was changed` (update) | Nothing was touched. `./setup.sh` to start it, then `./setup.sh --doctor` and send us the file |
| `the update to … didn't pass its check` | It printed two commands: `./setup.sh --update --to v<your old version>`, then `./setup.sh --restore <backup>` ([updating](updating.md)) |
| `this checkout has local changes; an update would mix them in` | `git stash`, then `./setup.sh --update` again |
| Out of memory / services keep restarting | Docker Desktop → Settings → Resources: 6 GB or more (8 with Ollama or `--kubernetes`) |
| I want to start over | `./setup.sh --reset` deletes all data (asks first); delete `.env` too for new passwords |
