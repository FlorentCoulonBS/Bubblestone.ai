# Sofiane — accès restreint pour la migration Hotily → Deviane

**Date :** 2026-05-12
**Serveur :** DalmataWeb (`85.31.236.58`)
**Bénéficiaire :** Sofiane (prestataire externe pilotant la migration Hotily → Deviane)
**Durée :** indéterminée, désactivation manuelle après validation de la migration

## Contexte

Sofiane porte la migration des données Hotily vers Deviane (`audit.dalmatahospitality.com`). Il a préparé des scripts qui doivent tourner côté Dalmata :

1. Dump PostgreSQL de la base Deviane
2. Sync des assets de Hotily vers le bucket R2 `dalmata-audit` via `rclone`
3. Réécriture en base des URLs des photos (UPDATE SQL pointant vers `https://files.dalmatahospitality.com`)
4. Smoke tests

Il a besoin d'un accès direct au serveur DalmataWeb mais doit être strictement isolé du reste du serveur (autres apps, autres bases, autres comptes, NPM, ops, etc.).

## Objectifs

- Permettre à Sofiane d'exécuter ses scripts (`psql`, `pg_dump`, `rclone`) sur la cible Dalmata
- Lui donner accès en lecture aux secrets Deviane nécessaires (`/opt/dalmataweb-deviane/.env.audit`)
- L'empêcher d'accéder à tout le reste : autres `/opt/dalmataweb-*/`, autres containers, NPM, secrets DalmataAI/BubbleStone, sudo, Docker
- Fournir une paire de clés R2 dédiée révocable sans toucher la prod
- Procédure de cleanup claire pour tout démonter post-migration

## Hors-scope

- Pas de comptes Sofiane sur BubbleStone ni DalmataAI
- Pas d'accès au container Deviane lui-même (`audit`), uniquement au Postgres
- Pas de modification du code de l'app Deviane

## Architecture

### Compte Linux `sofiane`

- User : `sofiane`
- Shell : `/bin/bash`
- Home : `/home/sofiane`, perms `750 sofiane:sofiane`
- Groupes : `sofiane` (primary) + `deviane-rw` (nouveau, lecture des `.env*` Deviane)
- **Pas dans** : `sudo`, `docker`, `wheel`, aucun groupe sensible
- Auth : SSH key publique fournie par Sofiane, déposée dans `~sofiane/.ssh/authorized_keys` (`600 sofiane:sofiane`)
- Pas d'expiration auto (`chage -E -1`) — désactivation manuelle après validation

### Groupe `deviane-rw` + permissions fichiers

| Chemin | Owner avant | Owner après | Mode après |
|---|---|---|---|
| `/opt/dalmataweb-deviane/.env` | `root:root 600` | `root:deviane-rw` | `640` |
| `/opt/dalmataweb-deviane/.env.audit` | `root:root 640` | `root:deviane-rw` | `640` |
| `/opt/dalmataweb-deviane/docker-compose.yml` | `root:root 640` | `root:deviane-rw` | `640` |

Le reste de `/opt/dalmataweb-*/` n'est pas modifié. Les autres composes restent `root:root 600/640` → invisibles à Sofiane.

### Exposition Postgres en loopback

Le Postgres Deviane (container `dalmataweb-deviane-db`) tourne aujourd'hui uniquement sur le réseau Docker `dalmataweb-net` (172.20.0.0/16). Aucun port n'est exposé sur l'host.

Modification du compose tracké `infra/dalmataweb-deviane/docker-compose.yml` (repo `Dalmatahospitality`) — ajout sur le service `deviane-db` :

```yaml
ports:
  - "127.0.0.1:5433:5432"
```

