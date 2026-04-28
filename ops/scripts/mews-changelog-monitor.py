#!/usr/bin/env python3
"""
Mews Connector API Changelog Monitor
Checks for new entries, generates plain-language explanations via Claude,
and sends email notifications.
"""

import html
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

URL = "https://docs.mews.com/connector-api/changelog"
STATE_DIR = Path("/opt/bubblestone-ops/scripts/state")
STATE_FILE = STATE_DIR / "mews-changelog.json"
RECIPIENT = "lrousseau@dalmatahospitality.com"  # Laetitia Rousseau
SENDER = "florent.coulon@bubblestone.ai"

CLAUDE_PROMPT = """\
Tu es un expert en hôtellerie et en systèmes PMS (Property Management System), \
spécialisé dans l'API Mews Connector et les outils de BI hôtelière.

On te donne une entrée du changelog de l'API Mews Connector. Cette entrée peut \
contenir PLUSIEURS sujets/changements distincts.

Pour CHAQUE sujet distinct dans l'entrée, génère un bloc structuré ainsi :

### [Titre court et clair du sujet]
[2-4 phrases en français simple expliquant :]
- Ce que ça change concrètement pour un hôtelier ou responsable BI
- L'impact sur les rapports, connecteurs BI, ou opérations quotidiennes
- Si c'est une dépréciation : dire clairement qu'il faudra adapter les connecteurs, \
et donner le niveau d'urgence (immédiat, à planifier, pas d'action requise)

Règles :
- Pas de jargon technique (pas de "endpoint", "enum", "discriminateur", "objet")
- Utiliser des termes métier : paiement, facture, réservation, client, rapport
- Être concret : "Apple Pay, Google Pay, PayPal" plutôt que "moyens de paiement alternatifs"
- Séparer chaque sujet par une ligne vide
- Ne PAS mettre de préambule ni de conclusion générale

Entrée changelog :
{entry}
"""


def fetch_page():
    """Fetch the changelog page and extract text content."""
    req = urllib.request.Request(URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; MewsChangelogMonitor/1.0)"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"</?(h[1-6]|p|div|li|ul|ol|br)[^>]*>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
    return "\n".join(line for line in lines if line)


def extract_entries(text):
    """Extract changelog entries from page text."""
    date_pattern = re.compile(
        r"(?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4}"
        r"|"
        r"\d{1,2}(?:st|nd|rd|th)\s+"
        r"(?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{4}"
    )

    entries = []
    positions = list(date_pattern.finditer(text))

    for i, match in enumerate(positions):
        date_str = match.group()
        start = match.end()
        end = positions[i + 1].start() if i + 1 < len(positions) else start + 2000
        content = text[start:end].strip()
        content = re.sub(r"hashtag\s*", "", content)
        content = content.strip()
        if len(content) > 1500:
            content = content[:1500] + "..."
        entries.append({"date": date_str, "content": content})

    return entries


