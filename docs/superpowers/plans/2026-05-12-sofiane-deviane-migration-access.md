# Sofiane — accès restreint pour la migration Hotily → Deviane — Plan d'exécution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mettre en place un accès SSH restreint pour le prestataire Sofiane sur DalmataWeb, lui permettant d'exécuter `pg_dump` + `rclone` + `psql` sur Deviane sans accès au reste du serveur, puis lui transmettre tout ce qu'il faut pour démarrer.

**Architecture:** User Linux dédié `sofiane` (pas de sudo, pas de docker), groupe `deviane-rw` pour lecture des `.env*` Deviane, port forward Postgres `127.0.0.1:5433` via le compose tracké, paire R2 dédiée révocable.

**Tech Stack:** Linux user mgmt (`useradd`, `groupadd`, `chage`), Docker Compose, GitHub Flow, Cloudflare R2.

**Spec source:** `docs/superpowers/specs/2026-05-12-sofiane-deviane-migration-access-design.md`

**Pré-requis déjà satisfaits :**
- Token Cloudflare R2 `sofiane-migration-2026-05` créé (Florent l'a stocké dans son gestionnaire de mots de passe)
- Spec PR : https://github.com/FlorentCoulonBS/Bubblestone.ai/pull/96

---

## File Structure

| Fichier | Statut | Responsabilité |
|---|---|---|
| `infra/dalmataweb-deviane/docker-compose.yml` (repo `Dalmatahospitality`) | Modify | Ajout du port forward `127.0.0.1:5433:5432` sur le service `deviane-db` |
| `/etc/passwd`, `/etc/group`, `/etc/shadow` (DalmataWeb) | Modify (via `useradd`/`groupadd`) | Création user `sofiane` + groupe `deviane-rw` |
| `/home/sofiane/` (DalmataWeb) | Create | Home + workspace + `.ssh/authorized_keys` |
| `/opt/dalmataweb-deviane/.env`, `.env.audit`, `docker-compose.yml` (DalmataWeb) | Modify (chgrp/chmod) | Ouverture lecture au groupe `deviane-rw` |
| `/opt/dalmataweb-backups/manual/deviane-pre-sofiane-<date>.sql.gz` (DalmataWeb) | Create | Filet de sécurité pg_dump avant intervention |

**Notes d'accès :**
- DalmataWeb = `85.31.236.58`. Toujours via `sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58`. `claude-ops` a `sudo NOPASSWD`.
- Le repo `Dalmatahospitality` est cloné sur DalmataWeb dans `/opt/repos/Dalmatahospitality/` (owner `deploy:deploy`). Operations git via `sudo -u deploy`.

---

## Task 1: Investiguer le mapping `files.dalmatahospitality.com` → R2

**Objectif :** Avant de communiquer l'URL publique à Sofiane (pour la réécriture SQL), confirmer qu'elle pointe bien sur le bucket `dalmata-audit`. Le dashboard Cloudflare montre "no custom domain" sur le bucket, donc soit un proxy NPM, soit un Worker, soit la variable d'env est trompeuse.

**Files:**
- Read: NPM SQLite `/opt/dalmataweb-core/data/database.sqlite` (sur DalmataWeb, attention au piège `advanced_config` documenté dans memory)
- Read: `/opt/dalmataweb-core/data/nginx/proxy_host/*.conf`

- [ ] **Step 1: Vérifier la résolution DNS de `files.dalmatahospitality.com`**

```bash
dig +short files.dalmatahospitality.com
dig +short files.dalmatahospitality.com CNAME
```

Attendu : un enregistrement, vraisemblablement vers Cloudflare ou vers l'IP DalmataWeb.

- [ ] **Step 2: Tester un objet R2 connu via les deux URLs**

D'abord récupérer le nom d'un objet existant dans le bucket via le dashboard Cloudflare R2 (ou `rclone ls` si une clé est dispo localement).

Puis :
```bash
# URL publique configurée dans .env.audit
curl -sI https://files.dalmatahospitality.com/<chemin/objet>
# URL publique r2.dev directe
curl -sI https://pub-17bc12f6e3344e4d954fe2eca5caa2db.r2.dev/<chemin/objet>
```

Attendu : les deux retournent `200 OK`.

Si `files.dalmatahospitality.com` retourne 404 ou redirige ailleurs → l'URL n'est PAS branchée sur ce bucket → bloquer l'étape de réécriture SQL et soulever immédiatement à Florent.

- [ ] **Step 3: Identifier le mécanisme de routage**

```bash
# Sur DalmataWeb
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo grep -ril "files.dalmatahospitality" /opt/dalmataweb-core/data/nginx/ 2>/dev/null'
```

Si trouvé → c'est NPM qui proxy (regarder le `forward_host` du conf trouvé).
Si absent → vérifier si custom domain Cloudflare R2 est attaché sous un autre nom, ou si un Worker fait le routage.

- [ ] **Step 4: Documenter le résultat dans la spec si nécessaire**

Si le routage diffère de ce qu'on suppose, ouvrir un commentaire dans la PR #96 et amender la section "Communication finale à Sofiane".

- [ ] **Step 5: Commit (si amendement)**

```bash
cd /opt/repos/bubblestone
git add docs/superpowers/specs/2026-05-12-sofiane-deviane-migration-access-design.md
git commit -m "docs(spec): clarify files.dalmatahospitality.com routing"
sudo -u codex-ops -H git -C /opt/repos/bubblestone push
```

---

## Task 2: Backup pg_dump complet de Deviane (filet de sécurité)

**Objectif :** Avant que Sofiane touche quoi que ce soit, snapshot complet de la base actuelle. Si un `UPDATE` casse les données, on peut restaurer.

**Files:**
- Create: `/opt/dalmataweb-backups/manual/deviane-pre-sofiane-2026-05-12.sql.gz` (sur DalmataWeb)

- [ ] **Step 1: Vérifier les credentials Postgres dans `.env.audit`**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo grep -E "^POSTGRES_" /opt/dalmataweb-deviane/.env'
```

Attendu : `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (ces vars sont aussi utilisées par le service `deviane-db` du compose). Noter les valeurs en mémoire pour les commandes suivantes.

- [ ] **Step 2: Exécuter le pg_dump via le container**

```bash
DATE=$(date -u +%Y-%m-%dT%H%MZ)
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  "sudo docker exec dalmataweb-deviane-db pg_dump -U <POSTGRES_USER> -d <POSTGRES_DB> --format=plain --no-owner --no-privileges | gzip > /tmp/deviane-pre-sofiane-${DATE}.sql.gz"
```

Remplacer `<POSTGRES_USER>` et `<POSTGRES_DB>` par les valeurs lues à l'étape 1.

- [ ] **Step 3: Déplacer dans le répertoire de backup et vérifier**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  "sudo mv /tmp/deviane-pre-sofiane-${DATE}.sql.gz /opt/dalmataweb-backups/manual/ && sudo ls -lh /opt/dalmataweb-backups/manual/deviane-pre-sofiane-${DATE}.sql.gz && sudo gzip -t /opt/dalmataweb-backups/manual/deviane-pre-sofiane-${DATE}.sql.gz && echo 'gzip OK'"
```

Attendu : taille raisonnable (Mo à dizaine de Mo selon usage), `gzip OK`.

- [ ] **Step 4: Vérifier le contenu du dump (présence du schéma)**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  "sudo zcat /opt/dalmataweb-backups/manual/deviane-pre-sofiane-${DATE}.sql.gz | head -50"
```

Attendu : header pg_dump + `CREATE TABLE` ou `SET` directives. Si vide ou tronqué → recommencer.

---

## Task 3: Demander la clé publique SSH de Sofiane

**Objectif :** On a besoin de sa clé publique SSH avant de pouvoir créer son `authorized_keys`. Bloquer la suite tant qu'on ne l'a pas.

- [ ] **Step 1: Préparer le message pour Sofiane**

Florent envoie à Sofiane :

> Pour créer ton accès SSH sur la cible Dalmata, il me faut ta clé **publique** SSH (jamais la privée).
>
> Sur ton poste : `cat ~/.ssh/id_ed25519.pub` (ou `id_rsa.pub` si tu n'as pas d'ed25519). Copie-colle-moi le contenu.
>
> Format attendu : une ligne commençant par `ssh-ed25519 AAAA...` ou `ssh-rsa AAAA...`.
>
> Si tu n'as pas de clé : `ssh-keygen -t ed25519 -C "sofiane-dalmata-migration"`.

- [ ] **Step 2: Stocker la clé reçue dans un fichier local pour la suite**

À la réception, créer le fichier suivant sur le poste d'orchestration (BubbleStone) :

```bash
mkdir -p /tmp/sofiane-onboarding
chmod 700 /tmp/sofiane-onboarding
cat > /tmp/sofiane-onboarding/sofiane.pub <<'KEY_EOF'
<COLLER ICI LA LIGNE EXACTE DE LA CLÉ PUBLIQUE>
KEY_EOF
chmod 600 /tmp/sofiane-onboarding/sofiane.pub
```

- [ ] **Step 3: Valider le format de la clé**

```bash
ssh-keygen -l -f /tmp/sofiane-onboarding/sofiane.pub
```

Attendu : ligne du type `256 SHA256:... sofiane-dalmata-migration (ED25519)`. Si erreur → clé mal copiée, redemander.

---

## Task 4: PR sur `Dalmatahospitality` — port forward Postgres loopback

**Objectif :** Ajouter `ports: ["127.0.0.1:5433:5432"]` au service `deviane-db` du compose, faire passer par PR.

**Files:**
- Modify: `/opt/repos/Dalmatahospitality/infra/dalmataweb-deviane/docker-compose.yml` (sur DalmataWeb)

- [ ] **Step 1: Préparer la branche**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo -u deploy git -C /opt/repos/Dalmatahospitality fetch origin && sudo -u deploy git -C /opt/repos/Dalmatahospitality checkout main && sudo -u deploy git -C /opt/repos/Dalmatahospitality pull --ff-only && sudo -u deploy git -C /opt/repos/Dalmatahospitality checkout -b feat/deviane-pg-loopback-for-migration'
```

- [ ] **Step 2: Patcher le compose**

Le bloc actuel du service `deviane-db` (référence pour reconnaître le contexte) :

```yaml
  deviane-db:
    image: pgvector/pgvector:pg16
    container_name: dalmataweb-deviane-db
    restart: unless-stopped
    mem_limit: 512m
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      webnet:
        aliases:
          - postgres
```

Insérer une clé `ports:` juste après `mem_limit` :

```yaml
  deviane-db:
    image: pgvector/pgvector:pg16
    container_name: dalmataweb-deviane-db
    restart: unless-stopped
    mem_limit: 512m
    ports:
      - "127.0.0.1:5433:5432"
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
```

Édition via Edit tool (la modif doit se faire dans le repo cloné sur DalmataWeb car c'est lui qui pousse — tunneliser la modif ou faire `Edit` à distance n'est pas natif. Le plus simple : utiliser `sed` côté serveur via `sudo -u deploy`).

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  "sudo -u deploy sed -i '/mem_limit: 512m/a\    ports:\n      - \"127.0.0.1:5433:5432\"' /opt/repos/Dalmatahospitality/infra/dalmataweb-deviane/docker-compose.yml"
```

- [ ] **Step 3: Vérifier le diff**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo -u deploy git -C /opt/repos/Dalmatahospitality diff infra/dalmataweb-deviane/docker-compose.yml'
```

Attendu : 3 lignes ajoutées (`    ports:`, `      - "127.0.0.1:5433:5432"`). Si pas exactement ça → corriger manuellement avant de continuer.

- [ ] **Step 4: Commit + push + PR**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo -u deploy git -C /opt/repos/Dalmatahospitality add infra/dalmataweb-deviane/docker-compose.yml && sudo -u deploy git -C /opt/repos/Dalmatahospitality -c user.email="ops@dalmatahospitality.com" -c user.name="claude-ops" commit -m "feat(deviane): expose Postgres on 127.0.0.1:5433 for Sofiane migration

Loopback-only, never exposed on the internet. Used by the dedicated sofiane
account to run pg_dump/psql for the Hotily->Deviane migration. To be
reverted post-migration per spec 2026-05-12-sofiane-deviane-migration-access-design.md."'
```

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo -u deploy git -C /opt/repos/Dalmatahospitality push -u origin feat/deviane-pg-loopback-for-migration'
```

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  "cd /opt/repos/Dalmatahospitality && sudo -u deploy gh pr create --title 'feat(deviane): expose Postgres on 127.0.0.1:5433 for Sofiane migration' --body 'Loopback-only Postgres exposure for the Hotily→Deviane migration. See spec https://github.com/FlorentCoulonBS/Bubblestone.ai/pull/96. To be reverted via cleanup checklist.'"
```

- [ ] **Step 5: Demander review + merge à Florent**

Présenter la PR à Florent. Attendre son merge.

- [ ] **Step 6: Pull + redeploy après merge**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo -u deploy git -C /opt/repos/Dalmatahospitality checkout main && sudo -u deploy git -C /opt/repos/Dalmatahospitality pull --ff-only && sudo cp /opt/repos/Dalmatahospitality/infra/dalmataweb-deviane/docker-compose.yml /opt/dalmataweb-deviane/docker-compose.yml && sudo docker compose -p dalmataweb-deviane -f /opt/dalmataweb-deviane/docker-compose.yml up -d'
```

Attention : `/opt/dalmataweb-deviane/docker-compose.yml` est la copie de runtime utilisée pour le `up -d`. Le repo est la source de vérité. Vérifier qu'il n'existe pas de pipeline CI/CD qui fait ça automatiquement (cf. `.github/workflows/` dans `Dalmatahospitality`) — si oui, ne pas faire le `cp` manuel et laisser le workflow opérer.

- [ ] **Step 7: Smoke test du port forward**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo ss -tlnp | grep 5433'
```

Attendu : ligne montrant `127.0.0.1:5433` en LISTEN (process `docker-proxy`).

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'PGPASSWORD=$(sudo grep ^POSTGRES_PASSWORD /opt/dalmataweb-deviane/.env | cut -d= -f2) psql -h 127.0.0.1 -p 5433 -U $(sudo grep ^POSTGRES_USER /opt/dalmataweb-deviane/.env | cut -d= -f2) -d $(sudo grep ^POSTGRES_DB /opt/dalmataweb-deviane/.env | cut -d= -f2) -c "SELECT version();"'
```

Attendu : ligne `PostgreSQL 16.x ...`.

```bash
# Vérifier qu'il n'est PAS exposé sur internet
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo ufw status | grep 5433 ; echo "---" ; nc -z -w 2 85.31.236.58 5433 && echo "EXPOSED EXTERNALLY - ALERT" || echo "Not externally accessible (OK)"'
```

Attendu : `Not externally accessible (OK)`.

---

## Task 5: Créer le groupe `deviane-rw` et ajuster les permissions

**Files:**
- Modify: `/etc/group` (DalmataWeb, via `groupadd`)
- Modify: `/opt/dalmataweb-deviane/.env`, `.env.audit`, `docker-compose.yml` (DalmataWeb, via `chgrp`/`chmod`)

- [ ] **Step 1: Créer le groupe**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo groupadd deviane-rw && getent group deviane-rw'
```

Attendu : `deviane-rw:x:<gid>:`

- [ ] **Step 2: Sauvegarder les perms originales (pour le cleanup)**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo stat -c "%n %a %U %G" /opt/dalmataweb-deviane/.env /opt/dalmataweb-deviane/.env.audit /opt/dalmataweb-deviane/docker-compose.yml | sudo tee /opt/dalmataweb-backups/manual/deviane-perms-pre-sofiane.txt'
```

Attendu : 3 lignes mémorisées avec les modes originaux.

- [ ] **Step 3: Appliquer les nouvelles perms**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo chgrp deviane-rw /opt/dalmataweb-deviane/.env /opt/dalmataweb-deviane/.env.audit /opt/dalmataweb-deviane/docker-compose.yml && sudo chmod 640 /opt/dalmataweb-deviane/.env /opt/dalmataweb-deviane/.env.audit /opt/dalmataweb-deviane/docker-compose.yml && sudo ls -la /opt/dalmataweb-deviane/.env*'
```

Attendu : `-rw-r----- 1 root deviane-rw ... .env` (et idem pour les autres).

- [ ] **Step 4: Vérifier que le répertoire `/opt/dalmataweb-deviane/` est traversable**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo stat -c "%n %a" /opt/dalmataweb-deviane/'
```

Si `700` → mettre `750` et `chgrp deviane-rw` sur le répertoire (sinon Sofiane ne peut pas y entrer même avec les perms sur les fichiers) :

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo chgrp deviane-rw /opt/dalmataweb-deviane/ && sudo chmod 750 /opt/dalmataweb-deviane/ && sudo ls -ld /opt/dalmataweb-deviane/'
```

Attendu : `drwxr-x--- root deviane-rw`.

---

## Task 6: Créer le user `sofiane`

**Files:**
- Modify: `/etc/passwd`, `/etc/shadow` (DalmataWeb, via `useradd`)
- Create: `/home/sofiane/`, `/home/sofiane/workspace/`, `/home/sofiane/.ssh/authorized_keys` (DalmataWeb)

- [ ] **Step 1: Créer le user**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo useradd --create-home --shell /bin/bash --groups deviane-rw --comment "Sofiane - Hotily->Deviane migration contractor" sofiane && id sofiane'
```

Attendu : `uid=<n> gid=<n>(sofiane) groups=<n>(sofiane),<gid>(deviane-rw)`.

- [ ] **Step 2: Verrouiller le mot de passe (auth uniquement par clé SSH)**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo passwd -l sofiane && sudo passwd -S sofiane'
```

Attendu : `sofiane L ...` (L = locked).

- [ ] **Step 3: Pas d'expiration auto du compte**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo chage -E -1 sofiane && sudo chage -l sofiane'
```

Attendu : `Account expires : never`.

- [ ] **Step 4: Créer le workspace**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo install -d -o sofiane -g sofiane -m 700 /home/sofiane/workspace && sudo ls -la /home/sofiane/'
```

Attendu : `drwx------ sofiane sofiane workspace`.

---

## Task 7: Déposer la clé SSH publique de Sofiane

**Files:**
- Create: `/home/sofiane/.ssh/authorized_keys` (DalmataWeb)

- [ ] **Step 1: Copier la clé du poste d'orchestration vers DalmataWeb**

```bash
sudo -u codex-ops -H scp -i /home/codex-ops/.ssh/dalmata_key /tmp/sofiane-onboarding/sofiane.pub claude-ops@85.31.236.58:/tmp/sofiane.pub
```

- [ ] **Step 2: Installer la clé au bon endroit avec les bonnes perms**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo install -d -o sofiane -g sofiane -m 700 /home/sofiane/.ssh && sudo install -o sofiane -g sofiane -m 600 /tmp/sofiane.pub /home/sofiane/.ssh/authorized_keys && sudo rm /tmp/sofiane.pub && sudo ls -la /home/sofiane/.ssh/'
```

Attendu : `drwx------ sofiane sofiane .` + `-rw------- sofiane sofiane authorized_keys`.

- [ ] **Step 3: Smoke test SSH login (depuis ton poste)**

À ce stade, demander à Florent de tester depuis son poste local :

```bash
ssh sofiane@85.31.236.58 'whoami && id && pwd'
```

Attendu : `sofiane`, `uid=... groups=...,deviane-rw`, `/home/sofiane`.

---

## Task 8: Installer les outils host (`psql`, `pg_dump`, `rclone`, `jq`)

**Files:** packages système (DalmataWeb)

- [ ] **Step 1: Vérifier ce qui est déjà installé**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'for cmd in psql pg_dump rclone jq tar gzip; do printf "%-10s -> " "$cmd"; command -v "$cmd" || echo MISSING; done'
```

Noter la liste des manquants.

- [ ] **Step 2: Installer les manquants**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'sudo apt update && sudo apt install -y postgresql-client rclone jq'
```

(Si tous présents → skip. Si seulement certains → adapter la liste à la fin.)

- [ ] **Step 3: Vérifier les versions**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  'psql --version && pg_dump --version && rclone version | head -1 && jq --version'
```

Attendu : 4 lignes de version, aucune erreur.

---

## Task 9: Smoke tests bout-en-bout sous l'identité `sofiane`

**Objectif :** Vérifier que sofiane peut faire tout ce qu'il doit faire ET ne peut PAS faire ce qu'il ne doit pas faire. À exécuter depuis ssh `sofiane@...` (donc depuis le poste de Florent).

- [ ] **Step 1: Florent ouvre une session SSH sofiane et exécute les checks "doit marcher"**

```bash
# Depuis le poste de Florent
ssh sofiane@85.31.236.58 << 'EOF'
echo "=== identity ==="
id
echo "=== home ==="
pwd && ls -la
echo "=== read .env.audit ==="
cat /opt/dalmataweb-deviane/.env.audit | head -5
echo "=== psql ==="
PGPASSWORD=$(grep ^POSTGRES_PASSWORD /opt/dalmataweb-deviane/.env | cut -d= -f2) \
  psql -h 127.0.0.1 -p 5433 \
  -U $(grep ^POSTGRES_USER /opt/dalmataweb-deviane/.env | cut -d= -f2) \
  -d $(grep ^POSTGRES_DB /opt/dalmataweb-deviane/.env | cut -d= -f2) \
  -c "SELECT current_database(), current_user;"
echo "=== rclone present ==="
which rclone && rclone version | head -1
echo "=== workspace writable ==="
echo "test" > ~/workspace/test.txt && cat ~/workspace/test.txt && rm ~/workspace/test.txt
EOF
```

Attendu : tout passe sans erreur.

- [ ] **Step 2: Checks "doit PAS marcher"**

```bash
ssh sofiane@85.31.236.58 << 'EOF'
echo "=== sudo (must fail) ==="
sudo -n true 2>&1 || echo "sudo blocked OK"
echo "=== docker (must fail) ==="
docker ps 2>&1 | head -3
echo "=== other compose .env (must fail) ==="
cat /opt/dalmataweb-core/data/.env 2>&1 | head -3
ls /opt/dalmataweb-staging/ 2>&1 | head -3
echo "=== root home (must fail) ==="
ls /root/ 2>&1 | head -3
echo "=== port 5433 from outside (must fail) ==="
EOF
nc -z -w 2 85.31.236.58 5433 && echo "ALERT EXPOSED" || echo "5433 not reachable externally OK"
```

Attendu :
- `sudo blocked OK`
- `docker ps` → `permission denied` ou `Got permission denied while trying to connect`
- Lecture autres `/opt/dalmataweb-*/` → `Permission denied`
- `/root/` → `Permission denied`
- `nc 5433` → `5433 not reachable externally OK`

Si l'un de ces checks échoue (i.e. accorde du droit indu) → bloquer la suite et corriger.

---

## Task 10: Configurer `rclone` pour Sofiane (modèle de config à lui transmettre)

**Objectif :** Lui fournir un template `rclone.conf` prêt à l'emploi pour qu'il puisse `rclone copy ./local/ dalmata-r2:dalmata-audit/destination/` immédiatement.

**Files:**
- Create: `/tmp/sofiane-onboarding/rclone-template.conf` (sur poste d'orchestration, à transmettre à Sofiane)

- [ ] **Step 1: Préparer le template rclone**

```bash
cat > /tmp/sofiane-onboarding/rclone-template.conf <<'EOF'
[dalmata-r2]
type = s3
provider = Cloudflare
access_key_id = <REMPLACER PAR ACCESS_KEY_ID FOURNI SÉPARÉMENT>
secret_access_key = <REMPLACER PAR SECRET_ACCESS_KEY FOURNI SÉPARÉMENT>
endpoint = https://4808400550c32d442431736efd3ea088.r2.cloudflarestorage.com
acl = private
no_check_bucket = true
EOF
chmod 600 /tmp/sofiane-onboarding/rclone-template.conf
cat /tmp/sofiane-onboarding/rclone-template.conf
```

- [ ] **Step 2: Smoke test rclone (côté ops, optionnel — nécessite que Florent fournisse temporairement les creds)**

À ne faire que si Florent veut valider avant de transmettre :

```bash
# Sur poste local de Florent, avec le template ci-dessus rempli
rclone --config /tmp/sofiane-onboarding/rclone-template.conf lsd dalmata-r2:
```

Attendu : ligne(s) listant les buckets accessibles, dont `dalmata-audit`.

---

## Task 11: Communication finale à Sofiane

**Objectif :** Lui transmettre tout ce qu'il faut pour démarrer.

- [ ] **Step 1: Préparer le message principal (canal normal — Slack/email)**

```
Bonjour Sofiane,

Ton accès est prêt. Voici les éléments :

== SSH ==
ssh sofiane@85.31.236.58
(Auth par clé uniquement — la clé publique que tu m'as envoyée est déjà installée.)
Workspace : /home/sofiane/workspace/

== Postgres Deviane ==
Host : 127.0.0.1
Port : 5433
Credentials : disponibles dans /opt/dalmataweb-deviane/.env
              (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)
Exemple : psql -h 127.0.0.1 -p 5433 -U <user> -d <db>

== Cloudflare R2 ==
Account ID    : 4808400550c32d442431736efd3ea088
Bucket        : dalmata-audit
Endpoint S3   : https://4808400550c32d442431736efd3ea088.r2.cloudflarestorage.com
URL publique  : https://files.dalmatahospitality.com (à confirmer après Task 1)
Access Key ID + Secret : envoyés séparément via Bitwarden Send / 1Password share.

Template rclone.conf attaché. Modifie les deux lignes "REMPLACER PAR..." avec
les credentials du canal sécurisé.

== Outils dispo ==
psql, pg_dump, rclone, jq, tar, gzip

== À noter ==
- Pas de sudo, pas d'accès Docker. Si tu as besoin d'un binaire absent, demande-moi.
- Backup pg complet déjà pris : /opt/dalmataweb-backups/manual/deviane-pre-sofiane-*.sql.gz
- Préviens-moi avant le run de la migration définitive sur la base de prod.

Florent
```

Attacher : `/tmp/sofiane-onboarding/rclone-template.conf`.

- [ ] **Step 2: Transmettre les creds R2 via canal sécurisé**

Florent crée :
- Bitwarden Send (ou 1Password share / ProtonMail / Signal) contenant :
  - `R2_ACCESS_KEY_ID=<...>`
  - `R2_SECRET_ACCESS_KEY=<...>`
- Lien envoyé séparément, expiration 24-72h, mot de passe optionnel.
- **Jamais Slack, Teams ou email clair.**

- [ ] **Step 3: Confirmer la réception**

Demander à Sofiane de confirmer qu'il a bien :
- réussi à se connecter en SSH
- accès psql qui répond
- creds R2 reçues et `rclone lsd dalmata-r2:` qui liste `dalmata-audit`

---

## Task 12: Documentation cleanup checklist

**Objectif :** Avant de fermer la mission, s'assurer que la checklist de cleanup est facilement retrouvable et que les éléments à révoquer sont notés.

**Files:**
- Modify: spec PR #96 si besoin de mise à jour finale

- [ ] **Step 1: Créer une note de rappel cleanup dans `/opt/sofiane-onboarding-cleanup.md` sur DalmataWeb**

```bash
sudo -u codex-ops -H ssh -i /home/codex-ops/.ssh/dalmata_key claude-ops@85.31.236.58 \
  "sudo tee /root/sofiane-cleanup-checklist.md > /dev/null <<'EOF'
# Cleanup post-migration Sofiane

À exécuter quand Florent valide que la migration Hotily→Deviane est terminée.

1. userdel -r sofiane
2. groupdel deviane-rw
3. Restaurer perms originales : voir /opt/dalmataweb-backups/manual/deviane-perms-pre-sofiane.txt
4. Retirer le port forward 127.0.0.1:5433:5432 (PR sur Dalmatahospitality, revert PR initiale)
5. Révoquer le token R2 'sofiane-migration-2026-05' dans le dashboard Cloudflare
6. Rotation POSTGRES_PASSWORD Deviane (mise à jour /opt/dalmataweb-deviane/.env + restart container)
7. lastlog -u sofiane (référence rapport)

Spec source : https://github.com/FlorentCoulonBS/Bubblestone.ai/pull/96
EOF"
```

- [ ] **Step 2: Mettre à jour `MEMORY.md` du poste d'orchestration**

Ajouter une entrée dans `/root/.claude/projects/-root/memory/` pour ne pas oublier de fermer cet accès. Voir `using-superpowers` mémoire — type `project`, avec date d'ouverture et action de cleanup à faire après validation de la migration.

---

## Self-Review

**Spec coverage :**
- Compte Linux `sofiane` ✅ Tasks 6-7
- Groupe `deviane-rw` + perms .env* ✅ Task 5
- Port forward Postgres ✅ Task 4
- Outils host ✅ Task 8
- Workspace ✅ Task 6 step 4
- Clé R2 dédiée ✅ déjà fait (pré-requis)
- Audit/logs ✅ implicite (auditd actif)
- Cleanup checklist ✅ Task 12
- Communication finale ✅ Task 11
- Backup pg pré-intervention ✅ Task 2
- Investigation `files.dalmatahospitality.com` ✅ Task 1

**Placeholder scan :**
- `<POSTGRES_USER>`, `<POSTGRES_DB>` dans Task 2 — c'est intentionnel : valeurs lues à l'étape 1, pas un TBD du plan.
- `<COLLER ICI...>` dans Task 3 — intentionnel : input externe (clé Sofiane).
- `<REMPLACER PAR ...>` dans Task 10 — intentionnel : creds du canal sécurisé.
- Aucun TBD/TODO/à compléter générique.

**Type consistency :**
- Service compose `deviane-db`, container `dalmataweb-deviane-db` — cohérent partout.
- Groupe `deviane-rw` — cohérent.
- Port `5433` — cohérent.
- User `sofiane` — cohérent.
- Bucket `dalmata-audit` — cohérent.
