#!/bin/bash
sleep 60
EMAIL="florent.coulon@bubblestone.ai"
KERNEL=$(uname -r)
DATE_FR=$(date '+%d/%m/%Y')
ALL_OK=true
DETAILS=""

for c in npm bubblestone-site bubblestone-staging 555 bubblestone-audit; do
  STATUS=$(docker inspect -f '{{.State.Running}}' $c 2>/dev/null)
  if [ "$STATUS" = "true" ]; then
    DETAILS="${DETAILS}Container $c: OK\n"
  else
    DETAILS="${DETAILS}Container $c: DOWN\n"
    ALL_OK=false
  fi
done

for u in https://bubblestone.ai https://staging.bubblestone.ai https://audit.bubblestone.ai/login https://veille.bubblestone.ai; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$u")
  DOMAIN=$(echo "$u" | sed 's|https://||' | cut -d/ -f1)
  if [ "$CODE" = "200" ]; then
    DETAILS="${DETAILS}${DOMAIN}: HTTP 200\n"
  else
    DETAILS="${DETAILS}${DOMAIN}: HTTP ${CODE}\n"
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
