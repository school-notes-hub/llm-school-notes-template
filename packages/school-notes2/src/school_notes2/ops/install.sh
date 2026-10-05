#!/bin/bash
# Install or roll back a School Notes v2 release in one step (plan 10.1).
#   ops/install.sh <tag>
# Waits for every configured learner's lock (the [students.<name>] tables of config.toml,
# or SN_LEARNERS), unpacks the tag under releases/<tag>/, `uv sync --frozen`,
# builds localhost/school-notes-agent:<tag>, then switches the `current` symlink atomically.
# An already installed tag (rollback) is neither unpacked nor rebuilt.
set -euo pipefail

TAG="${1:?usage: install.sh <tag>}"
ROOT="${SN_ROOT:-/srv/school-notes}"
SOURCE="${SN_TEMPLATE:-$ROOT/template}"     # a clone of the template repository
CONFIG="${SN_CONFIG:-$HOME/.config/school-notes/config.toml}"
RELEASE="$ROOT/releases/$TAG"
PKG="packages/school-notes2"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "tag must look like v2.0.0" >&2; exit 2; }

configured_learners() {
    # The learners in the configuration's table order; never a built-in list of names.
    python3 - "$CONFIG" <<'PY'
import re, sys
try:
    import tomllib
except ImportError:
    sys.exit("python3 >= 3.11 (tomllib) is required to read the configuration")
try:
    with open(sys.argv[1], "rb") as stream:
        names = list(tomllib.load(stream).get("students", {}))
except (OSError, tomllib.TOMLDecodeError) as exc:
    sys.exit(f"cannot read the configuration {sys.argv[1]}: {exc}")
bad = [n for n in names if not re.fullmatch(r"[a-z0-9-]+", n)]
if bad:
    sys.exit(f"learner names must be lowercase ascii: {bad}")
print(" ".join(names))
PY
}

LEARNERS="${SN_LEARNERS:-$(configured_learners)}"
[[ -n "${LEARNERS// /}" ]] || { echo "no learner configured ([students.<name>] in $CONFIG)" >&2; exit 2; }

LOCK_FDS=()

closed() {
    # Children must not inherit the lock descriptors: a long-lived helper (e.g. Podman's
    # rootless pause process) would otherwise keep the learners locked after the install.
    local redirs=""
    for fd in "${LOCK_FDS[@]}"; do redirs+=" $fd>&-"; done
    eval "\"\$@\" $redirs"
}

hold_locks() {
    # Keep every learner's lock for the whole install: no run sees a half-switched release.
    # Same order as round/chat: VM first, then learners. Hold across the symlink switch.
    mkdir -p "$ROOT/state/operations/vm"
    # Serialize installers so one cannot remove another installer's pending flag.
    exec 18>>"$ROOT/state/operations/install.lock"
    flock 18
    LOCK_FDS+=(18)
    touch "$ROOT/state/operations/install-pending"
    trap 'rm -f "$ROOT/state/operations/install-pending"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    exec 19>>"$ROOT/state/operations/vm/lock"
    echo "waiting for the VM lock ..."
    flock 19
    LOCK_FDS+=(19)
    note_holder "$ROOT/state/operations/vm"
    local fd=20
    for learner in $LEARNERS; do
        mkdir -p "$ROOT/state/$learner"
        eval "exec $fd>>\"$ROOT/state/$learner/lock\""
        echo "waiting for the lock of $learner ..."
        flock "$fd"
        LOCK_FDS+=("$fd")
        note_holder "$ROOT/state/$learner"
        fd=$((fd + 1))
    done
}

note_holder() {
    closed python3 - "$1" "$$" <<'PY'
import json, os, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
directory = Path(sys.argv[1])
temporary = directory / "holder.json.new"
temporary.write_text(json.dumps({"pid": int(sys.argv[2]), "kind": "install",
    "since": datetime.now(ZoneInfo("Europe/Budapest")).isoformat()}) + "\n")
os.replace(temporary, directory / "holder.json")
PY
}

unpack() {
    # Unpacked in place: a venv cannot be moved after `uv sync` (absolute shebangs), so an
    # interrupted install is marked by .installing and redone from scratch.
    closed git -C "$SOURCE" fetch --tags --quiet origin
    git -C "$SOURCE" rev-parse --verify --quiet "refs/tags/$TAG^{commit}" >/dev/null \
        || { echo "unknown tag $TAG" >&2; exit 2; }
    rm -rf "$RELEASE"
    mkdir -p "$RELEASE"
    touch "$RELEASE/.installing"
    closed git -C "$SOURCE" archive --output="$RELEASE.tar" "$TAG"
    closed tar -x -f "$RELEASE.tar" -C "$RELEASE"
    rm -f "$RELEASE.tar"
    closed uv --directory "$RELEASE/$PKG" sync --frozen --no-dev --quiet
    # The public-site renderer (Astro) needs its locked Node modules in the release too.
    closed npm --prefix "$RELEASE/packages/study-site" ci --no-audit --no-fund --loglevel=error
    mkdir -p "$RELEASE/bin"
    cat > "$RELEASE/bin/school-notes" <<WRAP
#!/bin/sh
exec "$RELEASE/$PKG/.venv/bin/school-notes" "\$@"
WRAP
    chmod 755 "$RELEASE/bin/school-notes"
    rm "$RELEASE/.installing"
}

build_image() {
    if closed podman image exists "localhost/school-notes-agent:$TAG"; then
        return
    fi
    closed podman build --quiet --build-arg "AGENT_UID=$(id -u)" --build-arg "AGENT_GID=$(id -g)" \
        -t "localhost/school-notes-agent:$TAG" \
        -f "$RELEASE/$PKG/src/school_notes2/container/Containerfile" "$RELEASE"
}

check_open_tasks() {
    # A newer phase.json than this release understands means: finish or discard that run first.
    # The same configuration as the locks: its learners and root are the runs to check.
    closed "$RELEASE/bin/school-notes" --config "$CONFIG" verify-tasks
}

switch_current() {
    ln -sfn "$RELEASE" "$ROOT/current.new"
    mv -T "$ROOT/current.new" "$ROOT/current"
}

hold_locks
{ [ -d "$RELEASE" ] && [ ! -e "$RELEASE/.installing" ]; } || unpack
build_image
check_open_tasks
switch_current
rm -f "$ROOT/state/operations/install-pending"
echo "installed $TAG"
