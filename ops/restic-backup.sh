#!/usr/bin/env bash
# Restic differential backup for BubbleStone.
# Source of truth: ops/restic-backup.sh in the BubbleStone repo.
# Deployed to /opt/bubblestone-ops/restic-backup.sh.
set -euo pipefail

REPO_LOCAL="/opt/bubblestone-restic"
REPO_MIRROR="sftp:backup@69.62.106.57:restic/bubblestone"
SFTP_KEY="/root/.ssh/id_ed25519_backup"
SFTP_OPT_ARGS="-i ${SFTP_KEY} -o BatchMode=yes"
PASSWORD_FILE="/root/.config/restic/password"
STAGING="/tmp/restic-staging-bubblestone-$$"
LOG_PREFIX="[restic-backup]"
TS_START=$(date +%s)

cleanup() { rm -rf "$STAGING"; }
trap cleanup EXIT

mkdir -p "$STAGING"
chmod 700 "$STAGING"

# 1. SQLite NPM cold copy via .backup
sqlite3 /opt/bubblestone-core/data/database.sqlite ".backup ${STAGING}/npm.sqlite"

export RESTIC_PASSWORD_FILE="$PASSWORD_FILE"

# 2. Backup local
restic -r "$REPO_LOCAL" unlock --remove-all >/dev/null 2>&1 || true
restic -r "$REPO_LOCAL" backup \
  --tag daily \
  --exclude /opt/bubblestone-backups-incoming \
  --exclude /opt/bubblestone-restic \
  "$STAGING" \
  /opt/bubblestone-555-data \
  /opt/bubblestone-audit-data \
  /opt/bubblestone-linkedin-data \
  /opt/bubblestone-core/data \
  /opt/bubblestone-core/letsencrypt \
  /opt/bubblestone-site-app/dist \
  /opt/bubblestone-staging-app/dist \
  /opt/repos/bubblestone/infra/docker-compose.yml \
  /opt/bubblestone-leximpact/docker-compose.yml \
  /opt/bubblestone-ops \
  /opt/bubblestone-site-app/nginx.conf \
  /opt/bubblestone-staging-app/nginx.conf \
  /etc/msmtprc \
  /etc/lynis/custom.prf \
  /etc/audit/rules.d/audit.rules \
  /etc/crowdsec/acquis.yaml \
  /etc/crowdsec/acquis.d \
  /etc/crowdsec/profiles.yaml \
  /etc/fail2ban/jail.local \
  /etc/ssh/sshd_config.d/01-hardening.conf \
  /etc/ssh/sshd_config.d/90-hardening.conf \
  /etc/profile.d/99-hardening.sh \
  /etc/apt/apt.conf.d/99-check-setuid-integrity \
  /etc/sudoers.d/90-codex-ops \
  /etc/sudoers.d/deploy \
  /etc/cron.d \
  /var/spool/cron/crontabs/root \
  /etc/systemd/system/cron.service.d/hardening.conf \
  /etc/systemd/system/crowdsec.service.d/hardening.conf \
  /etc/systemd/system/crowdsec-firewall-bouncer.service.d/hardening.conf \
  /etc/systemd/system/fail2ban.service.d/hardening.conf \
  /etc/systemd/system/ssh.service.d/hardening.conf \
  /etc/systemd/system/unattended-upgrades.service.d/hardening.conf \
  /etc/systemd/system/weekly-reboot.service \
  /etc/systemd/system/weekly-reboot.timer \
  /usr/local/sbin/check-setuid-integrity.sh \
  /usr/local/sbin/weekly-reboot.sh \
  /usr/local/sbin/bubblestone-deploy

# 3. Forget on local
restic -r "$REPO_LOCAL" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune --quiet

# 4. Copy to mirror
restic -r "$REPO_MIRROR" -o sftp.args="$SFTP_OPT_ARGS" unlock --remove-all >/dev/null 2>&1 || true
restic -r "$REPO_MIRROR" -o sftp.args="$SFTP_OPT_ARGS" \
  copy --from-repo "$REPO_LOCAL" --from-password-file "$PASSWORD_FILE"

# 5. Forget on mirror
restic -r "$REPO_MIRROR" -o sftp.args="$SFTP_OPT_ARGS" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune --quiet

# 6. Weekly rotating check (1/7 of data each day)
DOW=$(date +%u)
restic -r "$REPO_LOCAL" check --read-data-subset="${DOW}/7" --quiet

DURATION=$(( $(date +%s) - TS_START ))
SNAPSHOT_ID=$(restic -r "$REPO_LOCAL" snapshots --json --tag daily | jq -r '.[-1].short_id')
echo "${LOG_PREFIX} OK duration=${DURATION}s snapshot=${SNAPSHOT_ID}"
