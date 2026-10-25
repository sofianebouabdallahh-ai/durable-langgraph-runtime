# Windows 10 / 11

> **Status:** `setup.ps1` mirrors `setup.sh` step for step and is checked in CI (it parses and passes PSScriptAnalyzer), but it **hasn't been run on a real Windows machine yet**. If anything goes wrong, please open an issue with the output, and try the WSL route below: it runs the Linux setup, which is tested.

1. **Install Docker Desktop with the WSL 2 backend:** https://www.docker.com/products/docker-desktop/. Start it.
2. **Install Git:** https://git-scm.com/download/win.
3. **In PowerShell:**
   ```powershell
   git clone --branch v0.2.0 https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime.git nuria
   cd nuria
   .\setup.ps1
   ```
   If PowerShell refuses to run scripts: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then run it again.
4. **A local model (optional):** install **Ollama for Windows** (https://ollama.com/download), which uses your GPU. Then `ollama pull qwen2.5:7b` and `.\setup.ps1 -Model ollama`.

**Alternative: inside WSL** (the Linux setup, which is tested; WSL itself hasn't been tried yet). Open your Ubuntu (WSL) terminal and follow [linux.md](linux.md). Docker Desktop is shared with WSL automatically.
