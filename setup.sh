#!/usr/bin/env bash
# setup.sh: run Nuria on this machine. Only Docker is needed.
#
#   ./setup.sh                      first run: checks, .env, model questions, start, smoke
#                                   test, then opens the app (http://localhost:3000)
#   ./setup.sh --model ollama       (re)configure the model, then start
#   ./setup.sh --port 3100          the app on another port (default 3000, or a free one)
#   ./setup.sh --non-interactive --model scripted     no questions (CI, scripts)
#   ./setup.sh --chat               chat in this terminal
#   ./setup.sh --observability      also traces (Jaeger), metrics and a Grafana dashboard
#   ./setup.sh --no-sandbox         without the code tools (Run Python, terminal, files)
#   ./setup.sh --kubernetes         on a local Kubernetes cluster (kind) instead of Compose
#   ./setup.sh --update [--to v0.2.0]   back up, then move to the newest (or that) release
#   ./setup.sh --restore backups/….sql.gz   put a backup back (replaces today's data)
#   ./setup.sh --stop | --doctor | --reset | --help
#
# Safe to run again: it never overwrites a secret or a setting you didn't ask to change.
# Written for bash 3.2 (macOS's default) and Linux; Windows: setup.ps1.
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE_FILE=infra/compose/docker-compose.yml
ENV_FILE=.env
OLLAMA_DEFAULT_MODEL=qwen2.5:7b

# ------------------------------------------------------------------ output
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
else B=""; G=""; Y=""; R=""; N=""; fi
say()  { printf '%s\n' "${B}==>${N} $*"; }
ok()   { printf '%s\n' "  ${G}✓${N} $*"; }
warn() { printf '%s\n' "  ${Y}!${N} $*"; }
ROLLBACK=""  # set during an update: how to go back, printed with any failure
die()  { printf '%s\n' "  ${R}✗ $1${N}" >&2; [ $# -gt 1 ] && printf '    %s\n' "${@:2}" >&2
         [ -n "$ROLLBACK" ] && printf '    %s\n' "To go back to the version you had:" "$ROLLBACK" >&2; exit 1; }

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

# ------------------------------------------------------------------ options
ACTION=start; MODEL=""; INTERACTIVE=1; BUILD=0; OBSERVABILITY=""; SANDBOX=""; TO=""; RESTORE=""; PREVIOUS=""; BACKUP=""
API_KEY="${SETUP_API_KEY:-}"; BASE_URL=""; MODEL_NAME=""; WANT_PORT=""; OPEN_BROWSER=1
while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="${2:?--model needs scripted|ollama|openai|foundry|compatible}"; shift ;;
    --api-key) API_KEY="${2:?}"; shift ;;
    --base-url) BASE_URL="${2:?}"; shift ;;
    --model-name) MODEL_NAME="${2:?}"; shift ;;
    --port) WANT_PORT="${2:?}"; shift ;;
    --no-browser) OPEN_BROWSER=0 ;;
    --non-interactive|-y) INTERACTIVE=0 ;;
    --build) BUILD=1 ;;
    --stop) ACTION=stop ;;
    --reset) ACTION=reset ;;
    --doctor) ACTION=doctor ;;
    --update) ACTION=update ;;
    --to) TO="${2:?--to needs a release, e.g. v0.2.0}"; shift ;;
    --restore) ACTION=restore; RESTORE="${2:?--restore needs a backup file (backups/…)}"; shift ;;
    --finish-update) ACTION=finish-update; PREVIOUS="${2:?}"; BACKUP="${3:-}"; shift 2 ;;  # internal
    --chat) ACTION=chat ;;
    --observability) OBSERVABILITY=on ;;
    --sandbox) SANDBOX=on ;;
    --no-sandbox) SANDBOX=off ;;
    --no-observability) OBSERVABILITY=off ;;
    --kubernetes) ACTION=kubernetes ;;
    -h|--help) usage ;;
    *) die "unknown option: $1" "Run ./setup.sh --help" ;;
  esac
  shift
done
[ -t 0 ] || INTERACTIVE=0

