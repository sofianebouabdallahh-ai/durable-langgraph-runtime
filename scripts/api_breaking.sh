#!/usr/bin/env bash
# Breaking changes to the published API (CR-007 R19.2, phase S1): compares the spec at a
# base revision with the working tree's and fails on any change that breaks a client
# generated from the base (a removed operation, field or enum value, a narrowed input).
#
#   scripts/api_breaking.sh [BASE_REF]      default: origin/main
#   make api-breaking BASE=<ref>
#
# oasdiff (Apache-2.0) is pinned, its checksum verified, and kept in .tools/bin, like the
# Kubernetes tools (infra/kind/tools.sh). 1.35.0 is the newest release past the
# repository's two-week cooldown when it was pinned (published 2026-10-28).
set -euo pipefail

OASDIFF_VERSION=1.35.0
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN="$ROOT/.tools/bin"
SPEC=frontend/openapi.json
BASE_REF=${1:-origin/main}

sha() {  # sha PLATFORM: from the release's checksums.txt, checked when pinned
  case "$1" in
    linux_amd64) echo a8023002fcb2eaa7f5758148a9303cb63d33b939886df312268bc0fc7b939140 ;;
    darwin_all) echo 964ad2c0331768c4515fc49779827094bc89a65b1d309dac28886d1c3faf305c ;;
    *) echo "no pinned oasdiff for $1" >&2; exit 1 ;;
  esac
}

verify() {  # verify FILE SHA256
  local got
  if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$1" | cut -d' ' -f1)
  else got=$(shasum -a 256 "$1" | cut -d' ' -f1); fi
  [ "$got" = "$2" ] || { echo "checksum mismatch for $1 (got $got, want $2)" >&2; exit 1; }
}

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) platform=linux_amd64 ;;
  Darwin-*) platform=darwin_all ;;
  *) echo "no pinned oasdiff for $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$BIN"
if ! { [ -x "$BIN/oasdiff" ] && [ -f "$BIN/.oasdiff-$OASDIFF_VERSION" ]; }; then
  archive="oasdiff_${OASDIFF_VERSION}_${platform}.tar.gz"
  curl -fsSL -o "$tmp/$archive" \
    "https://github.com/oasdiff/oasdiff/releases/download/v$OASDIFF_VERSION/$archive"
  verify "$tmp/$archive" "$(sha "$platform")"
  tar -xzf "$tmp/$archive" -C "$tmp" oasdiff
  install -m 0755 "$tmp/oasdiff" "$BIN/oasdiff" && touch "$BIN/.oasdiff-$OASDIFF_VERSION"
  echo "installed oasdiff $OASDIFF_VERSION" >&2
fi

cd "$ROOT"
if ! git cat-file -e "$BASE_REF:$SPEC" 2>/dev/null; then
  echo "api-breaking: $BASE_REF has no $SPEC; nothing to compare" >&2
  exit 0
fi
git show "$BASE_REF:$SPEC" > "$tmp/base.json"
echo "api-breaking: $SPEC at $BASE_REF → the working tree" >&2
# Changes a reviewer accepted, each with its reason (see the file's header).
ACCEPTED="$ROOT/scripts/api_breaking.accepted"
[ -f "$ACCEPTED" ] || : > "$tmp/accepted"
[ -f "$ACCEPTED" ] || ACCEPTED="$tmp/accepted"
"$BIN/oasdiff" breaking "$tmp/base.json" "$SPEC" --fail-on ERR --format text --err-ignore "$ACCEPTED"
echo "api-breaking: no breaking change" >&2
