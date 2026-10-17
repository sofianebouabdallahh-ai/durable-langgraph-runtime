#!/usr/bin/env bash
# setup.sh: run the Durable Agent Runtime on this machine. Only Docker is needed.
#
#   ./setup.sh                      first run: checks, .env, model questions, start, smoke
#                                   test, then opens the app (http://localhost:3000)
#   ./setup.sh --model ollama       (re)configure the model, then start
#   ./setup.sh --port 3100          the app on another port (default 3000, or a free one)
#   ./setup.sh --non-interactive --model scripted     no questions (CI, scripts)
#   ./setup.sh --chat               chat in this terminal
#   ./setup.sh --stop | --update | --doctor | --reset | --help
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
die()  { printf '%s\n' "  ${R}✗ $1${N}" >&2; [ $# -gt 1 ] && printf '    %s\n' "${@:2}" >&2; exit 1; }

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

# ------------------------------------------------------------------ options
ACTION=start; MODEL=""; INTERACTIVE=1; BUILD=0
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
    --chat) ACTION=chat ;;
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
  [ "$changed" -gt 0 ] && ok "generated $changed local secret(s) (only on this machine, in .env)"
  [ -n "$(env_get COMPOSE_PROFILES)" ] || env_set COMPOSE_PROFILES app
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
    if [ "$INTERACTIVE" -eq 0 ]; then MODEL=scripted; else
      say "Which model should the agents use?"
      echo "    1) Demo model: offline, scripted answers (try everything with no key)"
      echo "    2) Local model with Ollama (free; needs ~6 GB RAM)"
      echo "    3) OpenAI (your API key)"
      echo "    4) Azure AI Foundry (your endpoint, key and deployment)"
      echo "    5) Another OpenAI-compatible service (base URL + key + model)"
      ask "Choose 1-5" 1
      case "$REPLY" in 2) MODEL=ollama ;; 3) MODEL=openai ;; 4) MODEL=foundry ;; 5) MODEL=compatible ;; *) MODEL=scripted ;; esac
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
        curl -fsS http://127.0.0.1:11434/api/tags | grep -q "\"$name\"" \
          || warn "model $name isn't downloaded yet: run  ollama pull $name"
      else
        env_set CONTAINER_OLLAMA_BASE_URL http://ollama:11434/v1
        env_set COMPOSE_PROFILES app,llm
        warn "no Ollama found on this machine: using Ollama in Docker (CPU-only on macOS; slower)."
        warn "For speed on macOS/Windows install the app instead: https://ollama.com/download"
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

start_stack() {
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
    make_env; choose_ports; configure_model
    start_stack; smoke
    echo
    say "${G}Ready.${N}"
    echo "    Open the app:        ${G}http://localhost:$UI_PORT${N}"
    echo "    API docs:            http://localhost:$UI_PORT/docs"
    echo "    Chat in a terminal:  ./setup.sh --chat"
    echo "    Stop / start again:  ./setup.sh --stop  /  ./setup.sh"
    echo "    Something wrong?     ./setup.sh --doctor   (a report you can attach to an issue)"
    if [ "$INTERACTIVE" -eq 1 ] && [ "$OPEN_BROWSER" -eq 1 ]; then
      if command -v open >/dev/null 2>&1; then open "http://localhost:$UI_PORT" >/dev/null 2>&1 || true
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:$UI_PORT" >/dev/null 2>&1 || true
      fi
    fi
    ;;
  chat)  check_docker; compose run --rm --no-deps api chat ;;
  stop)  check_docker; compose stop; ok "stopped (your data is kept)" ;;
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
    check_docker; make_env; choose_ports
    if [ -d .git ] && git diff --quiet 2>/dev/null; then git pull --ff-only || warn "couldn't fast-forward; staying on this version"; fi
    mkdir -p backups
    backup="backups/agent_runtime-$(date +%Y%m%d-%H%M%S).sql.gz"
    compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$backup" \
      && ok "database backed up to $backup" || warn "no backup taken (is the stack running?)"
    start_stack; smoke; ok "updated"
    ;;
  reset)
    check_docker
    if [ "$INTERACTIVE" -eq 1 ]; then
      ask "This DELETES all conversations, agents and downloaded models. Type 'delete' to confirm" ""
      [ "$REPLY" = delete ] || die "cancelled; nothing was deleted."
    fi
    compose down -v --remove-orphans; ok "everything deleted (.env kept; delete it too for a fresh start)"
    ;;
esac
