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
  .\setup.ps1 -Observability     (also traces, logs and metrics, in Grafana; -NoObservability: off)
  .\setup.ps1 -Kubernetes        (on a local Kubernetes cluster with kind; needs Git Bash or WSL for infra/kind/cluster.sh)
  .\setup.ps1 -Update [-To v0.2.0]    (back up, then move to the newest or that release)
  .\setup.ps1 -Restore backups\nuria-….sql.gz   (put a backup back; replaces today's data)
  .\setup.ps1 -Chat | -Stop | -Doctor | -Reset
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
  [switch]$Observability, [switch]$NoObservability, [switch]$Kubernetes,
  [switch]$Sandbox, [switch]$NoSandbox,
  [switch]$Chat, [switch]$Stop, [switch]$Update, [switch]$Doctor, [switch]$Reset,
  [string]$To = "", [string]$Restore = ""
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
# A Standard Webhooks signing secret: whsec_ and 32 random bytes in base64 (H4).
function New-WebhookSecret {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  "whsec_" + [Convert]::ToBase64String($bytes)
}
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
# Code sandboxes aren't Compose's: sandboxd starts them, one per turn.
function Remove-Sandboxes {
  $ids = & docker ps -aq --filter label=nuria.sandbox=1 2>$null
  if ($ids) { & docker rm -f @($ids) *> $null }
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
  # Secrets added by later versions: an existing .env gets them too (never overwritten).
  foreach ($key in @("NURIA_SECRET_KEY", "SEARXNG_SECRET", "SANDBOXD_TOKEN")) {
    if (-not (Get-EnvValue $key)) { Set-EnvValue $key (New-Secret); $changed++ }
  }
  if (-not (Get-EnvValue "NOTIFY_WEBHOOK_SECRET")) { Set-EnvValue "NOTIFY_WEBHOOK_SECRET" (New-WebhookSecret); $changed++ }
  if ($changed -gt 0) { Ok "generated $changed local secret(s) (only on this machine, in .env)" }
  if (-not (Get-EnvValue "COMPOSE_PROFILES")) { Set-EnvValue "COMPOSE_PROFILES" "app" }
  # The release this checkout is: Compose pulls exactly these images (L5).
  $version = (Get-Content VERSION -Raw).Trim()
  if ((Get-EnvValue "NURIA_VERSION") -ne $version) { Set-EnvValue "NURIA_VERSION" $version }
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
    # Ollama by default: free, private, on this machine. Keys can be added later in the app.
    if (-not $Interactive) { $m = "ollama" } else {
      Say "Which model should the agents use? (you can add others later in the app, under Models)"
      "    1) Ollama, on this computer: free and private (recommended; needs ~6 GB of memory)",
      "    2) OpenAI (your API key)",
      "    3) Azure AI Foundry (your endpoint, key and deployment)",
      "    4) Another OpenAI-compatible service (base URL + key + model)",
      "    5) The offline demo model (scripted answers: to look around, not a real AI)" | ForEach-Object { Write-Host $_ }
      $m = @{ "2" = "openai"; "3" = "foundry"; "4" = "compatible"; "5" = "scripted" }[(Read-Answer "Choose 1-5" "1")]
      if (-not $m) { $m = "ollama" }
    }
  }
  switch ($m) {
    "scripted" { Set-EnvValue "MODEL_PROVIDER" "scripted"; Ok "model: demo (scripted), works offline" }
    "ollama" {
      Set-EnvValue "MODEL_PROVIDER" "ollama"; $name = if ($ModelName) { $ModelName } else { $OllamaDefaultModel }
      try {
        $tags = Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 2
        Set-EnvValue "CONTAINER_OLLAMA_BASE_URL" "http://host.docker.internal:11434/v1"; Set-EnvValue "COMPOSE_PROFILES" "app"
        Ok "using the Ollama found at 127.0.0.1:11434"
        Warn "Tip: for long chats give Ollama a bigger context (OLLAMA_CONTEXT_LENGTH=8192): docs/setup/models.md"
        if (-not ($tags.models | Where-Object { $_.name -eq $name })) { Install-OllamaModel $name }
      } catch {
        Set-EnvValue "CONTAINER_OLLAMA_BASE_URL" "http://ollama:11434/v1"; Set-EnvValue "COMPOSE_PROFILES" "app,llm"
        Warn "no Ollama app found: using Ollama in Docker (CPU only; slower). For speed: https://ollama.com/download"
        # Docker's memory is shared with the whole stack: a 7B model needs about 5 GB of it.
        $mem = [int64](docker info --format '{{.MemTotal}}' 2>$null)
        if (-not $ModelName -and $mem -lt 12000000000) {
          $name = "qwen2.5:3b"; Set-EnvValue "MODEL_CHAT" $name
          Warn "Docker has $([math]::Floor($mem / 1e9)) GB of memory: using the smaller $name (more: Docker Desktop, Settings, Resources)."
        }
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
# The recommended model isn't in the Ollama found on this machine: download it (asked first
# when someone is there). Its CLI shows progress; without it, Ollama's API.
function Install-OllamaModel($name) {
  if ($Interactive -and (Read-Answer "Download $name now for Ollama (one time, about 5 GB)? [Y/n]" "Y") -match "^[nN]") {
    Warn "skipped: run  ollama pull $name  before chatting"; return
  }
  Say "Downloading $name into Ollama (one time, about 5 GB)..."
  try {
    if (Get-Command ollama -ErrorAction SilentlyContinue) { & ollama pull $name; if ($LASTEXITCODE) { throw "pull failed" } }
    else { Invoke-RestMethod -Method Post http://127.0.0.1:11434/api/pull -Body (@{ model = $name; stream = $false } | ConvertTo-Json) -TimeoutSec 3600 | Out-Null }
    Ok "$name is ready"
  } catch { Warn "the download didn't finish: run  ollama pull $name" }
}
function Test-Profile($name) { (",$(Get-EnvValue COMPOSE_PROFILES),") -like "*,$name,*" }

function Set-Observability {  # -Observability / -NoObservability; remembered in .env
  $profiles = ((Get-EnvValue COMPOSE_PROFILES) -split "," | Where-Object { $_ -and $_ -ne "observability" }) -join ","
  if (-not $profiles) { $profiles = "app" }
  if ($NoObservability) {
    Set-EnvValue COMPOSE_PROFILES $profiles; Set-EnvValue OTEL_ENDPOINT ""
    Set-EnvValue TRACE_UI_URL ""; Set-EnvValue DASHBOARD_URL ""
    Ok "observability off (traces, logs and metrics stop being collected)"; return
  }
  if (-not $Observability -and -not (Test-Profile observability)) { return }
  Set-EnvValue COMPOSE_PROFILES "$profiles,observability"
  Set-EnvValue OTEL_ENDPOINT "http://otel-collector:4318"
  $grafana = Select-Port grafana 3000 GRAFANA_PORT 3001 0
  $prometheus = Select-Port prometheus 9090 PROMETHEUS_PORT 9090 0
  Set-EnvValue TRACE_UI_URL "http://localhost:$grafana"  # Grafana: traces (Tempo) and logs (Loki)
  Set-EnvValue DASHBOARD_URL "http://localhost:$grafana/d/nuria"
  Ok "observability: Grafana $grafana (dashboard, traces, logs), metrics $prometheus"
}

function Set-Sandbox {  # -Sandbox / -NoSandbox; on by default; remembered in .env
  $profiles = ((Get-EnvValue COMPOSE_PROFILES) -split "," | Where-Object { $_ -and $_ -ne "sandbox" }) -join ","
  if (-not $profiles) { $profiles = "app" }
  if ($NoSandbox -or (-not $Sandbox -and (Get-EnvValue SANDBOX_ENABLED) -eq "false")) {
    Set-EnvValue COMPOSE_PROFILES $profiles; Set-EnvValue SANDBOXD_URL ""; Set-EnvValue SANDBOX_ENABLED "false"
    Ok "code tools off (Run Python, the terminal and workspace files aren't offered)"; return
  }
  Set-EnvValue COMPOSE_PROFILES "$profiles,sandbox"; Set-EnvValue SANDBOX_ENABLED "true"
  Set-EnvValue SANDBOXD_URL "http://sandboxd:8070"
}

function Build-SandboxImage {  # the image sandboxd starts for each run (built here)
  if (-not (Test-Profile sandbox)) { return }
  $image = "nuria-sandbox:$((Get-Content VERSION -Raw).Trim())"
  docker image inspect $image *> $null
  if ($Build -or $LASTEXITCODE -ne 0) {
    Say "Building the sandbox image (code runs there, one per conversation turn)..."
    docker build -q -t $image sandbox | Out-Null
    if ($LASTEXITCODE -ne 0) { Die "couldn't build the sandbox image." @("Run .\setup.ps1 -NoSandbox to start without the code tools.") }
  }
  Set-EnvValue SANDBOX_IMAGE $image
}

# A checked pg_dump, made and compressed inside the Postgres container and copied out
# (PowerShell's redirection would re-encode it). $null for a fresh install.
function Backup-Database {
  New-Item -ItemType Directory -Force backups | Out-Null
  Invoke-Compose up -d --wait postgres | Out-Null
  $has = Invoke-Compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT to_regclass(''public.runs'') IS NOT NULL"'
  if ("$has".Trim() -ne "t") { Ok "nothing to back up yet (a fresh install)"; return $null }
  $name = "nuria-$((Get-Content VERSION -Raw).Trim())-$(Get-Date -Format yyyyMMdd-HHmmss).sql.gz"
  Invoke-Compose exec -T postgres sh -c "pg_dump -U `"`$POSTGRES_USER`" --clean --if-exists `"`$POSTGRES_DB`" | gzip > /tmp/$name && gzip -dc /tmp/$name | grep -q 'CREATE TABLE public.runs'"
  if ($LASTEXITCODE -ne 0) { Die "the backup failed, so nothing was changed." @("Diagnostics: .\setup.ps1 -Doctor") }
  Invoke-Compose cp "postgres:/tmp/$name" "backups/$name"
  Invoke-Compose exec -T postgres rm -f "/tmp/$name" | Out-Null
  Ok "database backed up to backups/$name"
  return "backups/$name"
}

function Start-Stack {
  Build-SandboxImage
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
  try { Invoke-Compose run --rm --no-deps -T api smoke --api http://ui:8080/api --ui http://ui:8080 --timeout 600 } catch { Die "the smoke test failed (above)." @("Diagnostics: .\setup.ps1 -Doctor") }
}

# ------------------------------------------------------------------ actions
if ($Chat) { Test-Docker; Invoke-Compose run --rm --no-deps api chat; exit 0 }
if ($Stop) { Test-Docker; Invoke-Compose stop; Remove-Sandboxes; Ok "stopped (your data is kept)"; exit 0 }
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
  Invoke-Compose down -v --remove-orphans; Remove-Sandboxes; Ok "everything deleted (.env kept)"; exit 0
}

if ($Kubernetes) {
  Say "Checking this machine..."; Test-Docker; Initialize-EnvFile; Set-Model
  # The cluster script is bash (kind, helm and kubectl are the same on every OS).
  $bash = Get-Command bash -ErrorAction SilentlyContinue
  if (-not $bash) { Die "-Kubernetes needs bash (Git for Windows or WSL)." @("Install Git for Windows, then run .\setup.ps1 -Kubernetes again.") }
  & $bash.Source infra/kind/cluster.sh all
  if ($LASTEXITCODE -ne 0) { Die "the cluster didn't come up (above)." }
  exit 0
}

if ($Restore) {
  Test-Docker; Initialize-EnvFile; Select-Ports
  if (-not (Test-Path $Restore)) { Die "no backup file $Restore." @("Backups: dir backups") }
  if ($Interactive -and (Read-Answer "This REPLACES today's conversations, agents and settings with the backup's. Type 'restore' to confirm") -ne "restore") { Die "cancelled; nothing was changed." }
  Invoke-Compose stop api worker ui | Out-Null
  Invoke-Compose up -d --wait postgres | Out-Null
  Invoke-Compose cp $Restore "postgres:/tmp/restore.sql.gz"
  # The whole schema goes, then the backup comes in, as one transaction (see setup.sh).
  Invoke-Compose exec -T postgres sh -c '{ printf ''DROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n''; gzip -dc /tmp/restore.sql.gz; } | psql -q -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB" > /dev/null && rm -f /tmp/restore.sql.gz'
  if ($LASTEXITCODE -ne 0) { Die "the restore failed (above)." @("Your backup file is unchanged.") }
  Ok "data restored"; Start-Stack; Test-Smoke; Ok "restored from $Restore"; exit 0
}

Say "Checking this machine..."; Test-Docker
Initialize-EnvFile; Select-Ports
if ($Update) {
  if (-not (Test-Path .git)) { Die "-Update needs the git checkout: it moves to the new release." }
  if (git status --porcelain) { Die "this checkout has local changes; an update would mix them in." @("Commit or stash them (git stash), then run -Update again.") }
  $previous = (Get-Content VERSION -Raw).Trim()
  Say "Backing up the database first..."
  $backup = Backup-Database
  git fetch --tags --quiet
  if ($To) { git -c advice.detachedHead=false checkout --quiet $To; if ($LASTEXITCODE -ne 0) { Die "there's no release $To." } }
  elseif ((git describe --exact-match --tags HEAD 2>$null) -like "v*") {
    git -c advice.detachedHead=false checkout --quiet (git tag -l "v*" --sort=-v:refname | Select-Object -First 1)
  } else { git pull --ff-only --quiet }
  Initialize-EnvFile; Select-Ports
  $now = (Get-Content VERSION -Raw).Trim()
  Ok "$previous -> $now"
  Write-Host "    If anything fails: .\setup.ps1 -Update -To v$previous$(if ($backup) { "   then: .\setup.ps1 -Restore $backup" })"
} else { Set-Model }
Set-Observability
Set-Sandbox
Start-Stack; Test-Smoke
Write-Host ""
Say "Nuria is ready."
Write-Host "    Open the app:        http://localhost:$script:UiPortChosen" -ForegroundColor Green
Write-Host "    API docs:            http://localhost:$script:UiPortChosen/docs"
Write-Host "    Chat in a terminal:  .\setup.ps1 -Chat"
Write-Host "    Stop / start again:  .\setup.ps1 -Stop  /  .\setup.ps1"
Write-Host "    Something wrong?     .\setup.ps1 -Doctor   (a report you can attach to an issue)"
if (Test-Profile observability) {
  Write-Host "    Dashboard:           $(Get-EnvValue DASHBOARD_URL)"
  Write-Host "    Traces and logs:     $(Get-EnvValue TRACE_UI_URL)/explore   (or 'Open the trace' under a reply's 'What happened?')"
  Write-Host "    Metrics:             http://localhost:$(Get-EnvValue PROMETHEUS_PORT)"
}
if (-not $NonInteractive -and -not $NoBrowser) { Start-Process "http://localhost:$script:UiPortChosen" }