# ------------------------------------------------------------------ .env helpers
env_get() { [ -f "$ENV_FILE" ] && awk -F= -v k="$1" '$1==k { sub(/^[^=]*=/, ""); v=$0 } END { print v }' "$ENV_FILE" || true; }
env_set() {  # replace or append KEY=VALUE, keeping every other line (portable: no sed -i)
  local tmp; tmp=$(mktemp)
  awk -F= -v k="$1" -v v="$2" 'BEGIN { done=0 } $1==k { print k "=" v; done=1; next } { print } END { if (!done) print k "=" v }' "$ENV_FILE" > "$tmp"
  cat "$tmp" > "$ENV_FILE"; rm -f "$tmp"
}
random_secret() { openssl rand -hex 24 2>/dev/null || od -An -tx1 -N24 /dev/urandom | tr -d ' \n'; }

# ------------------------------------------------------------------ docker
find_docker() {
  for d in docker "$HOME/.docker/bin/docker" /usr/local/bin/docker /Applications/Docker.app/Contents/Resources/bin/docker; do
    if command -v "$d" >/dev/null 2>&1; then DOCKER=$(command -v "$d"); export PATH="$(dirname "$DOCKER"):$PATH"; return 0; fi
  done
  die "Docker isn't installed." \
      "macOS / Windows: install Docker Desktop: https://www.docker.com/products/docker-desktop/" \
      "Linux: install Docker Engine + the Compose plugin: https://docs.docker.com/engine/install/"
}
check_docker() {
  find_docker
  "$DOCKER" info >/dev/null 2>&1 || die "Docker is installed but not running." "Start Docker Desktop (or: sudo systemctl start docker), then run ./setup.sh again."
  "$DOCKER" compose version >/dev/null 2>&1 || die "Docker Compose v2 is missing." "Update Docker Desktop, or install the docker-compose-plugin package."
  ok "Docker $("$DOCKER" version --format '{{.Server.Version}}' 2>/dev/null) with Compose $("$DOCKER" compose version --short 2>/dev/null)"
}
profiles() { local p; p=$(env_get COMPOSE_PROFILES); p=${p:-app}; local out=""; IFS=,; for x in $p; do out="$out --profile $x"; done; unset IFS; echo "$out"; }
# shellcheck disable=SC2046
compose() { "$DOCKER" compose --file "$COMPOSE_FILE" --env-file "$ENV_FILE" $(profiles) "$@"; }

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
ours() {  # ours SERVICE CONTAINER_PORT HOST_PORT: is HOST_PORT this stack's own mapping?
  compose port "$1" "$2" 2>/dev/null | grep -q ":$3\$"
}

# ------------------------------------------------------------------ steps
make_env() {
  if [ ! -f "$ENV_FILE" ]; then
    cp .env.example "$ENV_FILE"; FIRST_RUN=1
    ok "created .env from .env.example"
  else
    FIRST_RUN=0
  fi
  chmod 600 "$ENV_FILE"
  local key changed=0
  for key in $(awk -F= '$2 ~ /^change-me/ { print $1 }' "$ENV_FILE"); do
    env_set "$key" "$(random_secret)"; changed=$((changed + 1))
  done
  # Secrets added by later versions: an existing .env gets them too (never overwritten).
  for key in NURIA_SECRET_KEY SEARXNG_SECRET SANDBOXD_TOKEN; do
    [ -n "$(env_get "$key")" ] || { env_set "$key" "$(random_secret)"; changed=$((changed + 1)); }
  done
  [ "$changed" -gt 0 ] && ok "generated $changed local secret(s) (only on this machine, in .env)"
  [ -n "$(env_get COMPOSE_PROFILES)" ] || env_set COMPOSE_PROFILES app
  # The release this checkout is: Compose pulls exactly these images (L5).
  [ "$(env_get NURIA_VERSION)" = "$(cat VERSION)" ] || env_set NURIA_VERSION "$(cat VERSION)"
}

