#!/usr/bin/env bash
# gvisor.sh: gVisor (runsc), pinned and verified, for the code sandboxes (phase H9).
#
#   infra/gvisor/gvisor.sh fetch [ARCH]   download it into .tools/gvisor/ARCH (x86_64 or
#                                         aarch64; default: this machine's), print the folder
#   infra/gvisor/gvisor.sh docker         install it into this Linux machine's Docker as the
#                                         `runsc` runtime (sudo; restarts Docker)
#
# gVisor runs on Linux only. Docker Desktop (macOS, Windows) has no supported way to add a
# runtime: docs/security.md says what to do there. A version bump is a change to this
# file (supply-chain cooldown: each release at least two weeks old when pinned).
set -euo pipefail
cd "$(dirname "$0")/../.."

RELEASE=release-20261026.0  # 2026-10-28
URL="https://github.com/google/gvisor/releases/download/$RELEASE"

sha512() {  # the pinned checksum of the release's tarball for ARCH (its SHA512SUMS)
  case "$1" in
    x86_64)  echo 26e4a327565f5da0f73261a6387e2c20f4695a232e330095a3111b70efd604fdf09d734e8cc8f714dbb5c5607ce8c87ea80b26df549d83a146f2efd5a1af448a ;;
    aarch64) echo da177d9bcfd9ac23899ecfedc6fd47358e9684a1f7e3f5f8ffb8bf7c0ca65f4c08730c0c503b9231b522db28b04c132a06d04d6719e0d8c04c9f82edaf03d8ae ;;
    *) echo "gVisor has no build for $1 (x86_64 and aarch64 only)" >&2; exit 1 ;;
  esac
}

arch_of() { case "$(uname -m)" in x86_64|amd64) echo x86_64 ;; arm64|aarch64) echo aarch64 ;; *) uname -m ;; esac; }

fetch() {  # fetch ARCH → .tools/gvisor/ARCH with runsc, containerd-shim-runsc-v1, gvisor-bin/
  local arch="$1" dir="$PWD/.tools/gvisor/$1" want got tmp
  want=$(sha512 "$arch")
  if [ -x "$dir/runsc" ] && [ "$(cat "$dir/.release" 2>/dev/null)" = "$RELEASE" ]; then echo "$dir"; return; fi
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' RETURN
  curl -fsSL --retry 3 -o "$tmp/gvisor.tar.bz2" "$URL/gvisor-$arch.tar.bz2"
  got=$( (sha512sum "$tmp/gvisor.tar.bz2" 2>/dev/null || shasum -a 512 "$tmp/gvisor.tar.bz2") | awk '{print $1}')
  [ "$got" = "$want" ] || { echo "gVisor's download doesn't match its pinned checksum: not installed" >&2; exit 1; }
  rm -rf "$dir"; mkdir -p "$dir"
  tar -xjf "$tmp/gvisor.tar.bz2" -C "$dir"
  echo "$RELEASE" > "$dir/.release"
  echo "$dir"
}

docker_install() {  # into this Linux machine's Docker, as the runtime `runsc`
  [ "$(uname -s)" = Linux ] || { echo "gVisor runs on Linux only" >&2; exit 1; }
  local dir; dir=$(fetch "$(arch_of)")
  sudo install -m 0755 "$dir/runsc" "$dir/containerd-shim-runsc-v1" /usr/local/bin/
  sudo rm -rf /usr/local/bin/gvisor-bin && sudo cp -R "$dir/gvisor-bin" /usr/local/bin/gvisor-bin
  sudo /usr/local/bin/runsc install  # adds it to /etc/docker/daemon.json, keeping the rest
  if command -v systemctl >/dev/null 2>&1; then sudo systemctl restart docker; else sudo service docker restart; fi
  docker info --format '{{json .Runtimes}}' | grep -q '"runsc"' || { echo "Docker doesn't list runsc after the install" >&2; exit 1; }
  echo "gVisor $RELEASE is Docker's runtime \`runsc\`"
}

case "${1:-}" in
  fetch) fetch "${2:-$(arch_of)}" ;;
  docker) docker_install ;;
  *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