def generate_explanation(entry_content):
    """Call claude CLI to generate a plain-language explanation."""
    prompt = CLAUDE_PROMPT.format(entry=entry_content)
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", "haiku", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        print(f"  Claude returned code {proc.returncode}: {proc.stderr[:200]}")
    except Exception as e:
        print(f"  Claude error: {e}")
    return None


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"known_dates": [], "content_hash": ""}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def send_email(subject, body_html):
    msg = (
        f"From: {SENDER}\n"
        f"To: {RECIPIENT}\n"
        f"Subject: {subject}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/html; charset=UTF-8\n"
        f"\n{body_html}"
    )
    proc = subprocess.run(
        ["msmtp", RECIPIENT],
        input=msg.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        print(f"ERROR sending email: {proc.stderr.decode()}", file=sys.stderr)
        sys.exit(1)
    print(f"Email sent to {RECIPIENT}")


def markdown_to_html(text):
    """Convert Claude's markdown output to styled HTML blocks."""
    blocks = []
    current_title = ""
    current_body = []

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("### "):
            if current_title or current_body:
                blocks.append((current_title, "\n".join(current_body)))
            current_title = line[4:].strip()
            current_body = []
        elif line:
            current_body.append(line)

    if current_title or current_body:
        blocks.append((current_title, "\n".join(current_body)))

    result = ""
    for title, body in blocks:
        is_deprecation = any(
            w in (title + body).lower()
            for w in ["déprécié", "depreci", "supprimer", "adapter", "obsolète"]
        )
        bg = "#fef2f2" if is_deprecation else "#fef9c3"
        border = "#f59e0b" if is_deprecation else "#2563eb"
        label_color = "#991b1b" if is_deprecation else "#92400e"
        text_color = "#991b1b" if is_deprecation else "#78350f"
        label = "Action requise" if is_deprecation else "Ce que ca signifie pour vous"

        title_html = (
            f'<h3 style="color: {label_color}; margin: 0 0 8px 0; font-size: 15px;">'
            f'{html.escape(title)}</h3>'
            if title
            else ""
        )

        body_html = html.escape(body).replace("\n", "<br>")

        result += f"""
        <div style="background: {bg}; border-left: 4px solid {border};
                    border-radius: 6px; padding: 14px 16px; margin-bottom: 12px;">
            <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
                        color: {label_color}; font-weight: 700; margin-bottom: 6px;">
                {label}
            </div>
            {title_html}
            <p style="margin: 0; color: {text_color}; line-height: 1.6;">{body_html}</p>
        </div>
        """
    return result


def format_email(new_entries):
    entries_html = ""
    for entry in new_entries:
        # Technical details
        content_lines = entry["content"].split("\n")
        content_html = ""
        for line in content_lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith(":"):
                line = line.lstrip(": ")
            content_html += f"<li>{html.escape(line)}</li>\n"

        # Plain-language explanation (structured by topic)
        explanation = entry.get("explanation", "")
        explanation_html = markdown_to_html(explanation) if explanation else ""

        entries_html += f"""
        <div style="margin-bottom: 32px;">
            <h2 style="color: #1e40af; margin: 0 0 14px 0; font-size: 18px;
                        border-bottom: 2px solid #2563eb; padding-bottom: 8px;">
                {html.escape(entry['date'])}
            </h2>
            {explanation_html}
            <details style="margin-top: 10px; cursor: pointer;">
                <summary style="color: #6b7280; font-size: 13px;">
                    Detail technique complet
                </summary>
                <ul style="margin: 8px 0 0 0; padding-left: 20px; color: #6b7280;
                           font-size: 13px; line-height: 1.6;">
                    {content_html}
                </ul>
            </details>
        </div>
        """

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, sans-serif; max-width: 700px;
             margin: 0 auto; padding: 20px; color: #1f2937;">
    <div style="background: #eff6ff; border-radius: 8px; padding: 16px 20px;
                margin-bottom: 24px;">
        <h1 style="margin: 0; font-size: 20px; color: #1e3a5f;">
            Mews Connector API — Nouveautes detectees
        </h1>
        <p style="margin: 8px 0 0 0; font-size: 14px; color: #6b7280;">
            {len(new_entries)} nouvelle(s) entree(s) dans le changelog
        </p>
    </div>

    {entries_html}

    <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb;
                font-size: 13px; color: #9ca3af;">
        <p>Source : <a href="{URL}" style="color: #2563eb;">{URL}</a></p>
        <p>Pensez a verifier l'impact sur nos connecteurs BI.</p>
        <p style="font-style: italic;">— Monitoring automatique DalmataHospitality</p>
    </div>
</body>
</html>
"""


def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Checking Mews changelog...")

    text = fetch_page()
    entries = extract_entries(text)

    if not entries:
        print("WARNING: No entries found — page structure may have changed.")
        sys.exit(1)

    print(f"Found {len(entries)} entries on page. Most recent: {entries[0]['date']}")

    state = load_state()
    known_dates = set(state.get("known_dates", []))

    new_entries = [e for e in entries if e["date"] not in known_dates]

    if force:
        new_entries = entries[:1]
        print("FORCE mode: sending most recent entry as notification")

    if not new_entries:
        print("No new entries detected.")
        return

    print(f"New entries detected: {[e['date'] for e in new_entries]}")

    # Generate plain-language explanations
    for entry in new_entries:
        print(f"  Generating explanation for {entry['date']}...")
        explanation = generate_explanation(entry["content"])
        if explanation:
            entry["explanation"] = explanation
            print(f"    -> {explanation[:80]}...")
        else:
            entry["explanation"] = ""
            print("    -> (no explanation generated)")

    if dry_run:
        print("\nDRY RUN — would send email with:")
        for e in new_entries:
            print(f"  - {e['date']}: {e['content'][:80]}...")
            if e.get("explanation"):
                print(f"    Explication: {e['explanation']}")
        return

    subject = (
        f"[Mews API] {len(new_entries)} nouveaute(s) — {new_entries[0]['date']}"
    )
    body = format_email(new_entries)
    send_email(subject, body)

    all_dates = [e["date"] for e in entries]
    save_state({"known_dates": all_dates, "last_check": datetime.now().isoformat()})
    print("State updated.")


if __name__ == "__main__":
    main()