has_data() {  # does the database hold Nuria's schema yet? (a fresh install doesn't)
  [ "$(compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT to_regclass('"'"'public.runs'"'"') IS NOT NULL"' 2>/dev/null | tr -d '[:space:]')" = t ]
}

is_backup() {  # a gzipped pg_dump of Nuria's schema? (grep -c reads it all: no SIGPIPE
               # under pipefail, which `grep -q` would cause by stopping at the first match)
  [ "$(gzip -dc "$1" 2>/dev/null | grep -c 'CREATE TABLE public.runs ')" -ge 1 ]
}

backup_db() {  # a checked pg_dump to backups/; sets BACKUP. Fails if the dump is empty.
  mkdir -p backups
  compose up -d --wait postgres >/dev/null 2>&1 || return 1
  if ! has_data; then BACKUP=""; ok "nothing to back up yet (a fresh install)"; return 0; fi
  BACKUP="backups/nuria-$(cat VERSION)-$(date +%Y%m%d-%H%M%S).sql.gz"
  if ! compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" --clean --if-exists "$POSTGRES_DB"' | gzip > "$BACKUP" \
     || ! is_backup "$BACKUP"; then
    rm -f "$BACKUP"; return 1
  fi
  chmod 600 "$BACKUP"  # it holds your conversations and (encrypted) keys
  ok "database backed up to $BACKUP ($(du -h "$BACKUP" | cut -f1))"
}

pick_port() {  # pick_port SERVICE CONTAINER_PORT ENV_KEY DEFAULT [WANTED] → a host port, saved in .env
  local service=$1 cport=$2 key=$3 default=$4 wanted=${5:-} current p
  current=$(env_get "$key")
  p=${wanted:-${current:-$default}}
  if port_in_use "$p" && ! ours "$service" "$cport" "$p"; then
    [ -n "$wanted" ] && die "port $p is already used by another program." "Choose another one."
    local candidate found=""
    for candidate in "$default" $((default + 1)) $((default + 2)) $((default + 10000)) $((default + 20000)); do
      if ! port_in_use "$candidate" || ours "$service" "$cport" "$candidate"; then found=$candidate; break; fi
    done
    [ -n "$found" ] || die "no free port found for $service." "Free one, or set $key in .env."
    warn "port $p is used by another program; $service will use $found" >&2
    p=$found
  fi
  env_set "$key" "$p"
  echo "$p"
}

choose_ports() {
  UI_PORT=$(pick_port ui 8080 UI_PORT 3000 "$WANT_PORT")
  local pg redis
  pg=$(pick_port postgres 5432 POSTGRES_PORT 5432)
  redis=$(pick_port redis 6379 REDIS_PORT 6379)
  env_set REDIS_URL "redis://localhost:$redis/0"  # for tools on this machine; containers use redis:6379
  ok "ports: app $UI_PORT, Postgres $pg, Redis $redis (all on 127.0.0.1 only)"
}

ask() {  # ask "Question" default  → REPLY
  local q=$1 d=${2:-}
  if [ "$INTERACTIVE" -eq 0 ]; then REPLY=$d; return; fi
  if [ -n "$d" ]; then printf '  %s [%s]: ' "$q" "$d"; else printf '  %s: ' "$q"; fi
  read -r REPLY || true; REPLY=${REPLY:-$d}
}
ask_secret() {  # never echoed, never stored outside .env
  if [ -n "$API_KEY" ] || [ "$INTERACTIVE" -eq 0 ]; then REPLY=$API_KEY; return; fi
  printf '  %s: ' "$1"; read -rs REPLY || true; printf '\n'
}

configure_model() {
  if [ -z "$MODEL" ]; then
    if [ "$FIRST_RUN" -eq 0 ] && [ -n "$(env_get MODEL_PROVIDER)" ]; then
      ok "model: $(env_get MODEL_PROVIDER) (unchanged; ./setup.sh --model … to change)"; return
    fi
    # Ollama by default: free, private, on this machine. Keys can be added later in the
    # app (Models), or chosen here.
    if [ "$INTERACTIVE" -eq 0 ]; then MODEL=ollama; else
      say "Which model should the agents use? (you can add others later in the app, under Models)"
      echo "    1) Ollama, on this computer: free and private (recommended; needs ~6 GB of memory)"
      echo "    2) OpenAI (your API key)"
      echo "    3) Azure AI Foundry (your endpoint, key and deployment)"
      echo "    4) Another OpenAI-compatible service (base URL + key + model)"
      echo "    5) The offline demo model (scripted answers: to look around, not a real AI)"
      ask "Choose 1-5" 1
      case "$REPLY" in 2) MODEL=openai ;; 3) MODEL=foundry ;; 4) MODEL=compatible ;; 5) MODEL=scripted ;; *) MODEL=ollama ;; esac
    fi
  fi
  case "$MODEL" in
    scripted)
      env_set MODEL_PROVIDER scripted; ok "model: demo (scripted), works offline" ;;
    ollama)
      env_set MODEL_PROVIDER ollama
      local name=${MODEL_NAME:-$OLLAMA_DEFAULT_MODEL}
      if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        env_set CONTAINER_OLLAMA_BASE_URL http://host.docker.internal:11434/v1
        env_set COMPOSE_PROFILES app
        ok "using the Ollama found at 127.0.0.1:11434 (the native app uses the GPU; Ollama in Docker on macOS doesn't)"
        curl -fsS http://127.0.0.1:11434/api/tags | grep -q "\"$name\"" || pull_native "$name"
      elif native_ollama_offered; then
        configure_model; return  # installed and running now: take the native path
      else
        env_set CONTAINER_OLLAMA_BASE_URL http://ollama:11434/v1
        env_set COMPOSE_PROFILES app,llm
        warn "no Ollama app found: using Ollama in Docker (CPU only on macOS; slower)."
        warn "For speed on macOS/Windows install the app instead: https://ollama.com/download"
        # Docker's memory is shared with the whole stack: a 7B model needs about 5 GB of it.
        local mem; mem=$("$DOCKER" info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
        if [ -z "$MODEL_NAME" ] && [ "${mem:-0}" -lt 12000000000 ]; then
          name=qwen2.5:3b
          warn "Docker has $((mem / 1000000000)) GB of memory: using the smaller $name (more memory: Docker Desktop → Settings → Resources)."
        fi
        OLLAMA_PULL=$name
      fi
      env_set MODEL_CHAT "$name"; env_set MODEL_RESEARCHER "$name" ;;
    openai)
      ask_secret "OpenAI API key (sk-…)"; [ -n "$REPLY" ] || die "an OpenAI API key is needed (--api-key …)"
      env_set MODEL_PROVIDER openai; env_set OPENAI_API_KEY "$REPLY"; env_set OPENAI_BASE_URL https://api.openai.com/v1
      [ -n "$MODEL_NAME" ] && env_set MODEL_CHAT "$MODEL_NAME"
      ok "model: OpenAI ${MODEL_NAME:-(default gpt-4o-mini)}" ;;
    foundry|compatible)
      local hint="https://<resource>.openai.azure.com/openai/v1/"
      [ "$MODEL" = compatible ] && hint="https://…/v1"
      [ -n "$BASE_URL" ] || { ask "Endpoint (e.g. $hint)" ""; BASE_URL=$REPLY; }
      [ -n "$BASE_URL" ] || die "an endpoint URL is needed (--base-url …)"
      ask_secret "API key"; local key=${REPLY:-none}
      [ -n "$MODEL_NAME" ] || { ask "Model or deployment name" ""; MODEL_NAME=$REPLY; }
      [ -n "$MODEL_NAME" ] || die "a model / deployment name is needed (--model-name …)"
      env_set MODEL_PROVIDER openai; env_set OPENAI_BASE_URL "$BASE_URL"; env_set OPENAI_API_KEY "$key"
      env_set MODEL_CHAT "$MODEL_NAME"; env_set MODEL_RESEARCHER "$MODEL_NAME"
      ok "model: $MODEL_NAME at $BASE_URL" ;;
    *) die "unknown model '$MODEL'" "Use: scripted | ollama | openai | foundry | compatible" ;;
  esac
}

