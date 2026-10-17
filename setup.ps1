<#
.SYNOPSIS
  Run Nuria on this Windows machine. Only Docker Desktop (WSL 2) is needed.

.DESCRIPTION
  The Windows twin of setup.sh: checks, .env with generated secrets, the model,
  start, smoke test, then opens the app (http://localhost:3000). Safe to run again: it never overwrites a secret or a setting
  you didn't ask to change.

  NOTE: written to mirror setup.sh step for step, but not yet run on a Windows
  machine (phase L1). Please report anything that doesn't work.

.EXAMPLE
  .\setup.ps1
  .\setup.ps1 -Model ollama
  .\setup.ps1 -Port 3100
  .\setup.ps1 -NonInteractive -Model scripted
  .\setup.ps1 -Chat | -Stop | -Update | -Doctor | -Reset
#>
[CmdletBinding()]
param(
  [ValidateSet("", "scripted", "ollama", "openai", "foundry", "compatible")][string]$Model = "",
  [string]$ApiKey = $env:SETUP_API_KEY,
  [string]$BaseUrl = "",
  [string]$ModelName = "",
  [int]$Port = 0,
  [switch]$NoBrowser,
  [switch]$NonInteractive,
  [switch]$Build,
  [switch]$Chat, [switch]$Stop, [switch]$Update, [switch]$Doctor, [switch]$Reset
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$ComposeFile = "infra/compose/docker-compose.yml"
$EnvFile = ".env"
$OllamaDefaultModel = "qwen2.5:7b"
$Interactive = -not $NonInteractive -and [Environment]::UserInteractive

function Say($m)  { Write-Host "==> $m" -ForegroundColor White }
function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Die($m, [string[]]$fix = @()) {
  Write-Host "  [x]  $m" -ForegroundColor Red; foreach ($f in $fix) { Write-Host "       $f" }; exit 1
}

# ------------------------------------------------------------------ .env helpers
function Get-EnvValue($key) {
  if (-not (Test-Path $EnvFile)) { return "" }
  $line = Get-Content $EnvFile | Where-Object { $_ -match "^$([regex]::Escape($key))=" } | Select-Object -Last 1
  if ($line) { return $line.Substring($key.Length + 1) } else { return "" }
}
function Set-EnvValue($key, $value) {
  $lines = @(Get-Content $EnvFile); $found = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^$([regex]::Escape($key))=") { $lines[$i] = "$key=$value"; $found = $true }
  }
  if (-not $found) { $lines += "$key=$value" }
  [IO.File]::WriteAllLines((Resolve-Path $EnvFile), $lines)
}
function New-Secret { -join ((1..24) | ForEach-Object { "{0:x2}" -f (Get-Random -Maximum 256) }) }
function Protect-EnvFile {  # readable by this user only
  $acl = Get-Acl $EnvFile; $acl.SetAccessRuleProtection($true, $false)
  $rule = New-Object Security.AccessControl.FileSystemAccessRule($env:USERNAME, "FullControl", "Allow")
  $acl.SetAccessRule($rule); Set-Acl $EnvFile $acl
}

# ------------------------------------------------------------------ docker
function Test-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die "Docker isn't installed." @("Install Docker Desktop (WSL 2 backend): https://www.docker.com/products/docker-desktop/")
  }
  docker info *> $null; if ($LASTEXITCODE -ne 0) { Die "Docker is installed but not running." @("Start Docker Desktop, then run .\setup.ps1 again.") }
  docker compose version *> $null; if ($LASTEXITCODE -ne 0) { Die "Docker Compose v2 is missing." @("Update Docker Desktop.") }
  Ok "Docker $(docker version --format '{{.Server.Version}}') with Compose $(docker compose version --short)"
}
function Get-ProfileArgs {
  $p = Get-EnvValue "COMPOSE_PROFILES"; if (-not $p) { $p = "app" }
  $args = @(); foreach ($x in $p.Split(",")) { $args += "--profile"; $args += $x }; return $args
}
function Invoke-Compose { param([Parameter(ValueFromRemainingArguments)]$rest)
  & docker compose --file $ComposeFile --env-file $EnvFile @(Get-ProfileArgs) @rest
  if ($LASTEXITCODE -ne 0) { throw "docker compose $rest failed" }
}
function Test-PortInUse($port) {
  try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $port); $c.Close(); return $true } catch { return $false }
}
function Test-OurPort($service, $cport, $port) {
  $mapped = & docker compose --file $ComposeFile --env-file $EnvFile @(Get-ProfileArgs) port $service $cport 2>$null
  return ($mapped -match ":$port$")
}
function Select-Port($service, $cport, $key, $default, $wanted) {
  $current = Get-EnvValue $key
  $p = if ($wanted) { $wanted } elseif ($current) { [int]$current } else { $default }
  if ((Test-PortInUse $p) -and -not (Test-OurPort $service $cport $p)) {
    if ($wanted) { Die "port $p is already used by another program." @("Choose another one.") }
    $found = $null
    foreach ($c in @($default, ($default + 1), ($default + 2), ($default + 10000), ($default + 20000))) {
      if (-not (Test-PortInUse $c) -or (Test-OurPort $service $cport $c)) { $found = $c; break }
    }
    if (-not $found) { Die "no free port found for $service." @("Free one, or set $key in .env.") }
    Warn "port $p is used by another program; $service will use $found"; $p = $found
  }
  Set-EnvValue $key $p; return $p
}

