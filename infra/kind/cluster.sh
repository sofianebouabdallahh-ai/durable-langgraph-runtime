#!/usr/bin/env bash
# cluster.sh: Nuria on a local Kubernetes cluster (kind), step by step (R10.2).
#
#   infra/kind/cluster.sh up         the cluster (1 control plane + 2 workers) and its
#                                    add-ons: Traefik (Ingress), metrics-server, KEDA
#   infra/kind/cluster.sh build      build the images (nuria/runtime, nuria/ui) at $TAG
#   infra/kind/cluster.sh load       copy them into the cluster's nodes (never pulled)
#   infra/kind/cluster.sh secrets    the Secret, from .env (only the secret keys)
#   infra/kind/cluster.sh deploy     Postgres + Redis (nuria-data), then Nuria (Helm)
#   infra/kind/cluster.sh smoke      one chat turn through the Ingress
#   infra/kind/cluster.sh all        all of the above, in order
#   infra/kind/cluster.sh status     what runs where
#   infra/kind/cluster.sh down       delete the cluster (and everything in it)
#
# Settings (environment): K8S_PORT (8090: Nuria at http://localhost:8090), TAG (dev),
# NAMESPACE (nuria). The tools (kind, helm, kubectl) are pinned: infra/kind/tools.sh.
set -euo pipefail
cd "$(dirname "$0")/../.."

CLUSTER=nuria
NAMESPACE=${NAMESPACE:-nuria}
RELEASE=nuria
K8S_PORT=${K8S_PORT:-8090}
TAG=${TAG:-dev}
ENV_FILE=${ENV_FILE:-.env}
CHART=infra/helm/agent-runtime

# Add-ons, pinned (each release at least two weeks old when pinned).
TRAEFIK_CHART=41.6.1      # 2026-09-30, Traefik v3: the Ingress controller
METRICS_SERVER_CHART=3.14.0 # 2026-08-19: CPU metrics for the API's HPA
KEDA_CHART=2.21.0         # 2026-09-23: scales workers on the work stream

say() { printf '==> %s\n' "$*"; }
ok()  { printf '  ✓ %s\n' "$*"; }

TOOLS=$(infra/kind/tools.sh)
export PATH="$TOOLS:$PATH"
if ! command -v docker >/dev/null 2>&1 && [ -x "$HOME/.docker/bin/docker" ]; then
  export PATH="$HOME/.docker/bin:$PATH"  # Docker Desktop's CLI on macOS
fi
# The cluster's credentials stay in this repository (.tools/kubeconfig), not in
# ~/.kube/config: nothing of yours is changed, and `down` removes them.
export KUBECONFIG="$PWD/.tools/kubeconfig"
KUBECTL=(kubectl --context "kind-$CLUSTER")
HELM=(helm --kube-context "kind-$CLUSTER")

env_get() { [ -f "$ENV_FILE" ] && awk -F= -v k="$1" '$1==k { sub(/^[^=]*=/, ""); v=$0 } END { print v }' "$ENV_FILE" || true; }

up() {
  if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
    kind export kubeconfig --name "$CLUSTER" >/dev/null 2>&1
    ok "cluster $CLUSTER exists"
  else
    say "Creating the cluster (1 control plane + 2 workers; a few minutes the first time)…"
    sed "s/\${K8S_PORT}/$K8S_PORT/" infra/kind/kind.yaml | kind create cluster --config - --wait 120s
  fi
  say "Installing the add-ons: Traefik, metrics-server, KEDA…"
  "${HELM[@]}" upgrade --install traefik traefik --repo https://traefik.github.io/charts \
    --version "$TRAEFIK_CHART" --namespace traefik --create-namespace \
    --values infra/kind/traefik-values.yaml --wait --timeout 5m >/dev/null
  "${HELM[@]}" upgrade --install metrics-server metrics-server \
    --repo https://kubernetes-sigs.github.io/metrics-server/ --version "$METRICS_SERVER_CHART" \
    --namespace kube-system --set 'args={--kubelet-insecure-tls}' --wait --timeout 5m >/dev/null
  "${HELM[@]}" upgrade --install keda keda --repo https://kedacore.github.io/charts \
    --version "$KEDA_CHART" --namespace keda --create-namespace --wait --timeout 5m >/dev/null
  # Nuria's namespace enforces the restricted Pod Security Standard (R10.10).
  "${KUBECTL[@]}" create namespace "$NAMESPACE" --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f - >/dev/null
  "${KUBECTL[@]}" label namespace "$NAMESPACE" --overwrite \
    pod-security.kubernetes.io/enforce=restricted pod-security.kubernetes.io/warn=restricted >/dev/null
  ok "cluster ready: Traefik on 127.0.0.1:$K8S_PORT, metrics-server, KEDA; namespace $NAMESPACE (restricted)"
}

build() {
  say "Building the images at tag $TAG…"
  docker build -q -t "nuria/runtime:$TAG" backend >/dev/null
  docker build -q -t "nuria/ui:$TAG" frontend >/dev/null
  ok "nuria/runtime:$TAG, nuria/ui:$TAG"
}

load() {
  say "Loading the images into the cluster's nodes…"
  kind load docker-image --name "$CLUSTER" "nuria/runtime:$TAG" "nuria/ui:$TAG" >/dev/null 2>&1
  ok "loaded"
}

