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
COMPOSE_PROJECT="projects"
SERVICES=(npm bubblestone-site bubblestone-staging 555 bubblestone-audit linkedin-generator)
container_name() { echo "${COMPOSE_PROJECT}-${1}-1"; }

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
    declare -A CNAMES=( [npm]="Nginx Proxy Manager" [bubblestone-site]="bubblestone.ai" [bubblestone-staging]="staging.bubblestone.ai" [555]="AI Trend Dashboard (555)" [bubblestone-audit]="Audit Platform" [linkedin-generator]="LinkedIn Generator" )
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
    DB_SIZE=$(du -sh /opt/data/trends.db 2>/dev/null | cut -f1 || echo "?")
    DB_TOPICS=$(docker exec "$C555" python3 -c "import sqlite3;c=sqlite3.connect('/data/trends.db');print(c.execute('SELECT COUNT(*) FROM topic').fetchone()[0])" 2>/dev/null || echo "?")
    DB_SNAP=$(docker exec "$C555" python3 -c "import sqlite3;c=sqlite3.connect('/data/trends.db');print(c.execute('SELECT COUNT(*) FROM topicsnapshot').fetchone()[0])" 2>/dev/null || echo "?")
    email_row "✅" "Base veille — ${DB_SIZE}, ${DB_TOPICS} topics, ${DB_SNAP} snapshots"
    POD_COUNT=$(ls /home/pinceouverte/clawd/podcasts/*.mp3 2>/dev/null | wc -l)
    POD_LAST=$(ls -t /home/pinceouverte/clawd/podcasts/*.mp3 2>/dev/null | head -1 | xargs basename 2>/dev/null | sed 's/555_//;s/\.mp3//' || echo "aucun")
    email_row "✅" "Podcast Le 5·5·5 — ${POD_COUNT} episode(s), dernier: ${POD_LAST}"

    # --- Security (generic) ---
    email_section_securite

    # --- Uptime & Reboot (generic) ---
    email_section_uptime_reboot

    # --- Backup summary ---
    email_section "💾 Sauvegarde"
    local BK_INFO
    BK_INFO=$(grep "Sauvegarde" "$LOGFILE" 2>/dev/null | tail -1 | sed 's/.*[✅❌⚠️] //')
    [ -n "$BK_INFO" ] && email_row "✅" "$BK_INFO" || email_row "✅" "Voir logs"

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
log "--- Docker image pulls ---"
DOCKER_PULLS=""
for IMG in jc21/nginx-proxy-manager:latest nginx:alpine; do
    OLD=$(docker image inspect "$IMG" --format '{{.Id}}' 2>/dev/null || echo "none")
    docker pull "$IMG" >/dev/null 2>&1
    NEW=$(docker image inspect "$IMG" --format '{{.Id}}' 2>/dev/null || echo "none")
    [ "$OLD" != "$NEW" ] && DOCKER_PULLS+="$IMG (updated) " || DOCKER_PULLS+="$IMG (up-to-date) "
done
step_ok "Docker pulls" "$DOCKER_PULLS"

# ÉTAPE 3 — OpenClaw + Claude Code
log "--- OpenClaw + Claude Code ---"
OC_BEFORE=$(node -p "require('/usr/lib/node_modules/openclaw/package.json').version" 2>/dev/null || echo "unknown")
CC_BEFORE=$(claude --version 2>/dev/null || echo "unknown")
npm install -g openclaw@latest --prefix /usr 2>/dev/null
chmod -R o+rX /usr/lib/node_modules/openclaw/ 2>/dev/null
/usr/local/bin/openclaw-patch-media.sh 2>/dev/null || true
npm update -g @anthropic-ai/claude-code 2>/dev/null
OC_AFTER=$(node -p "require('/usr/lib/node_modules/openclaw/package.json').version" 2>/dev/null || echo "unknown")
CC_AFTER=$(claude --version 2>/dev/null || echo "unknown")
OC_UPDATED=""
if [ "$OC_BEFORE" != "$OC_AFTER" ]; then
    OC_UPDATED="OpenClaw: $OC_BEFORE → $OC_AFTER "
    systemctl restart openclaw 2>/dev/null || true
fi
[ "$CC_BEFORE" != "$CC_AFTER" ] && OC_UPDATED+="Claude: $CC_BEFORE → $CC_AFTER"
if [ -z "$OC_UPDATED" ]; then
    step_ok "OpenClaw + Claude" "Déjà à jour (OC:$OC_AFTER CC:$CC_AFTER)"
else
    step_ok "OpenClaw + Claude" "$OC_UPDATED"
fi

# ÉTAPE 4 — Reboot check
maintenance_reboot_check send_email
[ $? -eq 2 ] && exit 0

# ÉTAPE 5 — Backup
log "--- Backup ---"
rm -rf "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

log "Arrêt des containers (docker compose)..."
docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" stop 2>&1 | tail -5
sleep 5

# 5.1 Configs (includes security hardening configs)
tar czf "$BACKUP_DIR/configs.tar.gz" \
    /opt/bubblestone-ops/maintenance.sh \
    /opt/bubblestone-ops/maintenance-common.sh \
    /etc/msmtprc \
    "$COMPOSE_FILE" \
    /etc/lynis/custom.prf \
    /etc/audit/rules.d/audit.rules \
    /etc/systemd/system/cron.service.d/hardening.conf \
    /etc/systemd/system/crowdsec-firewall-bouncer.service.d/hardening.conf \
    /etc/systemd/system/crowdsec.service.d/hardening.conf \
    /etc/systemd/system/fail2ban.service.d/hardening.conf \
    /etc/systemd/system/ssh.service.d/hardening.conf \
    /etc/systemd/system/unattended-upgrades.service.d/hardening.conf \
    /etc/profile.d/99-hardening.sh \
    /etc/ssh/sshd_config.d/01-hardening.conf \
    /etc/ssh/sshd_config.d/90-hardening.conf \
    /opt/bubblestone/nginx.conf \
    /opt/bubblestone-staging/nginx.conf \
    /etc/crowdsec/acquis.yaml \
    /etc/crowdsec/profiles.yaml \
    /etc/fail2ban/jail.local \
    /opt/scripts/ \
    /usr/local/sbin/check-setuid-integrity.sh \
    /usr/local/sbin/weekly-reboot.sh \
    /etc/apt/apt.conf.d/99-check-setuid-integrity \
    /etc/systemd/system/weekly-reboot.service \
    /etc/systemd/system/weekly-reboot.timer \
    2>/dev/null || true

# 5.1b Claude skills symlinks (repo on GitHub, save map for restore)
{
    echo "# Claude skills symlinks — generated $(date -Iseconds)"
    echo "# Restore: git clone git@github.com:FlorentCoulonBS/claude-skills.git /opt/repos/claude-skills"
    for repo in /opt/repos/*/; do
        link="$repo.claude/skills"
        [ -L "$link" ] && echo "ln -sfn $(readlink -f "$link") $link"
    done
    for link in /home/pinceouverte/.claude/skills/*/; do
        [ -L "${link%/}" ] && echo "ln -sfn $(readlink -f "${link%/}") ${link%/}"
    done
} > "$BACKUP_DIR/claude-skills-symlinks.sh" 2>/dev/null || true

# 5.2 Site Astro
tar czf "$BACKUP_DIR/site-astro.tar.gz" \
    --exclude='node_modules' \
    /opt/bubblestone/src /opt/bubblestone/dist \
    /opt/bubblestone-staging/dist \
    2>/dev/null || true

# 5.3 NPM
tar czf "$BACKUP_DIR/npm.tar.gz" /opt/npm/data /opt/npm/letsencrypt 2>/dev/null || true

# 5.4 OpenClaw
tar czf "$BACKUP_DIR/openclaw.tar.gz" \
    --exclude='browser' --exclude='media' \
    /home/pinceouverte/.openclaw 2>/dev/null || true

# 5.5 B-roll pipeline
tar czf "$BACKUP_DIR/broll.tar.gz" /home/pinceouverte/clawd/skills/youtube-broll 2>/dev/null || true
docker save broll-pipeline 2>/dev/null | gzip > "$BACKUP_DIR/broll-pipeline-image.tar.gz" || true

# 5.6 Container 555
tar czf "$BACKUP_DIR/555-data.tar.gz" /opt/data/ /home/pinceouverte/clawd/podcasts/ 2>/dev/null || true
docker save 555 2>/dev/null | gzip > "$BACKUP_DIR/555-image.tar.gz" || true

# 5.7 Audit
tar czf "$BACKUP_DIR/audit-data.tar.gz" /opt/data/audits/ 2>/dev/null || true
docker save bubblestone-audit 2>/dev/null | gzip > "$BACKUP_DIR/audit-image.tar.gz" || true

# 5.8 LinkedIn Generator
tar czf "$BACKUP_DIR/linkedin-data.tar.gz" /opt/data/linkedin/ 2>/dev/null || true
docker save linkedin-generator 2>/dev/null | gzip > "$BACKUP_DIR/linkedin-image.tar.gz" || true

# 5.9 Workspace
tar czf "$BACKUP_DIR/workspace.tar.gz" \
    --exclude='.git' --exclude='node_modules' \
    /home/pinceouverte/clawd/ 2>/dev/null || true

log "Restart des containers (docker compose)..."
docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" start 2>&1 | tail -5
sleep 10

# Ensure all containers are up
BACKUP_ERRORS=0
for svc in "${SERVICES[@]}"; do
    CNAME=$(container_name "$svc")
    if ! docker ps --format '{{.Names}}' | grep -q "^${CNAME}$"; then
        log "⚠️ Container $svc ($CNAME) non redémarré — tentative up..."
        docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" up -d "$svc" 2>&1
        sleep 3
        if ! docker ps --format '{{.Names}}' | grep -q "^${CNAME}$"; then
            log "❌ Container $svc toujours DOWN après up"
            BACKUP_ERRORS=$((BACKUP_ERRORS + 1))
        fi
    fi
done

# Archive + transfer
ARCHIVE="/tmp/backup-bubblestone-${DATE}.tar.gz"
tar czf "$ARCHIVE" -C "$BACKUP_DIR" . 2>/dev/null || true
ARCHIVE_SIZE=$(du -sh "$ARCHIVE" 2>/dev/null | cut -f1)

SFTP_BATCH=$(mktemp)
printf 'put %s %s/\n' "$ARCHIVE" "$REMOTE_DIR" > "$SFTP_BATCH"

if sftp -b "$SFTP_BATCH" -i "$REMOTE_KEY" -o StrictHostKeyChecking=no "$REMOTE_HOST" >/dev/null 2>&1; then
    step_ok "Sauvegarde" "Archive ${ARCHIVE_SIZE} transférée vers DALMATA"
else
    step_err "Sauvegarde" "Transfert SFTP échoué (archive locale: ${ARCHIVE_SIZE})"
fi

find /opt/backups/n8n -name 'backup-dalmata-*.tar.gz' -mtime +7 -delete 2>/dev/null || true

rm -f "$SFTP_BATCH"
rm -rf "$BACKUP_DIR" "$ARCHIVE"

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
PRUNE_OUTPUT=$(docker image prune -f 2>&1 && docker volume prune -f 2>&1)
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

# ÉTAPE 9 — Email report
log "--- Email report ---"
send_email
[ $? -eq 0 ] && log "✅ Email envoyé à $EMAIL" || log "❌ Échec envoi email"

log "========== MAINTENANCE $HOSTNAME_SRV END =========="
