# BubbleStone — Deploy scripts

Two scripts implement the GitHub Actions → server deploy path:

- **`deploy-dispatcher`** → installed at `/usr/local/bin/deploy-dispatcher`. SSH `ForceCommand` for the `deploy` user. Whitelists the 5 deploy actions; rejects everything else. Runs as `deploy`.
- **`bubblestone-deploy`** → installed at `/usr/local/sbin/bubblestone-deploy`. Privileged action runner (git pull, docker build, healthcheck). Invoked via `sudo -n` from the dispatcher. Runs as `root`.

The dispatcher exists to keep a single SSH key per workflow with no shell access. The privileged script does the actual work and is locked behind `sudo` rules in `/etc/sudoers.d/deploy`.

## Install on a fresh server

```bash
# 1. Install scripts
sudo install -m 755 -o root -g root ops/deploy/deploy-dispatcher /usr/local/bin/
sudo install -m 755 -o root -g root ops/deploy/bubblestone-deploy /usr/local/sbin/

# 2. Create deploy user (in docker group, no sudo of its own)
sudo useradd -m -s /bin/bash -G docker deploy
sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh

# 3. Sudoers — let deploy run only bubblestone-deploy as root
sudo tee /etc/sudoers.d/deploy >/dev/null <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/local/sbin/bubblestone-deploy
EOF
sudo chmod 440 /etc/sudoers.d/deploy
sudo visudo -c

# 4. Per-workflow authorized_keys entry (one line per GH Actions workflow)
#    Format: command="/usr/local/bin/deploy-dispatcher",restrict <type> <pubkey> <comment>
```

## Allowed actions

The dispatcher routes 5 commands; anything else logs `rejected SSH_ORIGINAL_COMMAND=...` to syslog (`tag=deploy-dispatcher`) and exits 1:

| `SSH_ORIGINAL_COMMAND` | Effect |
|---|---|
| `site-staging` | rsync stdin tar into `/opt/bubblestone-staging-app/dist`, restart `bubblestone-staging`, healthcheck |
| `site-production` | rsync stdin tar into `/opt/bubblestone-site-app/dist`, restart `bubblestone-site`, healthcheck |
| `555` | git pull, build `555:latest`, recreate container, healthcheck |
| `linkedin` | git pull, build `linkedin-generator:latest`, recreate container, healthcheck |
| `audit` | git pull, build `bubblestone-audit:latest`, recreate container, healthcheck |

## Modifying the scripts

The scripts on disk (`/usr/local/bin/deploy-dispatcher`, `/usr/local/sbin/bubblestone-deploy`) are NOT auto-synced from this repo. After merging a PR that touches them, re-run the install commands above on the server, or manually `cp` the new versions in.
