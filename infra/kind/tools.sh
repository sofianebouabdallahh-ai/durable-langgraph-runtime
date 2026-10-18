#!/usr/bin/env bash
# tools.sh: the pinned Kubernetes tools (kind, helm, kubectl), downloaded into
# .tools/bin of this repository and verified by SHA-256. Nothing is installed
# system-wide; a version bump is a change to this file (supply-chain cooldown:
# each release at least two weeks old when pinned).
#
#   infra/kind/tools.sh            install what is missing, print the bin directory
set -euo pipefail
cd "$(dirname "$0")/../.."

KIND_VERSION=v0.33.0      # 2026-08-26
HELM_VERSION=v4.3.0       # 2026-09-09
KUBECTL_VERSION=v1.37.1   # 2026-09-23

BIN="$PWD/.tools/bin"
mkdir -p "$BIN"

os=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$(uname -m)" in x86_64|amd64) arch=amd64 ;; arm64|aarch64) arch=arm64 ;; *) echo "unsupported CPU: $(uname -m)" >&2; exit 1 ;; esac
platform="$os-$arch"

sha() {  # sha TOOL PLATFORM → the pinned checksum
  case "$1/$2" in
    kind/darwin-arm64)    echo 0c8c7dbe5e23594a198b786c4bc13dacc101fa6196b0cb0b23a1ca44e61f4b4f ;;
    kind/darwin-amd64)    echo 5a99f26f57246dc9319dd294803313197a0f34d33c525b3ea8b655db5916ece0 ;;
    kind/linux-amd64)     echo aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d ;;
    kind/linux-arm64)     echo 20022bee6cfcd5086cb7234d218e3454e6090022f2a8f55d1fa7fcf42c3867a2 ;;
    helm/darwin-arm64)    echo d3870437e1e95b67f8edbde964156c84a26503f560821d40c542441658934fba ;;
    helm/darwin-amd64)    echo 347a784877e0e20eac865e8d1c36a80f6bb0861d6f29abd34defb6570ef95d92 ;;
    helm/linux-amd64)     echo 86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb ;;
    helm/linux-arm64)     echo 31c5794dd55c66a51e6b7d2e2ac7a114ae8b1de41ff1d9ba51748ac973b06a08 ;;
    kubectl/darwin-arm64) echo fd65982c97ddad3106754b69ffa196d0e543aa591930ae52aed1adfb92f8c77f ;;
    kubectl/darwin-amd64) echo 6851381c486ff6edd691623e3d65c87cb9a5b02887ff8fbbb38d8a031b748387 ;;
    kubectl/linux-amd64)  echo 65691ff77eb6fa44c908b77a1082c9f092c3b9733b5cefabec0d1104890e21a8 ;;
    kubectl/linux-arm64)  echo ff749f4b78d9c4f1ec87307df9b50119ed819e2094aa9810cb9acffc3286c8c7 ;;
    *) echo "no pinned $1 for $2" >&2; exit 1 ;;
  esac
}

verify() {  # verify FILE SHA256
  local got
  if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$1" | cut -d' ' -f1)
  else got=$(shasum -a 256 "$1" | cut -d' ' -f1); fi
  [ "$got" = "$2" ] || { echo "checksum mismatch for $1 (got $got, want $2)" >&2; exit 1; }
}

have() {  # have TOOL VERSION: the pinned version is already in .tools/bin
  [ -x "$BIN/$1" ] && [ -f "$BIN/.$1-$2" ]
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

if ! have kind "$KIND_VERSION"; then
  curl -fsSL -o "$tmp/kind" "https://github.com/kubernetes-sigs/kind/releases/download/$KIND_VERSION/kind-$platform"
  verify "$tmp/kind" "$(sha kind "$platform")"
  install -m 0755 "$tmp/kind" "$BIN/kind" && touch "$BIN/.kind-$KIND_VERSION"
  echo "installed kind $KIND_VERSION" >&2
fi
if ! have helm "$HELM_VERSION"; then
  curl -fsSL -o "$tmp/helm.tgz" "https://get.helm.sh/helm-$HELM_VERSION-$platform.tar.gz"
  verify "$tmp/helm.tgz" "$(sha helm "$platform")"
  tar -xzf "$tmp/helm.tgz" -C "$tmp"
  install -m 0755 "$tmp/$platform/helm" "$BIN/helm" && touch "$BIN/.helm-$HELM_VERSION"
  echo "installed helm $HELM_VERSION" >&2
fi
if ! have kubectl "$KUBECTL_VERSION"; then
  curl -fsSL -o "$tmp/kubectl" "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/$os/$arch/kubectl"
  verify "$tmp/kubectl" "$(sha kubectl "$platform")"
  install -m 0755 "$tmp/kubectl" "$BIN/kubectl" && touch "$BIN/.kubectl-$KUBECTL_VERSION"
  echo "installed kubectl $KUBECTL_VERSION" >&2
fi
echo "$BIN"
