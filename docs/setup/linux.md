# Linux

1. **Install Docker Engine and the Compose plugin:** https://docs.docker.com/engine/install/. Add yourself to the `docker` group (`sudo usermod -aG docker $USER`, then log out and in), or run setup with `sudo`.
2. **Get the code and start it:**
   ```bash
   git clone https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime.git
   cd durable-langgraph-runtime
   ./setup.sh
   ```
3. **A local model (optional):** either install Ollama on the host (https://ollama.com/download/linux), or let setup run it in Docker:
   ```bash
   ./setup.sh --model ollama     # uses a host Ollama if one is running, else starts one in Docker
   ```
   With an NVIDIA GPU, install the NVIDIA Container Toolkit so the Docker Ollama can use it.

This is the path tested on every change (CI runs `./setup.sh` on a fresh Ubuntu machine).
