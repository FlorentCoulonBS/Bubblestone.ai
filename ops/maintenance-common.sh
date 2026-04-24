#!/bin/bash
# =============================================================================
# MAINTENANCE COMMON LIB — shared helpers for BubbleStone / DalmataAI / DalmataWeb
# Version 1.0 (2026-04-24)
# =============================================================================
# Consumers MUST set before sourcing:
#   HOSTNAME_SRV, IP, EMAIL, LOGFILE, DATE, TIME_START, MAINT_VERSION
# Consumers MAY set:
#   MAINT_EMAIL_FROM        (default: maintenance@bubblestone.ai)
#   MAINT_DISK_WARN_PCT     (default: 80)
#   MAINT_SSH_WARN_24H      (default: 10)

: "${MAINT_EMAIL_FROM:=maintenance@bubblestone.ai}"
: "${MAINT_DISK_WARN_PCT:=80}"
: "${MAINT_SSH_WARN_24H:=10}"

# --- Counters & report state (global; populated by step_* helpers) ---
SUCCESS=0
WARNINGS=0
ERRORS=0
REPORT=""
ROWS=""

# =============================================================================
# Logging & step counters
# =============================================================================
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LOGFILE:-/var/log/maintenance.log}"
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

# =============================================================================
# APT helpers
# =============================================================================
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

# Check dpkg for broken packages, attempt auto-repair.
maintenance_apt_health() {
    log "--- APT health ---"
    local BROKEN_PKGS BROKEN_AFTER
    BROKEN_PKGS=$(dpkg --audit 2>&1 | grep -oP "^ \S+" | tr -d " " | tr "\n" " ")
    if [ -z "$BROKEN_PKGS" ]; then
        step_ok "Santé APT" "Aucun paquet cassé"
        return 0
    fi
    log "Paquets cassés détectés: $BROKEN_PKGS"
    DEBIAN_FRONTEND=noninteractive dpkg --configure -a 2>/dev/null || true
    DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y $BROKEN_PKGS >/dev/null 2>&1
    BROKEN_AFTER=$(dpkg --audit 2>&1 | grep -oP "^ \S+" | tr -d " " | tr "\n" " ")
    if [ -n "$BROKEN_AFTER" ]; then
        step_err "Santé APT" "Paquets toujours cassés: $BROKEN_AFTER"
        return 1
    fi
    step_ok "Santé APT" "Réparé: $BROKEN_PKGS"
}

# Run apt-get update + dist-upgrade with fix-broken retry. Updates rkhunter baseline on success.
maintenance_apt_upgrade() {
    log "--- APT dist-upgrade ---"
    wait_apt_lock || return 1

    local APT_OUTPUT UPGRADE_OUTPUT UPGRADED HELD_COUNT
    APT_OUTPUT=$(apt-get update 2>&1)
    if [ $? -ne 0 ]; then
        log "apt update echoue: $(echo "$APT_OUTPUT" | tail -5)"
        step_err "Mises à jour système" "apt update échoué"
        return 1
    fi
    DEBIAN_FRONTEND=noninteractive dpkg --configure -a 2>/dev/null || true
    HELD_COUNT=$(apt-mark showhold 2>/dev/null | wc -l)

    UPGRADE_OUTPUT=$(DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y 2>&1)
    if [ $? -eq 0 ]; then
        UPGRADED=$(echo "$UPGRADE_OUTPUT" | grep -c "^Inst ") || UPGRADED="0"
        DEBIAN_FRONTEND=noninteractive apt-get autoremove -y >/dev/null 2>&1
        step_ok "Mises à jour système" "${UPGRADED} paquet(s) mis à jour (${HELD_COUNT} held)"
        rkhunter --propupd --quiet 2>/dev/null || true
        log "rkhunter baseline updated"
        return 0
    fi

    # Retry: fix-broken then dist-upgrade
    log "dist-upgrade echoue, tentative fix-broken..."
    DEBIAN_FRONTEND=noninteractive apt --fix-broken install -y >/dev/null 2>&1 || true
    DEBIAN_FRONTEND=noninteractive dpkg --configure -a 2>/dev/null || true
    apt-get update -q >/dev/null 2>&1
    UPGRADE_OUTPUT=$(DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y 2>&1)
    if [ $? -eq 0 ]; then
        UPGRADED=$(echo "$UPGRADE_OUTPUT" | grep -c "^Inst ") || UPGRADED="0"
        DEBIAN_FRONTEND=noninteractive apt-get autoremove -y >/dev/null 2>&1
        step_ok "Mises à jour système" "${UPGRADED} paquet(s) mis à jour (retry)"
        rkhunter --propupd --quiet 2>/dev/null || true
        log "rkhunter baseline updated"
        return 0
    fi
    log "dist-upgrade retry echoue: $(echo "$UPGRADE_OUTPUT" | tail -10)"
    step_err "Mises à jour système" "apt dist-upgrade échoué après retry"
    return 1
}