# No Ollama app: on macOS and Windows (where Docker has no GPU and little memory) offer to
# install it first. True when it's running afterwards.
native_ollama_offered() {
  [ "$INTERACTIVE" -eq 1 ] || return 1
  case "$(uname -s)" in Darwin|MINGW*|MSYS*|CYGWIN*) ;; *) return 1 ;; esac
  say "Ollama works best as its app (it uses your GPU and memory directly)."
  echo "    Install it from https://ollama.com/download and open it, then press Enter."
  ask "Press Enter when it's running (or type 'docker' to run Ollama in Docker instead)" ""
  [ "$REPLY" = docker ] && return 1
  curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 \
    || { warn "still no Ollama app at 127.0.0.1:11434: using Ollama in Docker"; return 1; }
}

# The recommended model isn't in the Ollama found on this machine: download it (asked
# first when someone is there). Its CLI shows progress; without it, Ollama's API.
pull_native() {
  local name=$1
  if [ "$INTERACTIVE" -eq 1 ]; then
    ask "Download $name now for Ollama (one time, about 5 GB)? [Y/n]" Y
    case "$REPLY" in [nN]*) warn "skipped: run  ollama pull $name  before chatting"; return ;; esac
  fi
  say "Downloading $name into Ollama (one time, about 5 GB)…"
  if command -v ollama >/dev/null 2>&1; then
    ollama pull "$name" || warn "the download didn't finish: run  ollama pull $name"
  else
    curl -fsS --max-time 3600 -X POST http://127.0.0.1:11434/api/pull \
      -d "{\"model\":\"$name\",\"stream\":false}" >/dev/null \
      && ok "$name is ready" || warn "the download didn't finish: run  ollama pull $name"
  fi
}

