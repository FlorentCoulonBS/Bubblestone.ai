#!/bin/bash
# =============================================================================
# MAINTENANCE SCRIPT — BubbleStoneAI (72.62.190.147)
# Version 4.0 — Uses shared maintenance-common.sh lib, lives under /opt/bubblestone-ops/
# =============================================================================
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./maintenance-common.sh
source "${SCRIPT_DIR}/maintenance-common.sh"

# --- FLOCK: prevent concurrent executions ---
LOCKFILE="/var/lock/maintenance.lock"
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SKIP: another instance is already running" >> /var/log/maintenance.log
    exit 0
fi

# --- CONFIG (required by lib) ---
HOSTNAME_SRV="BubbleStoneAI"
IP="72.62.190.147"
EMAIL="florent.coulon@bubblestone.ai"
LOGFILE="/var/log/maintenance.log"
DATE=$(date +%Y-%m-%d)
TIME_START=$(date +%s)
MAINT_VERSION="4.0"
MAINT_EMAIL_FROM="florent.coulon@bubblestone.ai"

# --- CONFIG (BubbleStone-specific) ---
REMOTE_HOST="backup@69.62.106.57"
REMOTE_KEY="/root/.ssh/id_ed25519_backup"
REMOTE_DIR="bubblestone"
BACKUP_DIR="/tmp/backup_bubblestone"
COMPOSE_FILE="/opt/repos/bubblestone/infra/docker-compose.yml"
COMPOSE_PROJECT="bubblestone"
SERVICES=(npm site staging 555 audit linkedin-generator compta)
container_name() { echo "bubblestone-${1}"; }

# =============================================================================
# BubbleStone-specific helpers (VPS kernel blocks setuid changes during dpkg)
# =============================================================================
ensure_statoverride() {
    local perms="$1" owner="$2" group="$3" path="$4"
    if ! dpkg-statoverride --list "$path" >/dev/null 2>&1; then
        dpkg-statoverride --add "$owner" "$group" "$perms" "$path" 2>/dev/null && \
            log "statoverride added: $path ($perms $owner:$group)"
    fi
}

fix_suid_permissions() {
    local fixed=0
    for bin_perm in "/usr/bin/su:4755" "/usr/bin/sudo:4755" "/usr/bin/passwd:4755" \
                    "/usr/bin/chfn:4755" "/usr/bin/chsh:4755" "/usr/bin/newgrp:4755" \
                    "/usr/bin/gpasswd:4755" "/opt/google/chrome/chrome-sandbox:4755"; do
        local bin="${bin_perm%%:*}" perm="${bin_perm##*:}"
        if [ -f "$bin" ]; then
            local current
            current=$(stat -c "%a" "$bin" 2>/dev/null)
            if [ "$current" != "$perm" ]; then
                chmod "$perm" "$bin" 2>/dev/null && fixed=$((fixed + 1))
            fi
        fi
    done
    [ $fixed -gt 0 ] && log "Fixed suid permissions on $fixed binaries"
}

