# macOS

1. **Install Docker Desktop:** https://www.docker.com/products/docker-desktop/. Start it and wait for "Docker Desktop is running". OrbStack works too.
   - Give it at least **4 GB of memory**, or **8 GB if you'll run a local model in Docker** (Settings → Resources).
2. **Get the code and start it:**
   ```bash
   git clone https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime.git
   cd durable-langgraph-runtime
   ./setup.sh
   ```
   `git` isn't installed? macOS offers to install the command-line tools the first time you type `git`. Accept, then run the command again.
3. **A local model (optional):** install the **Ollama app** (https://ollama.com/download). It uses your Mac's GPU. Then:
   ```bash
   ollama pull qwen2.5:7b
   ./setup.sh --model ollama
   ```
   Setup finds it automatically. (Ollama in Docker works too, but on a Mac it runs on the CPU only, several times slower.)

The first start downloads or builds a few hundred MB; later starts take seconds.
