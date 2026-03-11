#!/bin/bash
# =============================================================================
# MAINTENANCE SCRIPT — BubbleStoneAI (72.62.190.147)
# Version 3.3 — Log apt errors on failure
# =============================================================================
set -o pipefail

# --- FLOCK: prevent concurrent executions ---
LOCKFILE="/var/lock/maintenance.lock"
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SKIP: another instance is already running" >> /var/log/maintenance.log
    exit 0
fi

# --- CONFIG ---
HOSTNAME_SRV="BubbleStoneAI"
IP="72.62.190.147"
REMOTE_HOST="root@69.62.106.57"
REMOTE_KEY="/root/.ssh/id_ed25519_backup"
REMOTE_DIR="/root/backups/bubblestone"
EMAIL="florent.coulon@bubblestone.ai"
LOGFILE="/var/log/maintenance.log"
BACKUP_DIR="/tmp/backup_bubblestone"
DATE=$(date +%Y-%m-%d)
TIME_START=$(date +%s)
COMPOSE_FILE="/home/pinceouverte/clawd/projects/docker-compose-bubblestoneai.yml"
COMPOSE_PROJECT="projects"
# Service names in compose file
SERVICES=(npm bubblestone-site bubblestone-staging 555 bubblestone-audit linkedin-generator)
# Map service → actual container name (docker compose prefixes)
container_name() { echo "${COMPOSE_PROJECT}-${1}-1"; }

# --- COUNTERS ---
SUCCESS=0
WARNINGS=0
ERRORS=0
REPORT=""

# --- HELPERS ---
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOGFILE"
}

step_ok() {
    SUCCESS=$((SUCCESS + 1))
    REPORT+="<tr><td style='padding:8px;border-bottom:1px solid #eee'>✅</td><td style='padding:8px;border-bottom:1px solid #eee'>$1</td><td style='padding:8px;border-bottom:1px solid #eee'>$2</td></tr>"
    log "✅ $1: $2"
}

step_warn() {
    WARNINGS=$((WARNINGS + 1))
    REPORT+="<tr style='background:#fff8e1'><td style='padding:8px;border-bottom:1px solid #eee'>⚠️</td><td style='padding:8px;border-bottom:1px solid #eee'>$1</td><td style='padding:8px;border-bottom:1px solid #eee'>$2</td></tr>"
    log "⚠️ $1: $2"
}

step_err() {
    ERRORS=$((ERRORS + 1))
    REPORT+="<tr style='background:#ffebee'><td style='padding:8px;border-bottom:1px solid #eee'>❌</td><td style='padding:8px;border-bottom:1px solid #eee'>$1</td><td style='padding:8px;border-bottom:1px solid #eee'>$2</td></tr>"
    log "❌ $1: $2"
}

wait_apt_lock() {
    local waited=0
    # Only check file locks — pgrep unreliable (unattended-upgrade-shutdown is a permanent daemon)
    while fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock /var/cache/apt/archives/lock >/dev/null 2>&1; do
        if [ $waited -ge 300 ]; then
            step_err "APT Lock" "Timeout après 300s (unattended-upgrades ou dpkg bloquant)"
            return 1
        fi
        [ $((waited % 30)) -eq 0 ] && log "Attente lock apt/dpkg... (${waited}s)"
        sleep 10
        waited=$((waited + 10))
    done
    return 0
}