# =============================================================================
# send_email — builds all sections, delegates final render to lib's email_send
# =============================================================================
send_email() {
    ROWS=""

    # --- Containers ---
    email_section "🐳 Containers"
    declare -A CNAMES=( [npm]="Nginx Proxy Manager" [site]="bubblestone.ai" [staging]="staging.bubblestone.ai" [555]="AI Trend Dashboard (555)" [audit]="Audit Platform" [linkedin-generator]="LinkedIn Generator" [compta]="Compta (compta.bubblestone.ai)" )
    for svc in "${SERVICES[@]}"; do
        local CNAME STATUS STARTED LABEL
        CNAME=$(container_name "$svc")
        STATUS=$(docker inspect --format '{{.State.Status}}' "$CNAME" 2>/dev/null || echo "absent")
        STARTED=$(docker inspect --format '{{.State.StartedAt}}' "$CNAME" 2>/dev/null | cut -dT -f1)
        LABEL="${CNAMES[$svc]:-$svc}"
        [ "$STATUS" = "running" ] && email_row "✅" "$LABEL — Running (depuis $STARTED)" || email_row "❌" "$LABEL — $STATUS"
    done

    # --- Sites web ---
    email_section "🌐 Sites web"
    local -a URL_LIST=("http://localhost:5000|Dashboard 555 (local)" "https://bubblestone.ai|bubblestone.ai" "http://172.18.0.25|staging.bubblestone.ai" "https://veille.bubblestone.ai|veille.bubblestone.ai" "https://audit.bubblestone.ai|audit.bubblestone.ai")
    for ENTRY in "${URL_LIST[@]}"; do
        local U LABEL CODE
        U="${ENTRY%%|*}"; LABEL="${ENTRY##*|}"
        CODE=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$U" 2>/dev/null) || true
        CODE=${CODE:-000}
        [ "$CODE" -ge 200 ] 2>/dev/null && [ "$CODE" -lt 400 ] 2>/dev/null && email_row "✅" "$LABEL — HTTP $CODE" || email_row "❌" "$LABEL — HTTP $CODE"
    done

    # --- SSL ---
    email_section "🔒 Certificats SSL"
    for DOMAIN in bubblestone.ai staging.bubblestone.ai veille.bubblestone.ai; do
        local EXPIRY DAYS_LEFT
        EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
        if [ -n "$EXPIRY" ]; then
            DAYS_LEFT=$(( ($(date -d "$EXPIRY" +%s) - $(date +%s)) / 86400 ))
            [ "$DAYS_LEFT" -lt 14 ] && email_row "⚠️" "$DOMAIN — ${DAYS_LEFT} jours restants" || email_row "✅" "$DOMAIN — ${DAYS_LEFT} jours restants"
        fi
    done

    # --- System (generic) ---
    email_section_systeme

    # --- Veille IA ---
    email_section "📊 Veille IA"
    local C555 DB_SIZE DB_TOPICS DB_SNAP POD_COUNT POD_LAST
    C555=$(container_name "555")
    DB_SIZE=$(du -sh /opt/bubblestone-555-data/trends.db 2>/dev/null | cut -f1 || echo "?")
    DB_TOPICS=$(docker exec "$C555" python3 -c "import sqlite3;c=sqlite3.connect('/data/trends.db');print(c.execute('SELECT COUNT(*) FROM topic').fetchone()[0])" 2>/dev/null || echo "?")
    DB_SNAP=$(docker exec "$C555" python3 -c "import sqlite3;c=sqlite3.connect('/data/trends.db');print(c.execute('SELECT COUNT(*) FROM topicsnapshot').fetchone()[0])" 2>/dev/null || echo "?")
    email_row "✅" "Base veille — ${DB_SIZE}, ${DB_TOPICS} topics, ${DB_SNAP} snapshots"

    # --- Security (generic) ---
    email_section_securite

    # --- Uptime & Reboot (generic) ---
    email_section_uptime_reboot

    # --- Backup summary ---
    email_section "💾 Sauvegarde"
    local BK_INFO
    BK_INFO=$(grep "Sauvegarde" "$LOGFILE" 2>/dev/null | tail -1 | sed 's/.*[✅❌⚠️] //')
    [ -n "$BK_INFO" ] && email_row "✅" "$BK_INFO" || email_row "✅" "Voir logs"

    # --- Restic differential backup ---
    email_section_restic
    email_section_restic_overview \
        "/opt/bubblestone-restic" \
        "sftp:backup@69.62.106.57:restic/bubblestone" \
        "-i /root/.ssh/id_ed25519_backup -o BatchMode=yes"

    email_send
}

# =============================================================================
log "========== MAINTENANCE $HOSTNAME_SRV START =========="

# ÉTAPE 0 — APT health
maintenance_apt_health

# ÉTAPE 1 — System upgrades (with BubbleStone-specific SUID safeguards)
# Pre-upgrade: ensure dpkg-statoverride for packages with setuid/setgid post-install.
# Hostinger VPS kernels may block suid/sgid bit changes during dpkg unpack/configure;
# statoverride tells dpkg to use these permissions, avoiding chmod failures.
ensure_statoverride 0755 root _ssh /usr/bin/ssh-agent
ensure_statoverride 4755 root root /usr/bin/su
ensure_statoverride 4755 root root /usr/bin/sudo
ensure_statoverride 4755 root root /usr/bin/chfn
ensure_statoverride 4755 root root /usr/bin/chsh
ensure_statoverride 4755 root root /usr/bin/newgrp
ensure_statoverride 4755 root root /usr/bin/gpasswd
ensure_statoverride 4755 root root /usr/bin/passwd
ensure_statoverride 4755 root root /opt/google/chrome/chrome-sandbox

# Mask fstrim.service temporarily during upgrade (util-linux postinst tries to start it)
FSTRIM_WAS_MASKED=false
if systemctl is-enabled fstrim.service 2>/dev/null | grep -q "static"; then
    systemctl mask fstrim.service 2>/dev/null && FSTRIM_WAS_MASKED=true
fi

# Patch uuid-runtime postinst if it chmods without statoverride fallback
UUID_POSTINST="/var/lib/dpkg/info/uuid-runtime.postinst"
if [ -f "$UUID_POSTINST" ] && grep -q "chmod 2775 /var/lib/libuuid" "$UUID_POSTINST" 2>/dev/null; then
    if ! grep -q "chmod 2775 /var/lib/libuuid 2>/dev/null || true" "$UUID_POSTINST" 2>/dev/null; then
        sed -i 's@chmod 2775 /var/lib/libuuid$@chmod 2775 /var/lib/libuuid 2>/dev/null || true@' "$UUID_POSTINST" 2>/dev/null
        log "patched uuid-runtime postinst (chmod tolerance)"
    fi
fi

fix_suid_permissions
maintenance_apt_upgrade
fix_suid_permissions
$FSTRIM_WAS_MASKED && systemctl unmask fstrim.service 2>/dev/null || true