secrets() {
  # Only the secret keys of .env, through a private temporary file: never in values,
  # never on the command line, never printed (R10.4).
  [ -f "$ENV_FILE" ] || { echo "no $ENV_FILE: run ./setup.sh (or make env) first" >&2; exit 1; }
  local tmp key value
  tmp=$(mktemp)
  chmod 600 "$tmp"
  for key in POSTGRES_PASSWORD API_POSTGRES_PASSWORD WORKER_POSTGRES_PASSWORD NURIA_SECRET_KEY \
             OPENAI_API_KEY GRAFANA_ADMIN_PASSWORD; do
    value=$(env_get "$key")
    value=${value#\'}; value=${value%\'}; value=${value#\"}; value=${value%\"}
    [ -n "$value" ] && printf '%s=%s\n' "$key" "$value" >> "$tmp"
  done
  "${KUBECTL[@]}" -n "$NAMESPACE" create secret generic nuria-secrets --from-env-file="$tmp" \
    --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f - >/dev/null
  rm -f "$tmp"
  ok "Secret nuria-secrets (from $ENV_FILE)"
}

dashboards() {
  # The same dashboard files as Compose, plus the cluster's own (pods, restarts, KEDA).
  "${KUBECTL[@]}" -n "$NAMESPACE" create configmap nuria-dashboards \
    --from-file=infra/observability/grafana/dashboards/ \
    --from-file=infra/observability/grafana/dashboards-kubernetes/ \
    --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f - >/dev/null
}

deploy() {
  say "Deploying Postgres and Redis (nuria-data)…"
  "${HELM[@]}" upgrade --install nuria-data infra/helm/nuria-data --namespace "$NAMESPACE" \
    --set postgres.database="$(env_get POSTGRES_DB)" --set postgres.user="$(env_get POSTGRES_USER)" \
    --wait --timeout 5m >/dev/null
  dashboards
  # A first install that failed leaves a release Helm can't upgrade: start it over.
  if "${HELM[@]}" -n "$NAMESPACE" history "$RELEASE" >/dev/null 2>&1 \
     && ! "${HELM[@]}" -n "$NAMESPACE" history "$RELEASE" 2>/dev/null | grep -q deployed; then
    "${HELM[@]}" -n "$NAMESPACE" uninstall "$RELEASE" --wait >/dev/null
  fi
  say "Deploying Nuria (migrate, then the UI, the API, the workers, monitoring)…"
  local model=()
  for key in MODEL_PROVIDER MODEL_CHAT MODEL_RESEARCHER OPENAI_BASE_URL; do
    [ -n "$(env_get "$key")" ] && model+=(--set-string "config.$key=$(env_get "$key")")
  done
  "${HELM[@]}" upgrade --install "$RELEASE" "$CHART" --namespace "$NAMESPACE" \
    --values "$CHART/values-kind.yaml" \
    --set image.runtime.tag="$TAG" --set image.ui.tag="$TAG" \
    --set-string config.POSTGRES_DB="$(env_get POSTGRES_DB)" \
    --set-string config.POSTGRES_USER="$(env_get POSTGRES_USER)" \
    --set-string config.API_POSTGRES_USER="$(env_get API_POSTGRES_USER)" \
    --set-string config.WORKER_POSTGRES_USER="$(env_get WORKER_POSTGRES_USER)" \
    --set-string monitoring.traceUiUrl="http://jaeger.localhost:$K8S_PORT" \
    --set-string monitoring.dashboardUrl="http://grafana.localhost:$K8S_PORT/d/nuria" \
    ${model[@]+"${model[@]}"} ${HELM_ARGS:-} --wait --timeout 10m >/dev/null
  ok "deployed: http://localhost:$K8S_PORT"
}

smoke() {
  say "Checking a real chat turn through the Ingress…"
  # From a container on kind's network, as a browser reaches Nuria (via Traefik).
  docker run --rm --network kind -e POSTGRES_PASSWORD=unused \
    -e MODEL_PROVIDER="$("${KUBECTL[@]}" -n "$NAMESPACE" get configmap "$RELEASE-config" -o jsonpath='{.data.MODEL_PROVIDER}')" \
    "nuria/runtime:$TAG" smoke --api "http://$CLUSTER-control-plane/api" \
    --ui "http://$CLUSTER-control-plane" --timeout 300
}

status() {
  "${KUBECTL[@]}" get nodes -o wide
  "${KUBECTL[@]}" -n "$NAMESPACE" get pods -o wide
  "${KUBECTL[@]}" -n "$NAMESPACE" get hpa,scaledobject,pdb 2>/dev/null || true
}

down() {
  kind delete cluster --name "$CLUSTER"
  ok "cluster $CLUSTER deleted"
}

case "${1:-}" in
  up|build|load|secrets|dashboards|deploy|smoke|status|down) "$1" ;;
  all) up; build; load; secrets; deploy; smoke
       echo; say "Nuria runs on Kubernetes: http://localhost:$K8S_PORT"
       echo "    Dashboard: http://grafana.localhost:$K8S_PORT/d/nuria"
       echo "    Traces:    http://jaeger.localhost:$K8S_PORT"
       echo "    Pods:      infra/kind/cluster.sh status" ;;
  *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
