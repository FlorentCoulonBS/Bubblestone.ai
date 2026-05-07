#!/bin/bash
# Auto-sync ops/ from the cloned repo to /opt/<server>-ops/.
# Runs every 5 minutes via /etc/cron.d/sync-ops, idempotent.
#
# Why: the deploy chain GitHub -> repo clone -> /opt/<server>-ops/ has a manual
# "cp" step at the end that historically drifted (Codex CLI step active in /opt
# but missing from origin/main; restic-backup script live but not in the repo).
# This script seals the chain by performing the cp automatically.
#
# Usage: sync-ops-from-repo.sh <repo_dir> <live_ops_dir>
#   ex: sync-ops-from-repo.sh /opt/repos/bubblestone /opt/bubblestone-ops
set -uo pipefail

REPO="${1:?repo dir required}"
LIVE_OPS="${2:?live ops dir required}"
LOG_FILE="/var/log/sync-ops.log"

log() {
    echo "[$(date -Iseconds)] $*" >> "$LOG_FILE"
}

# Step 1 — pull origin/main into the local repo, but only if the working tree
# is clean and we're already on main. This avoids stomping on in-flight work
# (e.g. a feature branch being prepared by codex-ops, or a developer SSH'd in).
cd "$REPO" || { log "ERROR: cannot cd to $REPO"; exit 1; }
git fetch --quiet origin main 2>/dev/null || true

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ "$CURRENT_BRANCH" = "main" ] && git diff --quiet && git diff --cached --quiet; then
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)
    if [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
        git reset --hard origin/main >/dev/null 2>&1
        log "repo $REPO: reset to $(git rev-parse --short HEAD) (was ${LOCAL:0:7})"
    fi
fi

# Step 2 — sync ops/ from the repo into the live ops directory.
# No --delete: we don't want to remove local-only artefacts (logs, runtime
# state) that may exist alongside the versioned scripts. Permissions and
# timestamps are preserved.
if [ -d "$REPO/ops" ] && [ -d "$LIVE_OPS" ]; then
    BEFORE=$(find "$LIVE_OPS" -type f -newer "$REPO/ops" -print 2>/dev/null | wc -l)
    rsync -a "$REPO/ops/" "$LIVE_OPS/"
    AFTER=$(find "$LIVE_OPS" -type f -newer /tmp -print 2>/dev/null | wc -l)
    # Log only when the rsync actually changed something (md5 of a sample file).
    SAMPLE_LIVE=$(md5sum "$LIVE_OPS/maintenance.sh" 2>/dev/null | awk '{print $1}')
    SAMPLE_REPO=$(md5sum "$REPO/ops/maintenance.sh" 2>/dev/null | awk '{print $1}')
    if [ "$SAMPLE_LIVE" = "$SAMPLE_REPO" ] && [ -n "$SAMPLE_LIVE" ]; then
        : # silent — sync was a noop
    else
        log "rsync $REPO/ops -> $LIVE_OPS (drift detected and corrected)"
    fi
fi