has_profile() { case ",$(env_get COMPOSE_PROFILES)," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

configure_observability() {  # --observability / --no-observability; remembered in .env
  local profiles
  profiles=$(env_get COMPOSE_PROFILES | tr ',' '\n' | { grep -v '^observability$' || true; } | paste -sd, -)
  if [ "$OBSERVABILITY" = off ]; then
    env_set COMPOSE_PROFILES "${profiles:-app}"; env_set OTEL_ENDPOINT ""
    env_set TRACE_UI_URL ""; env_set DASHBOARD_URL ""
    ok "observability off (traces and metrics stop being collected)"
    return
  fi
  [ "$OBSERVABILITY" = on ] || has_profile observability || return 0
  env_set COMPOSE_PROFILES "${profiles:-app},observability"
  env_set OTEL_ENDPOINT http://otel-collector:4318
  JAEGER_PORT=$(pick_port jaeger 16686 JAEGER_PORT 16686)
  GRAFANA_PORT=$(pick_port grafana 3000 GRAFANA_PORT 3001)
  PROMETHEUS_PORT=$(pick_port prometheus 9090 PROMETHEUS_PORT 9090)
  env_set TRACE_UI_URL "http://localhost:$JAEGER_PORT"
  env_set DASHBOARD_URL "http://localhost:$GRAFANA_PORT/d/nuria"
  ok "observability: traces $JAEGER_PORT, dashboard $GRAFANA_PORT, metrics $PROMETHEUS_PORT"
}

configure_sandbox() {  # --sandbox / --no-sandbox; on by default; remembered in .env
  local profiles
  profiles=$(env_get COMPOSE_PROFILES | tr ',' '\n' | { grep -v '^sandbox$' || true; } | paste -sd, -)
  if [ "$SANDBOX" = off ] || { [ -z "$SANDBOX" ] && [ "$(env_get SANDBOX_ENABLED)" = false ]; }; then
    env_set COMPOSE_PROFILES "${profiles:-app}"; env_set SANDBOXD_URL ""; env_set SANDBOX_ENABLED false
    ok "code tools off (Run Python, the terminal and workspace files aren't offered)"
    return
  fi
  env_set COMPOSE_PROFILES "${profiles:-app},sandbox"; env_set SANDBOX_ENABLED true
  env_set SANDBOXD_URL http://sandboxd:8070
}

remove_sandboxes() {  # code sandboxes aren't Compose's: sandboxd starts them, one per turn
  local ids; ids=$("$DOCKER" ps -aq --filter label=nuria.sandbox=1 2>/dev/null || true)
  [ -z "$ids" ] || "$DOCKER" rm -f $ids >/dev/null 2>&1 || true
}

sandbox_image() {  # the image sandboxd starts for each run (built here; small, no network)
  has_profile sandbox || return 0
  local image="nuria-sandbox:$(cat VERSION)"
  if [ "$BUILD" -eq 1 ] || ! "$DOCKER" image inspect "$image" >/dev/null 2>&1; then
    say "Building the sandbox image (code runs there, one per conversation turn)…"
    "$DOCKER" build -q -t "$image" sandbox >/dev/null || die "couldn't build the sandbox image." \
      "Run ./setup.sh --no-sandbox to start without the code tools."
  fi
  env_set SANDBOX_IMAGE "$image"
}

start_stack() {
  sandbox_image
  if [ "$BUILD" -eq 1 ]; then
    say "Building the images (first time: a few minutes)…"; compose build
  elif ! compose pull --quiet --ignore-buildable 2>/dev/null; then
    warn "couldn't download the published images; building them here instead (a few minutes)…"
    compose build
  fi
  say "Starting (database, queue, app, 2 API replicas, 2 workers)…"
  compose up -d --wait --remove-orphans >/dev/null || {
    compose ps; compose logs --tail 30 migrate api 2>/dev/null
    die "the stack didn't become healthy (logs above)." "Diagnostics: ./setup.sh --doctor"
  }
  ok "all services healthy"
  if [ -n "${OLLAMA_PULL:-}" ]; then
    say "Downloading the local model $OLLAMA_PULL (one time, ~5 GB)…"
    compose exec -T ollama ollama pull "$OLLAMA_PULL"
  fi
}

smoke() {
  say "Checking a real chat turn end to end…"
  # Through the UI's proxy, as a browser would: the page, then a turn via /api.
  compose run --rm --no-deps -T api smoke --api http://ui:8080/api --ui http://ui:8080 --timeout 300 \
    || die "the smoke test failed (above)." "Diagnostics: ./setup.sh --doctor"
}

# ------------------------------------------------------------------ actions
case "$ACTION" in
  start)
    say "Checking this machine…"; check_docker
    make_env; choose_ports; configure_model; configure_observability; configure_sandbox
    start_stack; smoke
    echo
    say "${G}Nuria is ready.${N}"
    echo "    Open the app:        ${G}http://localhost:$UI_PORT${N}"
    echo "    API docs:            http://localhost:$UI_PORT/docs"
    echo "    Chat in a terminal:  ./setup.sh --chat"
    echo "    Stop / start again:  ./setup.sh --stop  /  ./setup.sh"
    echo "    Something wrong?     ./setup.sh --doctor   (a report you can attach to an issue)"
    if has_profile observability; then
      echo "    Dashboard:           $(env_get DASHBOARD_URL)"
      echo "    Traces:              $(env_get TRACE_UI_URL)   (or \"Open the trace\" under a reply's \"What happened?\")"
      echo "    Metrics:             http://localhost:$(env_get PROMETHEUS_PORT)"
    fi
    if [ "$INTERACTIVE" -eq 1 ] && [ "$OPEN_BROWSER" -eq 1 ]; then
      if command -v open >/dev/null 2>&1; then open "http://localhost:$UI_PORT" >/dev/null 2>&1 || true
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:$UI_PORT" >/dev/null 2>&1 || true
      fi
    fi
    ;;
  kubernetes)
    # The same images on a local multi-node cluster (L4b): kind, Helm, KEDA, Traefik.
    # The tools are downloaded, pinned and verified, into .tools/ (infra/kind/tools.sh).
    say "Checking this machine…"; check_docker
    make_env; configure_model
    PATH="$(dirname "$DOCKER"):$PATH" infra/kind/cluster.sh all
    echo "    Stop it (deletes the cluster): infra/kind/cluster.sh down   ·   Demos: make k8s-demo-podkill (drain, scale, upgrade)"
    ;;
  chat)  check_docker; compose run --rm --no-deps api chat ;;
  stop)  check_docker; compose stop; remove_sandboxes; ok "stopped (your data is kept)" ;;
  doctor)
    check_docker
    out="diagnostics-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$out"
    compose run --rm --no-deps -T api doctor --api http://ui:8080/api > "$out/doctor.json" || true
    compose ps > "$out/services.txt" 2>&1 || true
    compose logs --no-color --tail 300 > "$out/logs.txt" 2>&1 || true
    "$DOCKER" version > "$out/docker.txt" 2>&1 || true
    tar -czf "$out.tar.gz" "$out" && rm -rf "$out"
    ok "wrote $out.tar.gz (secrets redacted). Attach it to a GitHub issue."
    ;;
  update)
    # Back up first, then move the code to the new release, then its images, migrate
    # (expand/contract: an update never breaks data), restart and check (L5).
    check_docker
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "--update needs the git checkout: it moves to the new release."
    git diff --quiet && git diff --cached --quiet \
      || die "this checkout has local changes; an update would mix them in." "Commit or stash them (git stash), then run --update again."
    make_env
    previous=$(cat VERSION)
    say "Backing up the database first…"
    backup_db || die "the backup failed, so nothing was changed." "Diagnostics: ./setup.sh --doctor"
    say "Getting the new release…"
    git fetch --tags --quiet 2>/dev/null || warn "couldn't reach GitHub; updating to what's already here"
    if [ -n "$TO" ]; then
      git -c advice.detachedHead=false checkout --quiet "$TO" 2>/dev/null || die "there's no release $TO." "Releases: git tag -l 'v*'"
    elif git describe --exact-match --tags HEAD 2>/dev/null | grep -q '^v'; then
      latest=$(git tag -l 'v*' --sort=-v:refname | head -1)
      git -c advice.detachedHead=false checkout --quiet "$latest"
    else
      git pull --ff-only --quiet || warn "couldn't fast-forward this branch; staying on it"
    fi
    # The rest is the NEW version's job: its own setup.sh starts its own stack.
    flags=(); [ "$INTERACTIVE" -eq 1 ] || flags+=(--non-interactive); [ "$BUILD" -eq 1 ] && flags+=(--build)
    exec ./setup.sh ${flags[@]+"${flags[@]}"} --finish-update "$previous" "$BACKUP"
    ;;
  finish-update)
    ROLLBACK="  ./setup.sh --update --to v$PREVIOUS${BACKUP:+   then: ./setup.sh --restore $BACKUP}"
    check_docker; make_env; choose_ports; configure_observability; configure_sandbox
    now=$(cat VERSION)
    [ "$now" = "$PREVIOUS" ] && ok "already at $now (restarting on it)" || ok "$PREVIOUS → $now"
    start_stack; smoke
    ROLLBACK=""
    ok "updated to $now${BACKUP:+ (backup: $BACKUP)}"
    ;;
  restore)
    check_docker; make_env
    [ -f "$RESTORE" ] || die "no backup file $RESTORE." "Backups: ls backups/"
    is_backup "$RESTORE" || die "$RESTORE isn't a Nuria backup (a gzipped pg_dump)."
    if [ "$INTERACTIVE" -eq 1 ]; then
      ask "This REPLACES today's conversations, agents and settings with the backup's. Type 'restore' to confirm" ""
      [ "$REPLY" = restore ] || die "cancelled; nothing was changed."
    fi
    say "Restoring $RESTORE…"
    compose stop api worker ui >/dev/null 2>&1 || true
    compose up -d --wait postgres >/dev/null
    # The whole schema goes, then the backup comes in, as one transaction: a backup from an
    # older release has fewer tables, and the newer ones (which may reference its tables)
    # must not survive or block it. Any failure changes nothing. Setup then migrates.
    { printf 'DROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n'; gzip -dc "$RESTORE"; } \
      | compose exec -T postgres sh -c 'psql -q -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null \
      || die "the restore failed (above); nothing was changed." "Your backup file is unchanged; diagnostics: ./setup.sh --doctor"
    ok "data restored"
    start_stack; smoke; ok "restored from $RESTORE"
    ;;
  reset)
    check_docker
    if [ "$INTERACTIVE" -eq 1 ]; then
      ask "This DELETES all conversations, agents and downloaded models. Type 'delete' to confirm" ""
      [ "$REPLY" = delete ] || die "cancelled; nothing was deleted."
    fi
    compose down -v --remove-orphans; remove_sandboxes
    ok "everything deleted (.env kept; delete it too for a fresh start)"
    ;;
esac
