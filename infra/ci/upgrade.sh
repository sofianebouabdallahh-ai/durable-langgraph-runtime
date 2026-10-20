#!/usr/bin/env bash
# upgrade.sh: an update from the previous release keeps everything, and its backup
# restores it exactly (L5 SC2, SC3). CI runs it on every pull request.
#
#   1. install the previous release (the newest v* tag, else the newest phase-* tag)
#      in a git worktree, as a tester did: ./setup.sh;
#   2. give it data (a chat with a saved note) and take a snapshot through the API;
#   3. move the code to this commit and run ./setup.sh --update: backup, migrate,
#      restart, smoke turn; the snapshot must be unchanged, and a new turn must work;
#   4. change the data, then ./setup.sh --restore the update's backup: the snapshot
#      must match the one before the update again.
#
# Settings: PREV (the release to start from), COMPOSE_PROJECT_NAME (nuria-upgrade).
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO=$PWD
NEW=$(git rev-parse HEAD)
PREV=${PREV:-$(git tag -l 'v*' --sort=-v:refname | head -1)}
PREV=${PREV:-$(git tag -l 'phase-*' --sort=-creatordate | head -1)}
WORK=$(mktemp -d)
DIR="$WORK/nuria"
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-nuria-upgrade}
if ! command -v docker >/dev/null 2>&1 && [ -x "$HOME/.docker/bin/docker" ]; then
  export PATH="$HOME/.docker/bin:$PATH"
fi

say() { printf '\n==> %s\n' "$*"; }
cleanup() {
  (cd "$DIR" 2>/dev/null && docker compose --file infra/compose/docker-compose.yml --env-file .env \
     --profile app down -v --remove-orphans >/dev/null 2>&1) || true
  git -C "$REPO" worktree remove --force "$DIR" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

say "Installing the previous release, $PREV"
git worktree add --quiet --detach "$DIR" "$PREV"
cd "$DIR"
./setup.sh --non-interactive --model scripted --build

api() { echo "http://127.0.0.1:$(awk -F= '$1=="UI_PORT" {print $2}' .env)/api"; }

# The data, and a snapshot of it: chats (title, agent) and every message's type
# and text, in order. Exactly what a tester would miss if it were gone.
python3 - "$(api)" seed <<'EOF'
import json, sys, time, urllib.request
api = sys.argv[1]
def call(method, path, body=None):
    req = urllib.request.Request(api + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)
sid = call("POST", "/sessions", {"agent": "chat"})["id"]
for text in ("Remember that the demo is on Friday", "What is 12 * (3 + 4)?"):
    call("POST", f"/sessions/{sid}/messages", {"content": text})
    for _ in range(120):
        if call("GET", f"/sessions/{sid}")["active_run_id"] is None:
            break
        time.sleep(0.5)
print("seeded", sid)
EOF

snapshot() {
  python3 - "$(api)" <<'EOF'
import json, sys, urllib.request
api = sys.argv[1]
def get(path):
    with urllib.request.urlopen(api + path, timeout=30) as r:
        return json.load(r)
out = []
for s in sorted(get("/sessions?limit=100"), key=lambda s: s["id"]):
    msgs = get(f"/sessions/{s['id']}/messages?limit=500")["messages"]
    out.append({"id": s["id"], "title": s.get("title"),
                "messages": [(m["type"], json.dumps(m["content"], sort_keys=True)) for m in msgs]})
print(json.dumps(out, sort_keys=True))
EOF
}
# The same data, ignoring the chats setup's own smoke turn adds on every start.
same() {
  python3 - "$1" "$2" <<'PY'
import json, sys
mine = lambda path: [s for s in json.load(open(path)) if s["title"] != "smoke test"]
a, b = mine(sys.argv[1]), mine(sys.argv[2])
if a != b:
    ids = lambda d: {s["id"] for s in d}
    print(f"  only before: {sorted(ids(a) - ids(b))}  only after: {sorted(ids(b) - ids(a))}")
    for x in a:
        y = next((s for s in b if s["id"] == x["id"]), None)
        if y and y != x:
            print(f"  chat {x['id']}: {len(x['messages'])} → {len(y['messages'])} messages")
    sys.exit(1)
PY
}
snapshot > "$WORK/before.json"
echo "  snapshot: $(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d), 'chat(s),', sum(len(s['messages']) for s in d), 'messages')" "$WORK/before.json")"

say "Updating to this commit ($NEW)"
# Releases before 0.1.0 have no --to: move the code first, as their `git pull` did.
git -c advice.detachedHead=false checkout --quiet --detach "$NEW"
./setup.sh --non-interactive --build --update --to "$NEW"
snapshot > "$WORK/after.json"
same "$WORK/before.json" "$WORK/after.json" || { echo "FAIL: the update changed the data"; exit 1; }
echo "  PASS  every chat and message survived the update"

BACKUP=$(ls -t backups/*.sql.gz | head -1)
say "Changing the data, then restoring $BACKUP"
python3 - "$(api)" <<'EOF'
import json, sys, urllib.request
req = urllib.request.Request(sys.argv[1] + "/sessions", method="POST", data=b'{"agent": "chat"}',
                             headers={"content-type": "application/json"})
urllib.request.urlopen(req, timeout=30)
EOF
./setup.sh --non-interactive --restore "$BACKUP"
snapshot > "$WORK/restored.json"
same "$WORK/before.json" "$WORK/restored.json" || { echo "FAIL: the restore didn't bring back the data"; exit 1; }
echo "  PASS  the backup restored exactly the data from before the update"
echo
echo "upgrade $PREV → $NEW: PASS"