- Liaison loopback uniquement → jamais exposé sur internet ni à d'autres machines
- Sofiane se connecte via : `psql -h 127.0.0.1 -p 5433 -U <user> -d <db>` (creds dans `.env.audit`, qu'il peut lire)
- Le port `5433` est libre sur DalmataWeb (vérifié)

### Outils host

À installer si absents (apt) :
- `postgresql-client` (fournit `psql`, `pg_dump`)
- `rclone`
- `jq` (probable utilité pour les scripts Sofiane)

`tar`, `gzip` sont déjà présents.

### Workspace Sofiane

- `/home/sofiane/workspace/` (`700 sofiane:sofiane`)
- Hébergera les scripts uploadés via SFTP, dumps temporaires, configs `rclone`, logs
- Pas de quota strict (à monitorer manuellement)

### Clé R2 dédiée Sofiane

- Création manuelle par Florent dans le dashboard Cloudflare R2
- Type : R2 API token avec permissions `Object Read & Write`
- Scope : bucket `dalmata-audit` uniquement
- Label : `sofiane-migration-2026-05`
- Pas d'expiration auto (révocation manuelle)
- Transmission à Sofiane via canal sécurisé (Bitwarden Send / 1Password share / ProtonMail) — **jamais Slack ni email clair**

### Audit & logs

- SSH login enregistré par auditd (déjà actif sur DalmataWeb)
- `bash_history` standard de `sofiane` (non éphémère par défaut)
- Logs Docker du Postgres : `docker logs dalmataweb-deviane-db` (visible à Florent uniquement, Sofiane n'a pas Docker)

## Flux de données

```
[Sofiane laptop]
   │
   │ ssh sofiane@dalmataweb (port 22)
   ▼
[host DalmataWeb /home/sofiane/workspace/]
   │
   ├─► psql -h 127.0.0.1:5433 ──► [container dalmataweb-deviane-db (Postgres)]
   │     (lecture .env.audit pour creds)                │
   │                                                    │ pg_dump → fichier dans workspace
   │                                                    │
   │                                                    ▼
   │                                          /home/sofiane/workspace/dump_*.sql.gz
   │
   ├─► rclone copy → [Cloudflare R2 dalmata-audit]
   │     (clé API dédiée Sofiane, public URL https://files.dalmatahospitality.com)
   │
   └─► UPDATE SQL via psql → réécriture URLs photos en base
```

## Communication finale à Sofiane (paquet à lui transmettre)

```
Hôte SSH      : ssh sofiane@85.31.236.58
SSH key       : (ajout de ta clé publique requise — envoyer la clé d'abord)
Workspace     : /home/sofiane/workspace/

Postgres Deviane :
  Host : 127.0.0.1
  Port : 5433
  Creds : voir /opt/dalmataweb-deviane/.env.audit (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)
  Exemple : psql -h 127.0.0.1 -p 5433 -U <user> -d <db>

Cloudflare R2 :
  Account ID    : 4808400550c32d442431736efd3ea088
  Bucket        : dalmata-audit
  URL publique  : https://files.dalmatahospitality.com
  Access Key ID : <fourni séparément via canal sécurisé>
  Secret        : <fourni séparément via canal sécurisé>

Outils dispo : psql, pg_dump, rclone, jq, tar, gzip
```

## Procédure de cleanup post-migration

Une fois Florent validé que la migration est bonne :

1. `userdel -r sofiane` (supprime le compte + home + workspace)
2. `groupdel deviane-rw`
3. Restaurer les perms originales : `chgrp root /opt/dalmataweb-deviane/.env*` + `chmod 600 /opt/dalmataweb-deviane/.env` + `chmod 640 .env.audit docker-compose.yml`
4. Retirer le port `127.0.0.1:5433:5432` du compose (PR sur `Dalmatahospitality`) + redeploy `docker compose -p dalmataweb-deviane up -d`
5. Révoquer le token R2 `sofiane-migration-2026-05` dans le dashboard Cloudflare
6. Rotation du `POSTGRES_PASSWORD` Deviane (mise à jour `.env.audit` + restart container) — Sofiane a vu ce mot de passe en clair
7. Vérifier dernier login : `lastlog -u sofiane` (référence pour rapport)

## Risques & mitigations

| Risque | Mitigation |
|---|---|
| Sofiane fuite la `.env.audit` (creds DB prod) | Token R2 dédié → on peut révoquer son accès R2 sans affecter prod. Pour la DB : rotation du `POSTGRES_PASSWORD` au cleanup (étape 6 checklist). |
| Sofiane modifie/casse la base de prod | Aucune mitigation technique (il a UPDATE par design). Backup pg complet avant qu'il commence (`pg_dump` côté ops) → recovery possible. |
| Port 5433 accidentellement exposé sur internet | Liaison `127.0.0.1` explicite dans le compose → impossible sauf erreur de config. UFW deny-by-default sur l'host comme deuxième couche. |
| Compte oublié actif | Pas de mitigation auto. Note Slack/calendrier à Florent pour relire dans 30 jours. |
| Sofiane installe des outils ou laisse des traces | Pas de sudo → installation système impossible. `userdel -r` au cleanup nettoie tout son `$HOME`. |

## Décisions documentées

- **Port forward via compose plutôt que via `socat` ad-hoc** : passe par PR sur `Dalmatahospitality` → trace Git, validation review. Le compose est rollbackable proprement.
- **R2 token dédié plutôt que partage de la clé prod** : permet révocation isolée. Coût = 5 minutes dans le dashboard Cloudflare.
- **Pas d'expiration auto du compte** : choix Florent. Compense par note de relecture manuelle.
- **Postgres exposé en loopback plutôt que via `docker exec`** : éviter de mettre Sofiane dans le groupe `docker` (qui équivaut à root sur l'host).
- **Spec stockée dans le repo `bubblestone`** : repo ops central déjà cloné sur le serveur d'orchestration. Le code (modif compose) lui ira dans `Dalmatahospitality`.

## Plan d'exécution (à dérouler après approbation de la spec)

1. Florent crée le token R2 dédié dans Cloudflare et le stocke
2. Florent demande à Sofiane sa clé publique SSH
3. PR sur `Dalmatahospitality` ajoutant le port forward Postgres + merge + déploiement (CI/CD ou redeploy manuel)
4. Sur DalmataWeb (via `claude-ops`) : création user `sofiane`, groupe `deviane-rw`, ajustement permissions `.env*`, dépôt clé SSH, install outils manquants
5. Smoke test : `ssh sofiane@...` depuis poste Florent + `psql -h 127.0.0.1 -p 5433` qui répond
6. Snapshot (pg_dump) de Deviane prod par Florent (filet de sécurité)
7. Communication à Sofiane (paquet ci-dessus + clés R2 séparément via canal sécurisé)