# Reboot if /var/run/reboot-required exists. On reboot: call $1 (email callback) + shutdown.
# Returns 2 when reboot triggered → caller should exit.
maintenance_reboot_check() {
    local email_callback="${1:-email_send}"
    log "--- Reboot check ---"
    if [ -f /var/run/reboot-required ]; then
        step_warn "Reboot" "Reboot nécessaire — planifié dans 1 minute"
        $email_callback
        shutdown -r +1 "Maintenance reboot"
        return 2
    fi
    step_ok "Reboot" "Pas de reboot nécessaire"
}

# Log rotation + journal vacuum (safe on all 3 servers).
maintenance_cleanup_logs() {
    find /var/log -name "*.gz" -mtime +30 -delete 2>/dev/null || true
    journalctl --vacuum-time=7d 2>/dev/null || true
}

# =============================================================================
# HTML email helpers — append to global $ROWS
# =============================================================================
email_row() {
    ROWS+="<tr><td style='padding:8px 12px;border-bottom:1px solid #eee;width:30px'>$1</td><td style='padding:8px 12px;border-bottom:1px solid #eee'>$2</td></tr>"
}

email_section() {
    ROWS+="<tr><td colspan='2' style='padding:14px 12px 6px;font-weight:700;color:#667eea;border-bottom:2px solid #667eea;font-size:13px;text-transform:uppercase;letter-spacing:1px'>$1</td></tr>"
}

# Section: uptime + weekly-reboot timer + setuid-alert flag
email_section_uptime_reboot() {
    email_section "⏱ Uptime & Reboot"

    local UPTIME_PRETTY BOOT_TIME
    UPTIME_PRETTY=$(uptime -p 2>/dev/null | sed 's/^up //')
    BOOT_TIME=$(uptime -s 2>/dev/null)
    email_row "✅" "Uptime — ${UPTIME_PRETTY:-?} (dernier boot : ${BOOT_TIME:-?})"

    # Next weekly-reboot from systemd timer
    local NEXT_STR NEXT_EPOCH NOW_EPOCH LEFT_SEC LEFT_D LEFT_H
    NEXT_STR=$(systemctl show weekly-reboot.timer -p NextElapseUSecRealtime --value 2>/dev/null)
    if [ -n "$NEXT_STR" ] && [ "$NEXT_STR" != "n/a" ]; then
        NEXT_EPOCH=$(date -d "$NEXT_STR" +%s 2>/dev/null)
        NOW_EPOCH=$(date +%s)
        if [ -n "$NEXT_EPOCH" ] && [ "$NEXT_EPOCH" -gt "$NOW_EPOCH" ]; then
            LEFT_SEC=$(( NEXT_EPOCH - NOW_EPOCH ))
            LEFT_D=$(( LEFT_SEC / 86400 ))
            LEFT_H=$(( (LEFT_SEC % 86400) / 3600 ))
            email_row "🔄" "Prochain reboot auto — ${NEXT_STR} (dans ${LEFT_D}j ${LEFT_H}h)"
        else
            email_row "🔄" "Prochain reboot auto — ${NEXT_STR}"
        fi
    else
        email_row "⚠️" "Prochain reboot auto — timer weekly-reboot non programmé"
    fi

    # setuid-alert flag (safety-net dpkg hook)
    if [ -f /var/lib/setuid-alert ]; then
        email_row "⚠️" "Flag setuid-alert — PRÉSENT — weekly-reboot bloqué"
    else
        email_row "✅" "Flag setuid-alert — aucun"
    fi
}

# Section: disk + docker images
email_section_systeme() {
    email_section "💾 Systeme"
    local DISK_PCT DISK_USED DISK_TOTAL DISK_FREE DOCKER_IMG_SIZE
    DISK_PCT=$(df / | awk 'NR==2 {gsub(/%/,""); print $5}')
    DISK_USED=$(df -h / | awk 'NR==2 {print $3}')
    DISK_TOTAL=$(df -h / | awk 'NR==2 {print $2}')
    DISK_FREE=$(df -h / | awk 'NR==2 {print $4}')
    if [ "${DISK_PCT:-0}" -gt "$MAINT_DISK_WARN_PCT" ] 2>/dev/null; then
        email_row "⚠️" "Disque — ${DISK_PCT}% (${DISK_USED}/${DISK_TOTAL}, libre: ${DISK_FREE})"
    else
        email_row "✅" "Disque — ${DISK_PCT}% (${DISK_USED}/${DISK_TOTAL}, libre: ${DISK_FREE})"
    fi
    DOCKER_IMG_SIZE=$(docker system df --format '{{.Type}}\t{{.Size}}' 2>/dev/null | awk -F'\t' '/Images/{print $2}')
    email_row "✅" "Docker images — ${DOCKER_IMG_SIZE:-?}"
}

