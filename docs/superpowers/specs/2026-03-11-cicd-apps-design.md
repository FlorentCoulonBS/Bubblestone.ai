# CI/CD for BubbleStone Apps — Design Spec

**Date:** 2026-03-11
**Scope:** Add CI/CD deployment for 555 (veille), audit-platform, linkedin-generator
**Server:** BubbleStone (72.62.190.147)

## Context

The site (bubblestone.ai) already has CI/CD via `.github/workflows/deploy.yml`:
- Push to `main` with `site/**` changes → auto deploy to staging
- Manual `workflow_dispatch` → deploy to production

The 3 apps have **no CI/CD**. Docker images are built manually on the server.
Additionally, the 555 container bind-mounts `/root/src:/root/src` which means
it runs code from the host filesystem instead of the image — this must be fixed.

## Decision Record

| Decision | Choice | Rationale |
|---|---|---|
| Build location | On-server (option A) | Images are 2-3GB; no bandwidth wasted. Nightly backup already saves images via `docker save` to Dalmata. Full disaster recovery covered. |
| Staging for apps | No | Staging is only for the site (bubblestone.ai / staging.bubblestone.ai). Apps are internal tools, deploy direct to prod. |
| Workflow structure | One workflow per component (option B) | Independent lifecycles. A broken audit build (heavy: Chrome, ZAP) must not block site or other app deploys. |
| Registry (GHCR) | No | Nightly backups save Docker images to Dalmata. Recovery: `docker load` from backup. No added complexity needed. |

## Architecture

```
GitHub repo (Bubblestone.ai)
├── .github/workflows/
│   ├── deploy-site.yml          (existing, renamed from deploy.yml)
│   ├── deploy-555.yml           (new)
│   ├── deploy-audit.yml         (new)
│   └── deploy-linkedin.yml      (new)
├── site/                        → bubblestone.ai + staging.bubblestone.ai
├── apps/
│   ├── 555-trend-monitor/       → veille.bubblestone.ai
│   ├── audit-platform/          → audit.bubblestone.ai
│   └── linkedin-generator/      → linkedin.bubblestone.ai
└── infra/
    └── docker-compose.yml       (updated: remove 555 bind mount)
```

## Workflow Design (per app)

All 3 app workflows follow the same pattern:

### Trigger
```yaml
on:
  push:
    branches: [main]
    paths:
      - 'apps/<app-name>/**'
      - '.github/workflows/deploy-<app>.yml'
```

No `workflow_dispatch` — apps deploy direct to prod on merge to main.

### Steps
1. Install SSH key (from existing `VPS_SSH_KEY` secret)
2. SSH to server:
   a. `cd /opt/repos/bubblestone && git pull origin main`
   b. `docker build -t <image>:latest apps/<app-name>/`
   c. `docker compose -f <compose-file> -p projects up -d <service>`
3. Health check: `curl` the app's local port to verify it responds

### Per-app specifics

| App | Image name | Service name | Build context | Health check |
|---|---|---|---|---|
| 555 | `555:latest` | `555` | `apps/555-trend-monitor/` | `curl -sf http://127.0.0.1:5000/` |
| audit | `bubblestone-audit:latest` | `bubblestone-audit` | `apps/audit-platform/` | `curl -sf http://127.0.0.1:8080/` |
| linkedin | `linkedin-generator:latest` | `linkedin-generator` | `apps/linkedin-generator/` | `curl -sf http://127.0.0.1:5001/` |

## Changes Required

### 1. Rename existing workflow
- `deploy.yml` → `deploy-site.yml`
- No functional change, just naming consistency

### 2. Create 3 new workflows
- `deploy-555.yml`
- `deploy-audit.yml`
- `deploy-linkedin.yml`

### 3. Fix docker-compose.yml
Remove bind mounts from 555 service:
```yaml
# REMOVE these lines:
- /root/data:/root/data
- /root/src:/root/src
- /home/pinceouverte/clawd:/home/pinceouverte/clawd

# KEEP only data volumes:
- /root/data:/data
```

The 555 Dockerfile already copies source into the image at build time.
Data access is via `/data` mount (DATABASE_PATH=/data/trends.db, OPML_PATH=/data/feeds.opml).

### 4. Fix 555 Dockerfile build context
The current Dockerfile expects build context = `apps/555-trend-monitor/`
with source code in `ai_trend_monitor/` subfolder. Verify COPY paths match.

### 5. Update maintenance.sh backup paths
After removing `/root/src` bind mount, the backup step that archives
`/root/src/ai_trend_monitor/` is redundant (code is in Git + Docker image).
Update to remove this path from backup.

## GitHub Secrets (already configured)
- `VPS_SSH_KEY` — base64-encoded SSH deploy key
- `VPS_HOST` — 72.62.190.147
- `VPS_USER` — deploy

No new secrets needed.

## Compose file — single source of truth

**Problem:** Two identical but independent copies of docker-compose exist:
- `/opt/repos/bubblestone/infra/docker-compose.yml` (Git-versioned)
- `/home/pinceouverte/clawd/projects/docker-compose-bubblestoneai.yml` (OpenClaw workspace, no Git remote)

The maintenance script (`maintenance.sh`) and OpenClaw both reference the
second path. This is fragile — changes in one won't propagate to the other.

**Fix:** The Git repo version is the source of truth.
1. Replace OpenClaw's copy with a symlink:
   `ln -sf /opt/repos/bubblestone/infra/docker-compose.yml /home/pinceouverte/clawd/projects/docker-compose-bubblestoneai.yml`
2. Update `maintenance.sh` COMPOSE_FILE to point to the repo:
   `COMPOSE_FILE="/opt/repos/bubblestone/infra/docker-compose.yml"`
3. Both maintenance.sh and CI/CD workflows use the same file from Git.
4. OpenClaw continues to work via the symlink — no disruption.

## OpenClaw disaster recovery

OpenClaw workspace (`/home/pinceouverte/clawd/`) is a local Git repo with
**no remote**. It is backed up nightly as `workspace.tar.gz` to Dalmata.

Current backup coverage for OpenClaw:
- `workspace.tar.gz` — full workspace (excludes .git, node_modules)
- `openclaw.tar.gz` — /home/pinceouverte/.openclaw config
- `broll.tar.gz` + `broll-pipeline-image.tar.gz` — B-roll pipeline

This is adequate: in a disaster scenario, restore from backup covers
OpenClaw's MEMORY.md, SOUL.md, projects, scripts, skills, podcasts, etc.
The docker-compose symlink means that file is always in Git as well.

## Rollback strategy
- Git revert the merge commit → push to main → triggers redeploy with previous code
- Or: `docker compose` restart with previous image (backup from last night)

## Out of scope
- chat.bubblestone.ai (OpenClaw, not in repo)
- loisirs.florentcoulon.cloud (inactive)
- leximpact.bubblestone.ai (stopped, proxy to be disabled manually in NPM)
