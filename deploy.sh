#!/usr/bin/env bash
set -euo pipefail

# deploy.sh — Commit and push to trigger CI/CD pipeline
# Usage: ./deploy.sh "description du changement"
#
# Flow:
#   1. git add + commit + push origin master
#   2. GitHub Actions builds and deploys to staging (auto)
#   3. Verify on staging.bubblestone.ai
#   4. Trigger "production" manually from GitHub Actions

BRANCH="master"
REMOTE="origin"

# -- Validate commit message ------------------------------------------------
if [ $# -eq 0 ] || [ -z "${1:-}" ]; then
  echo "Usage: ./deploy.sh \"description du changement\""
  exit 1
fi

MSG="$1"

# -- Pre-flight checks ------------------------------------------------------
if ! git diff --cached --quiet 2>/dev/null && [ -z "$(git diff --cached --name-only)" ]; then
  true  # nothing staged, that's fine — we'll stage below
fi

# Check for changes (staged + unstaged + untracked)
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo "Rien à déployer — aucun changement détecté."
  exit 0
fi

# -- Stage, commit, push ----------------------------------------------------
echo "==> Staging des fichiers modifiés..."
git add -A

echo "==> Commit : $MSG"
git commit -m "$MSG"

echo "==> Push vers $REMOTE/$BRANCH..."
git push "$REMOTE" "$BRANCH"

echo ""
echo "Déploiement lancé !"
echo "  → GitHub Actions va builder et déployer sur staging"
echo "  → Vérifier sur : https://staging.bubblestone.ai"
echo "  → Pour la prod  : déclencher manuellement depuis GitHub Actions"
