#!/bin/bash
sleep 60
EMAIL="florent.coulon@bubblestone.ai"
KERNEL=$(uname -r)
DATE_FR=$(date '+%d/%m/%Y')
ALL_OK=true
DETAILS=""

for c in bubblestone-npm bubblestone-site bubblestone-staging bubblestone-555 bubblestone-audit bubblestone-linkedin-generator; do
  STATUS=$(docker inspect -f '{{.State.Running}}' $c 2>/dev/null)
  if [ "$STATUS" = "true" ]; then
    DETAILS="${DETAILS}Container $c: OK\n"
  else
    DETAILS="${DETAILS}Container $c: DOWN\n"
    ALL_OK=false
  fi
done

for check in \
  "bubblestone.ai|https://bubblestone.ai|200" \
  "staging internal|http://172.18.0.25|200" \
  "audit.bubblestone.ai|https://audit.bubblestone.ai/login|200" \
  "veille.bubblestone.ai|https://veille.bubblestone.ai|200"; do
  LABEL="${check%%|*}"
  REST="${check#*|}"
  URL="${REST%%|*}"
  EXPECTED="${REST##*|}"
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL")
  if [ "$CODE" = "$EXPECTED" ]; then
    DETAILS="${DETAILS}${LABEL}: HTTP ${CODE}\n"
  else
    DETAILS="${DETAILS}${LABEL}: HTTP ${CODE} (expected ${EXPECTED})\n"
    ALL_OK=false
  fi
done

if [ "$ALL_OK" = true ]; then
  SUBJECT="[BubbleStoneAI] Reboot OK - ${DATE_FR}"
  BODY="Reboot automatique effectue avec succes.\n\nKernel: ${KERNEL}\n\n${DETAILS}\nAucune intervention requise."
else
  SUBJECT="[BubbleStoneAI] ERREUR post-reboot - ${DATE_FR}"
  BODY="Problemes detectes apres reboot.\n\nKernel: ${KERNEL}\n\n${DETAILS}\nVerifier manuellement."
fi

printf "To: ${EMAIL}\nFrom: florent.coulon@bubblestone.ai\nSubject: ${SUBJECT}\nContent-Type: text/plain; charset=utf-8\n\n$(echo -e "$BODY")" | msmtp -t

systemctl disable maintenance-post-reboot.service 2>/dev/null