# ÉTAPE 2 — Docker image pulls
# Standalone images used by NPM and the nginx site/staging containers.
log "--- Docker image pulls ---"
DOCKER_PULLS=""
for IMG in jc21/nginx-proxy-manager:latest nginx:alpine; do
    OLD=$(docker image inspect "$IMG" --format '{{.Id}}' 2>/dev/null || echo "none")
    docker pull "$IMG" >/dev/null 2>&1
    NEW=$(docker image inspect "$IMG" --format '{{.Id}}' 2>/dev/null || echo "none")
    [ "$OLD" != "$NEW" ] && DOCKER_PULLS+="$IMG (updated) " || DOCKER_PULLS+="$IMG (up-to-date) "
done
step_ok "Docker pulls" "$DOCKER_PULLS"

# Pull and re-up secondary compose stacks (besides the main one which is rebuilt
# from CI). Currently: leximpact legacy service.
maintenance_docker_pull_update \
    "/opt/repos/bubblestone/infra/bubblestone-leximpact/docker-compose.yml"

# Audit Python deps in the apps shipped from this repo.
maintenance_pip_audit_files \
    /opt/repos/bubblestone/apps/audit-platform/requirements.txt \
    /opt/repos/bubblestone/apps/linkedin-generator/requirements.txt

# ÉTAPE 3 — npm runtime (npm + corepack)
# Updated FIRST so subsequent `npm install -g` calls run against the latest npm.
log "--- npm runtime ---"
maintenance_npm_runtime_update

# ÉTAPE 3b — Claude Code
log "--- Claude Code ---"
maintenance_npm_package_update "Claude Code" "claude --version" "@anthropic-ai/claude-code@latest"

# ÉTAPE 3c — Codex CLI
log "--- Codex CLI ---"
maintenance_npm_package_update "Codex CLI" "codex --version" "@openai/codex@latest"

# ÉTAPE 4 — Restic backup (sole backup mechanism since 2026-05-07)
log "--- Restic ---"
if [ -x /opt/bubblestone-ops/restic-backup.sh ]; then
    RESTIC_OUTPUT=$(/opt/bubblestone-ops/restic-backup.sh 2>&1)
    RESTIC_LINE=$(echo "$RESTIC_OUTPUT" | grep -E '^\[restic-backup\]' | tail -1)
    if echo "$RESTIC_LINE" | grep -q '\[restic-backup\] OK'; then
        step_ok "Restic" "$RESTIC_LINE"
    else
        step_err "Restic" "${RESTIC_LINE:-no output}"
    fi
    echo "$RESTIC_OUTPUT" >> "$LOGFILE"
else
    step_warn "Restic" "Script /opt/bubblestone-ops/restic-backup.sh introuvable"
fi

# ÉTAPE 6 — Verification
log "--- Verification ---"
CONTAINER_FAIL=""
for svc in "${SERVICES[@]}"; do
    CNAME=$(container_name "$svc")
    docker ps --format '{{.Names}}' | grep -q "^${CNAME}$" || CONTAINER_FAIL+="$svc "
done
if [ -n "$CONTAINER_FAIL" ]; then
    step_warn "Vérification" "Containers DOWN: $CONTAINER_FAIL"
else
    step_ok "Vérification" "Tous les containers running"
fi

# ÉTAPE 7 — Cleanup
log "--- Cleanup ---"
PRUNE_OUTPUT=$(docker image prune -f 2>&1)
SPACE_RECLAIMED=$(echo "$PRUNE_OUTPUT" | grep -i "reclaimed" || echo "rien")
maintenance_cleanup_logs
SPACE_CLEAN=$(echo "$SPACE_RECLAIMED" | grep -oP 'Total reclaimed space: \S+' | head -1 || echo "$SPACE_RECLAIMED")
step_ok "Cleanup" "$SPACE_CLEAN"

# ÉTAPE 8 — Sync Claude Code config to remote servers
log "--- Sync Claude config ---"
SYNC_OK=true
for SERVER in "69.62.106.57" "85.31.236.58"; do
    SFTP_BATCH=$(mktemp)
    {
        printf 'put /root/.claude/CLAUDE.md CLAUDE.md\n'
        printf 'put /root/CLAUDE.local.md CLAUDE.local.md\n'
        printf -- '-mkdir memory\n'
    } > "$SFTP_BATCH"
    for memfile in /root/.claude/projects/-root/memory/*.md; do
        if [ -f "$memfile" ]; then
            printf 'put %s memory/%s\n' "$memfile" "$(basename "$memfile")" >> "$SFTP_BATCH"
        fi
    done
    sftp -b "$SFTP_BATCH" -i /root/.ssh/claude_sync_key -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        "claude-sync@${SERVER}" >/dev/null 2>&1 || SYNC_OK=false
    rm -f "$SFTP_BATCH"
done
if $SYNC_OK; then
    step_ok "Sync Claude config" "CLAUDE.md + memory synced to claude-sync inbox on 2 servers"
else
    step_warn "Sync Claude config" "Sync partielle — vérifier connectivité"
fi

# ÉTAPE 9 — Reboot check
maintenance_reboot_check send_email
[ $? -eq 2 ] && exit 0

# ÉTAPE 10 — Email report
log "--- Email report ---"
send_email
[ $? -eq 0 ] && log "✅ Email envoyé à $EMAIL" || log "❌ Échec envoi email"

log "========== MAINTENANCE $HOSTNAME_SRV END =========="