send_email() {
    local TIME_END=$(date +%s)
    local DURATION=$(( TIME_END - TIME_START ))
    local DURATION_MIN=$(( DURATION / 60 ))
    local DURATION_SEC=$(( DURATION % 60 ))

    local ROWS=""
    row() { ROWS+="<tr><td style='padding:8px 12px;border-bottom:1px solid #eee;width:30px'>$1</td><td style='padding:8px 12px;border-bottom:1px solid #eee'>$2</td></tr>"; }
    section() { ROWS+="<tr><td colspan='2' style='padding:14px 12px 6px;font-weight:700;color:#667eea;border-bottom:2px solid #667eea;font-size:13px;text-transform:uppercase;letter-spacing:1px'>$1</td></tr>"; }

    # --- Containers ---
    section "🐳 Containers"
    declare -A CNAMES=( [npm]="Nginx Proxy Manager" [bubblestone-site]="bubblestone.ai" [bubblestone-staging]="staging.bubblestone.ai" [555]="AI Trend Dashboard (555)" [bubblestone-audit]="Audit Platform" [linkedin-generator]="LinkedIn Generator" )
    for svc in "${SERVICES[@]}"; do
        local CNAME=$(container_name "$svc")
        local STATUS=$(docker inspect --format '{{.State.Status}}' "$CNAME" 2>/dev/null || echo "absent")
        local STARTED=$(docker inspect --format '{{.State.StartedAt}}' "$CNAME" 2>/dev/null | cut -dT -f1)
        local LABEL="${CNAMES[$svc]:-$svc}"
        [ "$STATUS" = "running" ] && row "✅" "$LABEL — Running (depuis $STARTED)" || row "❌" "$LABEL — $STATUS"
    done

    # --- Sites web ---
    section "🌐 Sites web"
    local -a URL_LIST=("http://localhost:5000|Dashboard 555 (local)" "https://bubblestone.ai|bubblestone.ai" "http://172.18.0.25|staging.bubblestone.ai" "https://veille.bubblestone.ai|veille.bubblestone.ai" "https://audit.bubblestone.ai|audit.bubblestone.ai")
    for ENTRY in "${URL_LIST[@]}"; do
        local U="${ENTRY%%|*}" LABEL="${ENTRY##*|}"
        local CODE
        CODE=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$U" 2>/dev/null) || true
        CODE=${CODE:-000}
        [ "$CODE" -ge 200 ] 2>/dev/null && [ "$CODE" -lt 400 ] 2>/dev/null && row "✅" "$LABEL — HTTP $CODE" || row "❌" "$LABEL — HTTP $CODE"
    done

    # --- SSL ---
    section "🔒 Certificats SSL"
    for DOMAIN in bubblestone.ai staging.bubblestone.ai veille.bubblestone.ai; do
        local EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
        if [ -n "$EXPIRY" ]; then
            local DAYS_LEFT=$(( ($(date -d "$EXPIRY" +%s) - $(date +%s)) / 86400 ))
            [ "$DAYS_LEFT" -lt 14 ] && row "⚠️" "$DOMAIN — ${DAYS_LEFT} jours restants" || row "✅" "$DOMAIN — ${DAYS_LEFT} jours restants"
        fi
    done

    # --- Systeme ---
    section "💾 Systeme"
    local DISK_PCT=$(df / | awk 'NR==2 {gsub(/%/,""); print $5}')
    local DISK_USED=$(df -h / | awk 'NR==2 {print $3}')
    local DISK_TOTAL=$(df -h / | awk 'NR==2 {print $2}')
    local DISK_FREE=$(df -h / | awk 'NR==2 {print $4}')
    [ "$DISK_PCT" -gt 80 ] && row "⚠️" "Disque — ${DISK_PCT}% (${DISK_USED}/${DISK_TOTAL}, libre: ${DISK_FREE})" || row "✅" "Disque — ${DISK_PCT}% (${DISK_USED}/${DISK_TOTAL}, libre: ${DISK_FREE})"
    local DOCKER_IMG_SIZE=$(docker system df --format '{{.Type}}\t{{.Size}}' 2>/dev/null | awk -F'\t' '/Images/{print $2}')
    row "✅" "Docker images — ${DOCKER_IMG_SIZE}"

    # --- Veille IA ---
    section "📊 Veille IA"
    local C555=$(container_name "555")
    local DB_SIZE=$(du -sh /root/data/trends.db 2>/dev/null | cut -f1 || echo "?")
    local DB_TOPICS=$(docker exec "$C555" python3 -c "import sqlite3;c=sqlite3.connect('/data/trends.db');print(c.execute('SELECT COUNT(*) FROM topic').fetchone()[0])" 2>/dev/null || echo "?")
    local DB_SNAP=$(docker exec "$C555" python3 -c "import sqlite3;c=sqlite3.connect('/data/trends.db');print(c.execute('SELECT COUNT(*) FROM topicsnapshot').fetchone()[0])" 2>/dev/null || echo "?")
    row "✅" "Base veille — ${DB_SIZE}, ${DB_TOPICS} topics, ${DB_SNAP} snapshots"
    local POD_COUNT=$(ls /home/pinceouverte/clawd/podcasts/*.mp3 2>/dev/null | wc -l)
    local POD_LAST=$(ls -t /home/pinceouverte/clawd/podcasts/*.mp3 2>/dev/null | head -1 | xargs basename 2>/dev/null | sed 's/555_//;s/\.mp3//' || echo "aucun")
    row "✅" "Podcast Le 5·5·5 — ${POD_COUNT} episode(s), dernier: ${POD_LAST}"

    # --- Securite ---
    section "🛡️ Securite"

    # Lynis — read last daily scan result (lynis.timer runs daily)
    local LYNIS_SCORE
    LYNIS_SCORE=$(grep -oP 'hardening_index=\K[0-9]+' /var/log/lynis-report.dat 2>/dev/null || echo "?")
    local LYNIS_DATE=$(stat -c '%Y' /var/log/lynis-report.dat 2>/dev/null)
    local LYNIS_AGE="?"
    if [ -n "$LYNIS_DATE" ]; then
        LYNIS_AGE=$(( ($(date +%s) - LYNIS_DATE) / 3600 ))
    fi
    if [ "$LYNIS_SCORE" != "?" ] && [ "$LYNIS_SCORE" -ge 70 ] 2>/dev/null; then
        row "✅" "Lynis hardening index — ${LYNIS_SCORE}/100 (scan il y a ${LYNIS_AGE}h)"
    else
        row "⚠️" "Lynis hardening index — ${LYNIS_SCORE}/100 (scan il y a ${LYNIS_AGE}h)"
    fi

    # rkhunter — read last daily log
    local RKH_WARNINGS
    RKH_WARNINGS=$(grep -c "\[ Warning \]" /var/log/rkhunter.log 2>/dev/null) || RKH_WARNINGS="0"
    if [ "$RKH_WARNINGS" -eq 0 ] 2>/dev/null; then
        row "✅" "rkhunter — Aucun warning (dernier scan)"
    else
        row "⚠️" "rkhunter — ${RKH_WARNINGS} warning(s) (dernier scan)"
    fi

    # CrowdSec active decisions
    local CS_DECISIONS
    CS_DECISIONS=$(cscli decisions list -o json 2>/dev/null | jq 'if . == null then 0 else length end' 2>/dev/null || echo "?")
    row "✅" "CrowdSec — ${CS_DECISIONS} decision(s) active(s)"

    # auditd events 24h
    local AUDIT_EVENTS
    AUDIT_EVENTS=$(ausearch -ts recent 2>/dev/null | grep -c "^type=") || true
    row "✅" "auditd — ${AUDIT_EVENTS} evenement(s) (24h)"

    # fail2ban active bans
    local F2B_BANS
    F2B_BANS=$(fail2ban-client status 2>/dev/null | grep "Jail list" | sed 's/.*://;s/,/\n/g' | while read jail; do
        jail=$(echo "$jail" | xargs)
        [ -n "$jail" ] && fail2ban-client status "$jail" 2>/dev/null | grep "Currently banned" | awk '{print $NF}'
    done | paste -sd+ | bc 2>/dev/null || echo "0")
    [ -z "$F2B_BANS" ] && F2B_BANS="0"
    row "✅" "fail2ban — ${F2B_BANS} IP(s) bannie(s)"

    # UFW
    local UFW_RULES
    UFW_RULES=$(ufw status 2>/dev/null | grep -c "ALLOW") || UFW_RULES="0"
    local UFW_PORTS=$(ufw status 2>/dev/null | grep "ALLOW" | awk '{print $1}' | sort -u | tr '\n' ',' | sed 's/,$//')
    row "✅" "Firewall UFW — actif, ${UFW_RULES} regles (${UFW_PORTS})"

    # SSH failed
    local SSH_FAILED
    SSH_FAILED=$(journalctl _SYSTEMD_UNIT=ssh.service --since "24 hours ago" 2>/dev/null | grep -c "Failed") || SSH_FAILED="0"
    [ "$SSH_FAILED" -gt 10 ] 2>/dev/null && row "⚠️" "SSH — ${SSH_FAILED} tentatives echouees (24h)" || row "✅" "SSH — ${SSH_FAILED} tentative(s) echouee(s) (24h)"

    # --- Sauvegarde ---
    section "💾 Sauvegarde"
    local BK_INFO=$(grep "Sauvegarde" "$LOGFILE" 2>/dev/null | tail -1 | sed 's/.*[✅❌⚠️] //')
    [ -n "$BK_INFO" ] && row "✅" "$BK_INFO" || row "✅" "Voir logs"

    # --- Header ---
    local STATUS_LABEL="SUCCES" STATUS_ICON="✅"
    local HEADER_BG="linear-gradient(135deg,#43a047 0%,#66bb6a 100%)"
    if [ "$ERRORS" -gt 0 ]; then
        STATUS_LABEL="ERREURS"; STATUS_ICON="❌"
        HEADER_BG="linear-gradient(135deg,#e53935 0%,#ef5350 100%)"
    elif [ "$WARNINGS" -gt 0 ]; then
        STATUS_LABEL="WARNINGS"; STATUS_ICON="⚠️"
        HEADER_BG="linear-gradient(135deg,#f57f17 0%,#ffb300 100%)"
    fi

    local SUBJECT="$STATUS_ICON Maintenance $STATUS_LABEL — $HOSTNAME_SRV ($DATE)"

    cat <<EOF | msmtp "$EMAIL"
From: florent.coulon@bubblestone.ai
To: $EMAIL
Subject: $SUBJECT
Content-Type: text/html; charset=UTF-8
MIME-Version: 1.0

<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5">
<div style="max-width:700px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1)">

<div style="background:${HEADER_BG};padding:30px;text-align:center;color:white">
<h1 style="margin:0;font-size:24px">$STATUS_ICON Maintenance $STATUS_LABEL</h1>
<p style="margin:8px 0 0;opacity:0.9">$HOSTNAME_SRV ($IP) — $DATE</p>
</div>

<div style="padding:25px">

<div style="display:flex;justify-content:center;gap:20px;margin-bottom:25px;text-align:center">
<div style="display:inline-block;text-align:center;margin:0 10px"><div style="font-size:32px;font-weight:700;color:#2e7d32">$SUCCESS</div><div style="font-size:12px;color:#888">Succes</div></div>
<div style="display:inline-block;text-align:center;margin:0 10px"><div style="font-size:32px;font-weight:700;color:#f57f17">$WARNINGS</div><div style="font-size:12px;color:#888">Warnings</div></div>
<div style="display:inline-block;text-align:center;margin:0 10px"><div style="font-size:32px;font-weight:700;color:#c62828">$ERRORS</div><div style="font-size:12px;color:#888">Erreurs</div></div>
</div>

<p style="text-align:center;color:#666;margin-bottom:25px">⏱ Duree totale: ${DURATION_MIN}min ${DURATION_SEC}s</p>

<table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:20px">
<tr><td colspan='3' style='padding:14px 12px 6px;font-weight:700;color:#667eea;border-bottom:2px solid #667eea;font-size:13px;text-transform:uppercase;letter-spacing:1px'>🔧 Étapes maintenance</td></tr>
$REPORT
</table>

<table style="width:100%;border-collapse:collapse;font-size:14px">
$ROWS
</table>

</div>
<div style="background:#f8f9fa;padding:15px;text-align:center;color:#999;font-size:12px">Email automatique — $HOSTNAME_SRV Maintenance v3.3</div>
</div>
</body></html>
EOF
}



# =============================================================================
log "========== MAINTENANCE $HOSTNAME_SRV START =========="

# ÉTAPE 1 — Mises à jour système
log "--- ÉTAPE 1 : Mises à jour système ---"
if wait_apt_lock; then
    APT_OUTPUT=$(apt-get update 2>&1)
    if [ $? -eq 0 ]; then
        # Fix broken dependencies if any (VPS kernel packages can leave dpkg in bad state)
        DEBIAN_FRONTEND=noninteractive dpkg --configure -a 2>/dev/null || true
        HELD_COUNT=$(apt-mark showhold 2>/dev/null | wc -l)
        UPGRADE_OUTPUT=$(DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y 2>&1)
        if [ $? -eq 0 ]; then
            UPGRADED=$(echo "$UPGRADE_OUTPUT" | grep -c "^Inst ") || UPGRADED="0"
            DEBIAN_FRONTEND=noninteractive apt-get autoremove -y 2>&1 >/dev/null
            step_ok "Mises à jour système" "${UPGRADED} paquet(s) mis à jour (${HELD_COUNT} held)"
        else
            # Retry: fix-broken then dist-upgrade
            # VPS blocks suid bit on chrome-sandbox, use --force-all as fallback
            log "dist-upgrade echoue (erreur: $(echo "$UPGRADE_OUTPUT" | tail -5)), tentative fix-broken + force-all..."
            DEBIAN_FRONTEND=noninteractive apt --fix-broken install -y 2>&1 >/dev/null || true
            DEBIAN_FRONTEND=noninteractive dpkg --force-all --configure -a 2>/dev/null || true
            apt-get update -q 2>&1 >/dev/null
            UPGRADE_OUTPUT=$(DEBIAN_FRONTEND=noninteractive apt-get -o Dpkg::Options::="--force-all" dist-upgrade -y 2>&1)
            if [ $? -eq 0 ]; then
                UPGRADED=$(echo "$UPGRADE_OUTPUT" | grep -c "^Inst ") || UPGRADED="0"
                DEBIAN_FRONTEND=noninteractive apt-get autoremove -y 2>&1 >/dev/null
                step_ok "Mises à jour système" "${UPGRADED} paquet(s) mis à jour (retry+force)"
            else
                log "dist-upgrade retry echoue: $(echo "$UPGRADE_OUTPUT" | tail -10)"
                step_err "Mises à jour système" "apt dist-upgrade échoué après retry"
            fi
        fi
    else
        log "apt update echoue: $(echo "$APT_OUTPUT" | tail -5)"
        step_err "Mises à jour système" "apt update échoué"
    fi
fi

# ÉTAPE 2 — Mises à jour Docker
log "--- ÉTAPE 2 : Mises à jour Docker ---"
DOCKER_PULLS=""
for IMG in jc21/nginx-proxy-manager:latest nginx:alpine; do
    OLD=$(docker image inspect "$IMG" --format '{{.Id}}' 2>/dev/null || echo "none")
    PULL_OUT=$(docker pull "$IMG" 2>&1)
    NEW=$(docker image inspect "$IMG" --format '{{.Id}}' 2>/dev/null || echo "none")
    if [ "$OLD" != "$NEW" ]; then
        DOCKER_PULLS+="$IMG (updated) "
    else
        DOCKER_PULLS+="$IMG (up-to-date) "
    fi
done
if [ -n "$DOCKER_PULLS" ]; then
    step_ok "Docker pulls" "$DOCKER_PULLS"
else
    step_ok "Docker pulls" "Aucune image à pull"
fi

# ÉTAPE 3 — OpenClaw + Claude Code
log "--- ÉTAPE 3 : OpenClaw + Claude Code ---"
OC_BEFORE=$(node -p "require('/usr/lib/node_modules/openclaw/package.json').version" 2>/dev/null || echo "unknown")
CC_BEFORE=$(claude --version 2>/dev/null || echo "unknown")

npm install -g openclaw@latest --prefix /usr 2>/dev/null
chmod -R o+rX /usr/lib/node_modules/openclaw/ 2>/dev/null
npm update -g @anthropic-ai/claude-code 2>/dev/null

OC_AFTER=$(node -p "require('/usr/lib/node_modules/openclaw/package.json').version" 2>/dev/null || echo "unknown")
CC_AFTER=$(claude --version 2>/dev/null || echo "unknown")

OC_UPDATED=""
if [ "$OC_BEFORE" != "$OC_AFTER" ]; then
    OC_UPDATED="OpenClaw: $OC_BEFORE → $OC_AFTER "
    systemctl restart openclaw 2>/dev/null || true
fi
if [ "$CC_BEFORE" != "$CC_AFTER" ]; then
    OC_UPDATED+="Claude: $CC_BEFORE → $CC_AFTER"
fi
if [ -z "$OC_UPDATED" ]; then
    step_ok "OpenClaw + Claude" "Déjà à jour (OC:$OC_AFTER CC:$CC_AFTER)"
else
    step_ok "OpenClaw + Claude" "$OC_UPDATED"
fi

# ÉTAPE 4 — Reboot si nécessaire
log "--- ÉTAPE 4 : Reboot check ---"
if [ -f /var/run/reboot-required ]; then
    step_warn "Reboot" "Reboot nécessaire — planifié dans 1 minute"
    send_email
    shutdown -r +1 "Maintenance reboot"
    exit 0
else
    step_ok "Reboot" "Pas de reboot nécessaire"
fi

# ÉTAPE 5 — Sauvegarde
log "--- ÉTAPE 5 : Sauvegarde ---"
rm -rf "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

# Arrêt containers via docker compose
log "Arrêt des containers (docker compose)..."
docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" stop 2>&1 | tail -5
sleep 5

BACKUP_ERRORS=0

# 5.1 Configs (includes security hardening configs)
tar czf "$BACKUP_DIR/configs.tar.gz" \
    /root/maintenance.sh \
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
    2>/dev/null || true

# 5.2 Site Astro
tar czf "$BACKUP_DIR/site-astro.tar.gz" \
    --exclude='node_modules' \
    /opt/bubblestone/src /opt/bubblestone/dist \
    /opt/bubblestone-staging/dist \
    2>/dev/null || true

# 5.3 NPM
tar czf "$BACKUP_DIR/npm.tar.gz" \
    /opt/npm/data /opt/npm/letsencrypt \
    2>/dev/null || true

# 5.4 OpenClaw
tar czf "$BACKUP_DIR/openclaw.tar.gz" \
    --exclude='browser' --exclude='media' \
    /home/pinceouverte/.openclaw \
    2>/dev/null || true

# 5.5 B-roll pipeline
tar czf "$BACKUP_DIR/broll.tar.gz" \
    /home/pinceouverte/clawd/skills/youtube-broll \
    2>/dev/null || true
docker save broll-pipeline 2>/dev/null | gzip > "$BACKUP_DIR/broll-pipeline-image.tar.gz" || true

# 5.6 Container 555
tar czf "$BACKUP_DIR/555-data.tar.gz" \
    /root/data/ \
    /root/src/ai_trend_monitor/ \
    /home/pinceouverte/clawd/podcasts/ \
    2>/dev/null || true
docker save 555 2>/dev/null | gzip > "$BACKUP_DIR/555-image.tar.gz" || true

# 5.7 Audit
tar czf "$BACKUP_DIR/audit-data.tar.gz" \
    /root/data/audits/ \
    2>/dev/null || true
docker save bubblestone-audit 2>/dev/null | gzip > "$BACKUP_DIR/audit-image.tar.gz" || true

# 5.9 LinkedIn Generator
tar czf "$BACKUP_DIR/linkedin-data.tar.gz" \
    /root/data/linkedin/ \
    2>/dev/null || true
docker save linkedin-generator 2>/dev/null | gzip > "$BACKUP_DIR/linkedin-image.tar.gz" || true

# 5.8 Workspace
tar czf "$BACKUP_DIR/workspace.tar.gz" \
    --exclude='.git' --exclude='node_modules' \
    /home/pinceouverte/clawd/ \
    2>/dev/null || true

# Restart containers via docker compose
log "Restart des containers (docker compose)..."
docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" start 2>&1 | tail -5
sleep 10

# Vérifier que tous les containers sont up
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

# Archive finale
ARCHIVE="/tmp/backup-bubblestone-${DATE}.tar.gz"
tar czf "$ARCHIVE" -C "$BACKUP_DIR" . 2>/dev/null || true
ARCHIVE_SIZE=$(du -sh "$ARCHIVE" 2>/dev/null | cut -f1)

# Transfert vers DALMATA
if scp -i "$REMOTE_KEY" -o StrictHostKeyChecking=no "$ARCHIVE" "$REMOTE_HOST:$REMOTE_DIR/" 2>/dev/null; then
    step_ok "Sauvegarde" "Archive ${ARCHIVE_SIZE} transférée vers DALMATA"
    # Rotation 7j sur DALMATA
    ssh -i "$REMOTE_KEY" -o StrictHostKeyChecking=no "$REMOTE_HOST" \
        "find $REMOTE_DIR -name 'backup-bubblestone-*.tar.gz' -mtime +7 -delete" 2>/dev/null || true
else
    step_err "Sauvegarde" "Transfert SCP échoué (archive locale: ${ARCHIVE_SIZE})"
fi

# Cleanup local
rm -rf "$BACKUP_DIR" "$ARCHIVE"

# ÉTAPE 6 — Vérification
log "--- ÉTAPE 6 : Vérification ---"
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
log "--- ÉTAPE 7 : Cleanup ---"
PRUNE_OUTPUT=$(docker image prune -f 2>&1 && docker volume prune -f 2>&1)
SPACE_RECLAIMED=$(echo "$PRUNE_OUTPUT" | grep -i "reclaimed" || echo "rien")

# Rotation logs
find /var/log -name "*.gz" -mtime +30 -delete 2>/dev/null || true
journalctl --vacuum-time=7d 2>/dev/null || true

SPACE_CLEAN=$(echo "$SPACE_RECLAIMED" | grep -oP 'Total reclaimed space: \S+' | head -1 || echo "$SPACE_RECLAIMED")
step_ok "Cleanup" "$SPACE_CLEAN"

# ÉTAPE 8 — Rapport email
log "--- ÉTAPE 8 : Envoi rapport ---"
send_email
if [ $? -eq 0 ]; then
    log "✅ Email envoyé à $EMAIL"
else
    log "❌ Échec envoi email"
fi

log "========== MAINTENANCE $HOSTNAME_SRV END =========="
