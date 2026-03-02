#!/bin/bash
set -e

URL="${1:?Usage: docker run bubblestone-audit <URL>}"
OUTPUT_DIR="/output"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DOMAIN=$(echo "$URL" | sed 's|https\?://||;s|/.*||;s|www\.||')

mkdir -p "$OUTPUT_DIR"

echo "══════════════════════════════════════════════"
echo "🔍 BubbleStone.ai — Audit complet de $URL"
echo "══════════════════════════════════════════════"
echo ""

# 1. Lighthouse
echo "⚡ [1/5] Lighthouse (Performance, SEO, A11y, Best Practices)..."
lighthouse "$URL" \
  --chrome-flags="--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage" \
  --output=json \
  --output-path="$OUTPUT_DIR/lighthouse.json" \
  --only-categories=performance,seo,accessibility,best-practices \
  --quiet 2>/dev/null || echo "⚠️  Lighthouse a rencontré une erreur (résultats partiels possibles)"

# 2. OWASP ZAP baseline scan
echo "🔒 [2/5] OWASP ZAP Security Scan..."
# ZAP needs DISPLAY for headless mode via xvfb
export DISPLAY=:99
Xvfb :99 -screen 0 1024x768x24 &>/dev/null &
XVFB_PID=$!
sleep 1

# Run ZAP baseline using the installed ZAP
python3 /usr/local/bin/zap-baseline.py \
  -t "$URL" \
  -J "$OUTPUT_DIR/zap.json" \
  -I \
  -d \
  -z "-config api.disablekey=true" \
  2>/dev/null || echo "⚠️  ZAP scan terminé avec avertissements"

kill $XVFB_PID 2>/dev/null || true

# 3. Security headers check
echo "🛡️  [3/5] Analyse des headers de sécurité..."
python3 /app/check_headers.py "$URL" > "$OUTPUT_DIR/headers.json"

# 4. Stack detection
echo "📦 [4/5] Détection de la stack technique..."
python3 /app/detect_stack.py "$URL" > "$OUTPUT_DIR/stack.json"

# 5. Generate report
echo "📄 [5/5] Génération du rapport PDF..."
python3 /app/generate_report.py "$OUTPUT_DIR" "$URL" "$DOMAIN" "$TIMESTAMP"

echo ""
echo "══════════════════════════════════════════════"
echo "✅ Audit terminé !"
echo "📁 Rapport : $OUTPUT_DIR/rapport_${DOMAIN}_${TIMESTAMP}.pdf"
echo "══════════════════════════════════════════════"