# Section: Lynis / rkhunter / CrowdSec / auditd / fail2ban / UFW / SSH failed
# Each metric only emitted if the underlying tool is present — safe on DalmataWeb (no auditd/crowdsec).
email_section_securite() {
    email_section "🛡️ Securite"

    # Lynis
    if [ -f /var/log/lynis-report.dat ]; then
        local LYNIS_SCORE LYNIS_DATE LYNIS_AGE
        LYNIS_SCORE=$(grep -oP 'hardening_index=\K[0-9]+' /var/log/lynis-report.dat 2>/dev/null | tail -1 || echo "?")
        LYNIS_DATE=$(stat -c '%Y' /var/log/lynis-report.dat 2>/dev/null)
        LYNIS_AGE="?"
        [ -n "$LYNIS_DATE" ] && LYNIS_AGE=$(( ($(date +%s) - LYNIS_DATE) / 3600 ))
        if [ "$LYNIS_SCORE" != "?" ] && [ "$LYNIS_SCORE" -ge 70 ] 2>/dev/null; then
            email_row "✅" "Lynis hardening index — ${LYNIS_SCORE}/100 (scan il y a ${LYNIS_AGE}h)"
        else
            email_row "⚠️" "Lynis hardening index — ${LYNIS_SCORE}/100 (scan il y a ${LYNIS_AGE}h)"
        fi
    fi

    # rkhunter
    if [ -f /var/log/rkhunter.log ]; then
        local RKH_WARNINGS
        RKH_WARNINGS=$(grep -c "\[ Warning \]" /var/log/rkhunter.log 2>/dev/null) || RKH_WARNINGS="0"
        if [ "$RKH_WARNINGS" -eq 0 ] 2>/dev/null; then
            email_row "✅" "rkhunter — Aucun warning (dernier scan)"
        else
            email_row "⚠️" "rkhunter — ${RKH_WARNINGS} warning(s) (dernier scan)"
        fi
    fi

    # CrowdSec
    if command -v cscli >/dev/null 2>&1; then
        local CS_DECISIONS
        CS_DECISIONS=$(cscli decisions list -o json 2>/dev/null | jq 'if . == null then 0 else length end' 2>/dev/null || echo "?")
        email_row "✅" "CrowdSec — ${CS_DECISIONS} decision(s) active(s)"
    fi

    # auditd
    if command -v ausearch >/dev/null 2>&1; then
        local AUDIT_EVENTS
        AUDIT_EVENTS=$(ausearch -ts recent 2>/dev/null | grep -c "^type=") || AUDIT_EVENTS="0"
        email_row "✅" "auditd — ${AUDIT_EVENTS} evenement(s) (24h)"
    fi

    # fail2ban
    if command -v fail2ban-client >/dev/null 2>&1; then
        local F2B_BANS
        F2B_BANS=$(fail2ban-client status 2>/dev/null | grep "Jail list" | sed 's/.*://;s/,/\n/g' | while read jail; do
            jail=$(echo "$jail" | xargs)
            [ -n "$jail" ] && fail2ban-client status "$jail" 2>/dev/null | grep "Currently banned" | awk '{print $NF}'
        done | paste -sd+ | bc 2>/dev/null || echo "0")
        [ -z "$F2B_BANS" ] && F2B_BANS="0"
        email_row "✅" "fail2ban — ${F2B_BANS} IP(s) bannie(s)"
    fi

    # UFW
    if command -v ufw >/dev/null 2>&1; then
        local UFW_RULES UFW_PORTS UFW_STATUS
        UFW_STATUS=$(ufw status 2>/dev/null | awk 'NR==1 {print $2}')
        UFW_RULES=$(ufw status 2>/dev/null | grep -c "ALLOW") || UFW_RULES="0"
        UFW_PORTS=$(ufw status 2>/dev/null | grep "ALLOW" | awk '{print $1}' | sort -u | tr '\n' ',' | sed 's/,$//')
        if [ "$UFW_STATUS" = "active" ]; then
            email_row "✅" "Firewall UFW — actif, ${UFW_RULES} regles (${UFW_PORTS})"
        else
            email_row "⚠️" "Firewall UFW — ${UFW_STATUS:-inconnu}"
        fi
    fi

    # SSH failed attempts (24h)
    local SSH_FAILED
    SSH_FAILED=$(journalctl _SYSTEMD_UNIT=ssh.service --since "24 hours ago" 2>/dev/null | grep -c "Failed") || SSH_FAILED="0"
    if [ "$SSH_FAILED" -gt "$MAINT_SSH_WARN_24H" ] 2>/dev/null; then
        email_row "⚠️" "SSH — ${SSH_FAILED} tentatives echouees (24h)"
    else
        email_row "✅" "SSH — ${SSH_FAILED} tentative(s) echouee(s) (24h)"
    fi
}

# =============================================================================
# Email send — wraps $ROWS + $REPORT in HTML layout, pipes to msmtp
# Requires: HOSTNAME_SRV, IP, EMAIL, DATE, TIME_START, MAINT_VERSION (+ counters)
# =============================================================================
email_send() {
    local TIME_END DURATION DURATION_MIN DURATION_SEC
    TIME_END=$(date +%s)
    DURATION=$(( TIME_END - TIME_START ))
    DURATION_MIN=$(( DURATION / 60 ))
    DURATION_SEC=$(( DURATION % 60 ))

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
From: ${MAINT_EMAIL_FROM}
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
<div style="background:#f8f9fa;padding:15px;text-align:center;color:#999;font-size:12px">Email automatique — $HOSTNAME_SRV Maintenance v${MAINT_VERSION:-?}</div>
</div>
</body></html>
EOF
}