# ------------------------------------------------------------------ steps
$script:FirstRun = $false
function Initialize-EnvFile {
  if (-not (Test-Path $EnvFile)) { Copy-Item .env.example $EnvFile; $script:FirstRun = $true; Ok "created .env from .env.example" }
  $changed = 0
  foreach ($line in Get-Content $EnvFile) {
    if ($line -match "^([A-Z0-9_]+)=change-me") { Set-EnvValue $Matches[1] (New-Secret); $changed++ }
  }
  if ($changed -gt 0) { Ok "generated $changed local secret(s) (only on this machine, in .env)" }
  if (-not (Get-EnvValue "COMPOSE_PROFILES")) { Set-EnvValue "COMPOSE_PROFILES" "app" }
  try { Protect-EnvFile } catch { Warn "couldn't restrict .env permissions: $_" }
}
function Select-Ports {
  $script:UiPortChosen = Select-Port "ui" 8080 "UI_PORT" 3000 $Port
  $pg = Select-Port "postgres" 5432 "POSTGRES_PORT" 5432 0
  $redis = Select-Port "redis" 6379 "REDIS_PORT" 6379 0
  Set-EnvValue "REDIS_URL" "redis://localhost:$redis/0"
  Ok "ports: app $script:UiPortChosen, Postgres $pg, Redis $redis (all on 127.0.0.1 only)"
}
function Read-Answer($q, $default = "") {
  if (-not $Interactive) { return $default }
  $a = Read-Host "  $q$(if ($default) { " [$default]" })"; if ($a) { return $a } else { return $default }
}
function Read-Secret($q) {
  if ($ApiKey -or -not $Interactive) { return $ApiKey }
  $s = Read-Host "  $q" -AsSecureString
  return [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}
function Set-Model {
  $m = $Model
  if (-not $m) {
    if (-not $script:FirstRun -and (Get-EnvValue "MODEL_PROVIDER")) { Ok "model: $(Get-EnvValue 'MODEL_PROVIDER') (unchanged; -Model ... to change)"; return }
    if (-not $Interactive) { $m = "scripted" } else {
      Say "Which model should the agents use?"
      "    1) Demo model: offline, scripted answers (try everything with no key)",
      "    2) Local model with Ollama (free; needs ~6 GB RAM)",
      "    3) OpenAI (your API key)",
      "    4) Azure AI Foundry (your endpoint, key and deployment)",
      "    5) Another OpenAI-compatible service (base URL + key + model)" | ForEach-Object { Write-Host $_ }
      $m = @{ "2" = "ollama"; "3" = "openai"; "4" = "foundry"; "5" = "compatible" }[(Read-Answer "Choose 1-5" "1")]
      if (-not $m) { $m = "scripted" }
    }
  }
  switch ($m) {
    "scripted" { Set-EnvValue "MODEL_PROVIDER" "scripted"; Ok "model: demo (scripted), works offline" }
    "ollama" {
      Set-EnvValue "MODEL_PROVIDER" "ollama"; $name = if ($ModelName) { $ModelName } else { $OllamaDefaultModel }
      try {
        Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null
        Set-EnvValue "CONTAINER_OLLAMA_BASE_URL" "http://host.docker.internal:11434/v1"; Set-EnvValue "COMPOSE_PROFILES" "app"
        Ok "using the Ollama found at 127.0.0.1:11434"
      } catch {
        Set-EnvValue "CONTAINER_OLLAMA_BASE_URL" "http://ollama:11434/v1"; Set-EnvValue "COMPOSE_PROFILES" "app,llm"
        Warn "no Ollama found: using Ollama in Docker (CPU only; slower). For speed: https://ollama.com/download"
        $script:OllamaPull = $name
      }
      Set-EnvValue "MODEL_CHAT" $name; Set-EnvValue "MODEL_RESEARCHER" $name
    }
    "openai" {
      $key = Read-Secret "OpenAI API key (sk-...)"; if (-not $key) { Die "an OpenAI API key is needed (-ApiKey ...)" }
      Set-EnvValue "MODEL_PROVIDER" "openai"; Set-EnvValue "OPENAI_API_KEY" $key; Set-EnvValue "OPENAI_BASE_URL" "https://api.openai.com/v1"
      if ($ModelName) { Set-EnvValue "MODEL_CHAT" $ModelName }; Ok "model: OpenAI"
    }
    { $_ -in "foundry", "compatible" } {
      $url = if ($BaseUrl) { $BaseUrl } else { Read-Answer "Endpoint (e.g. https://<resource>.openai.azure.com/openai/v1/)" }
      if (-not $url) { Die "an endpoint URL is needed (-BaseUrl ...)" }
      $key = Read-Secret "API key"; if (-not $key) { $key = "none" }
      $name = if ($ModelName) { $ModelName } else { Read-Answer "Model or deployment name" }
      if (-not $name) { Die "a model / deployment name is needed (-ModelName ...)" }
      Set-EnvValue "MODEL_PROVIDER" "openai"; Set-EnvValue "OPENAI_BASE_URL" $url; Set-EnvValue "OPENAI_API_KEY" $key
      Set-EnvValue "MODEL_CHAT" $name; Set-EnvValue "MODEL_RESEARCHER" $name; Ok "model: $name at $url"
    }
  }
}
function Start-Stack {
  if ($Build) { Say "Building the images (first time: a few minutes)..."; Invoke-Compose build }
  else {
    & docker compose --file $ComposeFile --env-file $EnvFile @(Get-ProfileArgs) pull --quiet --ignore-buildable 2>$null
    if ($LASTEXITCODE -ne 0) { Warn "couldn't download the published images; building them here instead..."; Invoke-Compose build }
  }
  Say "Starting (database, queue, app, 2 API replicas, 2 workers)..."
  try { Invoke-Compose up -d --wait --remove-orphans | Out-Null } catch {
    & docker compose --file $ComposeFile --env-file $EnvFile @(Get-ProfileArgs) logs --tail 30 migrate api
    Die "the stack didn't become healthy (logs above)." @("Diagnostics: .\setup.ps1 -Doctor")
  }
  Ok "all services healthy"
  if ($script:OllamaPull) { Say "Downloading the local model $script:OllamaPull (one time, ~5 GB)..."; Invoke-Compose exec -T ollama ollama pull $script:OllamaPull }
}
function Test-Smoke {
  Say "Checking a real chat turn end to end..."
  try { Invoke-Compose run --rm --no-deps -T api smoke --api http://ui:8080/api --ui http://ui:8080 --timeout 300 } catch { Die "the smoke test failed (above)." @("Diagnostics: .\setup.ps1 -Doctor") }
}

# ------------------------------------------------------------------ actions
if ($Chat) { Test-Docker; Invoke-Compose run --rm --no-deps api chat; exit 0 }
if ($Stop) { Test-Docker; Invoke-Compose stop; Ok "stopped (your data is kept)"; exit 0 }
if ($Doctor) {
  Test-Docker; $out = "diagnostics-$(Get-Date -Format yyyyMMdd-HHmmss)"; New-Item -ItemType Directory $out | Out-Null
  & docker compose --file $ComposeFile --env-file $EnvFile @(Get-ProfileArgs) run --rm --no-deps -T api doctor --api http://ui:8080/api > "$out/doctor.json" 2>$null
  & docker compose --file $ComposeFile --env-file $EnvFile @(Get-ProfileArgs) ps > "$out/services.txt" 2>&1
  & docker compose --file $ComposeFile --env-file $EnvFile @(Get-ProfileArgs) logs --no-color --tail 300 > "$out/logs.txt" 2>&1
  docker version > "$out/docker.txt" 2>&1
  Compress-Archive -Path $out -DestinationPath "$out.zip"; Remove-Item -Recurse $out
  Ok "wrote $out.zip (secrets redacted). Attach it to a GitHub issue."; exit 0
}
if ($Reset) {
  Test-Docker
  if ($Interactive -and (Read-Answer "This DELETES all conversations, agents and downloaded models. Type 'delete' to confirm") -ne "delete") { Die "cancelled; nothing was deleted." }
  Invoke-Compose down -v --remove-orphans; Ok "everything deleted (.env kept)"; exit 0
}

Say "Checking this machine..."; Test-Docker
Initialize-EnvFile; Select-Ports
if ($Update) {
  if ((Test-Path .git) -and -not (git status --porcelain)) { git pull --ff-only }
  New-Item -ItemType Directory -Force backups | Out-Null
  $backup = "backups/agent_runtime-$(Get-Date -Format yyyyMMdd-HHmmss).sql"
  & docker compose --file $ComposeFile --env-file $EnvFile @(Get-ProfileArgs) exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > $backup
  if ($LASTEXITCODE -eq 0) { Ok "database backed up to $backup" } else { Warn "no backup taken (is the stack running?)" }
} else { Set-Model }
Start-Stack; Test-Smoke
Write-Host ""
Say "Nuria is ready."
Write-Host "    Open the app:        http://localhost:$script:UiPortChosen" -ForegroundColor Green
Write-Host "    API docs:            http://localhost:$script:UiPortChosen/docs"
Write-Host "    Chat in a terminal:  .\setup.ps1 -Chat"
Write-Host "    Stop / start again:  .\setup.ps1 -Stop  /  .\setup.ps1"
Write-Host "    Something wrong?     .\setup.ps1 -Doctor   (a report you can attach to an issue)"
if (-not $NonInteractive -and -not $NoBrowser) { Start-Process "http://localhost:$script:UiPortChosen" }
