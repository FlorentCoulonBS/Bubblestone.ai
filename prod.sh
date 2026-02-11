#!/usr/bin/env bash
set -euo pipefail

# prod.sh — Déclenche le déploiement en production via GitHub Actions
# Prérequis : le code doit déjà être pushé et validé en staging

REPO="FlorentCoulonBS/Bubblestone.ai"
WORKFLOW_ID="deploy.yml"
BRANCH="master"
TOKEN_FILE="$HOME/.github_token_bubblestone"

# -- Charger le token -------------------------------------------------------
if [ ! -f "$TOKEN_FILE" ]; then
  echo "Token GitHub introuvable dans $TOKEN_FILE"
  echo "Lance : echo 'ghp_xxx' > $TOKEN_FILE && chmod 600 $TOKEN_FILE"
  exit 1
fi

GH_TOKEN=$(cat "$TOKEN_FILE")
export GH_TOKEN

# -- Déclencher le workflow production --------------------------------------
echo "==> Déclenchement du déploiement PRODUCTION..."

HTTP_CODE=$(curl -s -o /tmp/gh_response.json -w "%{http_code}" \
  -X POST \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW_ID/dispatches" \
  -d "{\"ref\":\"$BRANCH\",\"inputs\":{\"target\":\"production\"}}")

if [ "$HTTP_CODE" = "204" ]; then
  echo ""
  echo "Déploiement PRODUCTION lancé !"
  echo "  → Suivre le run : https://github.com/$REPO/actions"
  echo "  → Site prod     : https://bubblestone.ai"
else
  echo "Erreur HTTP $HTTP_CODE :"
  cat /tmp/gh_response.json
  exit 1
fi
