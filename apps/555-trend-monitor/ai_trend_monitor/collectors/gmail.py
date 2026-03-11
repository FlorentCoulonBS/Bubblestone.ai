"""Gmail collector - fetches AI newsletters from IMAP folder."""

import email
import email.message
import hashlib
import imaplib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ai_trend_monitor import config
from ai_trend_monitor.collectors import CollectedItem

logger = logging.getLogger(__name__)

GMAIL_FOLDER = "Veille IA"

# Noise patterns to skip (pubs, polls, CTAs, sponsors)
SKIP_URL_PATTERNS = re.compile("|".join([
    r"unsubscribe", r"preferences", r"mailto:", r"google\.com/alerts",
    r"support\.google", r"privacy", r"terms",
    r"facebook\.com", r"twitter\.com/share", r"linkedin\.com/share",
    r"instagram\.com", r"manage.*subscription", r"view.*browser",
    r"click.*here", r"beehiiv\.com/subscribe", r"beehiiv\.com/login",
    r"advertise", r"sponsor", r"workos\.com", r"deel\.com",
    r"onescreen\.ai", r"partner\.com", r"jobs\.ashbyhq",
    r"refer.*friend", r"share.*newsletter",
]), re.IGNORECASE)

SKIP_TITLE_PATTERNS = re.compile("|".join([
    r"^advertise", r"^sponsor", r"^get the (free )?report",
    r"^simplify", r"^try .* (free|today)", r"^sign up",
    r"^read more$", r"^learn more$", r"^click here",
    r"^subscribe", r"^share", r"^refer",
    r"^\U0001f43e",  # paw emoji ratings from The Neuron
    r"^yes please", r"^no[;,]", r"^\(wildcard\)",
    r"^sure, but", r"like a hit of", r"good, not great",
]), re.IGNORECASE)

# Minimum title length to filter out fragments
MIN_TITLE_LEN = 20

# Known newsletter-specific parsers
NEWSLETTER_PARSERS = {
    "beehiiv": "_parse_beehiiv",  # The Neuron, TLDR, etc.
    "deeplearning.ai": "_parse_deeplearning",  # The Batch
    "googlealerts": "_parse_google_alerts",
}


def _decode_subject(msg):
    raw = msg.get("Subject", "")
    parts = decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _unwrap_google_url(href):
    parsed = urlparse(href)
    if "google.com/url" in href:
        qs = parse_qs(parsed.query)
        real = qs.get("url") or qs.get("q")
        if real:
            return real[0]
    return href


def _unwrap_beehiiv_url(href):
    """Unwrap beehiiv tracking redirects."""
    if "beehiiv.com" in href:
        parsed = urlparse(href)
        # beehiiv redirects contain the real URL in various params
        qs = parse_qs(parsed.query)
        for key in ["url", "u", "redirect"]:
            if key in qs:
                return qs[key][0]
    return href


def _is_noise(url, title):
    """Check if a link is noise (ad, poll, CTA, sponsor)."""
    if SKIP_URL_PATTERNS.search(url):
        return True
    if SKIP_TITLE_PATTERNS.search(title):
        return True
    if len(title) < MIN_TITLE_LEN:
        return True
    # Skip pure emoji titles
    if re.match(r'^[\U0001f000-\U0001ffff\s]+$', title):
        return True
    return False


def _is_non_latin(title):
    """Reject titles with >30% non-Latin characters (CJK, Arabic, Cyrillic, etc.).
    Keeps French (accents), English, and other Latin-based languages."""
    if not title:
        return True
    # Count characters that are NOT Latin, digits, punctuation, or whitespace
    non_latin = 0
    total = 0
    for ch in title:
        if ch.isalpha():
            total += 1
            cp = ord(ch)
            # Latin + Latin Extended + Latin Supplement (covers FR accents)
            if not (0x0041 <= cp <= 0x024F):
                non_latin += 1
    if total == 0:
        return True
    return (non_latin / total) > 0.3


def _parse_beehiiv(html, subject):
    """Parse beehiiv newsletters (The Neuron, TLDR AI, etc.)
    Strategy: look for links inside article content blocks, skip sidebar/footer."""
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href:
            continue

        url = _unwrap_beehiiv_url(_unwrap_google_url(href))
        title = a_tag.get_text(strip=True)

        if not title or not url.startswith("http"):
            continue
        if _is_noise(url, title):
            continue
        # Skip beehiiv internal links (polls, tracking pixels)
        if "beehiiv.com" in url and "/p/" not in url:
            continue

        links.append((url, title))

    return links


def _parse_google_alerts(html, subject):
    """Parse Google Alerts emails - extract article links."""
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href:
            continue

        url = _unwrap_google_url(href)
        title = a_tag.get_text(strip=True)

        if not title or not url.startswith("http"):
            continue
        if _is_noise(url, title):
            continue
        # Skip Google's own links
        if "google.com" in url and "news" not in url:
            continue
        # Google Alerts flag as irrelevant link
        if "flag as irrelevant" in title.lower():
            continue

        links.append((url, title))

    return links


def _parse_deeplearning(html, subject):
    """Parse DeepLearning.AI's The Batch newsletter."""
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href:
            continue

        url = _unwrap_google_url(href)
        title = a_tag.get_text(strip=True)

        if not title or not url.startswith("http"):
            continue
        if _is_noise(url, title):
            continue

        links.append((url, title))

    return links


def _parse_generic(html, subject):
    """Generic newsletter parser with improved noise filtering."""
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href:
            continue

        url = _unwrap_google_url(href)
        title = a_tag.get_text(strip=True)

        if not title or not url.startswith("http"):
            continue
        if _is_noise(url, title):
            continue

        links.append((url, title))

    return links


def _detect_newsletter_type(sender, subject):
    """Detect newsletter type from sender/subject."""
    sender_lower = (sender or "").lower()
    if "beehiiv" in sender_lower or "theneuron" in sender_lower or "tldr" in sender_lower:
        return "beehiiv"
    if "deeplearning.ai" in sender_lower or "the batch" in subject.lower():
        return "deeplearning.ai"
    if "googlealerts" in sender_lower:
        return "googlealerts"
    return "generic"


def collect_gmail():
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        logger.warning("Gmail not configured, skipping")
        return []

    items = []
    conn = None

    try:
        logger.info("Connecting to %s as %s", config.GMAIL_HOST, config.GMAIL_USER)
        conn = imaplib.IMAP4_SSL(config.GMAIL_HOST)
        conn.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)

        status, _ = conn.select(f'"{GMAIL_FOLDER}"')
        if status != "OK":
            logger.error("Failed to select folder '%s'", GMAIL_FOLDER)
            conn.logout()
            return []

        status, msg_ids = conn.search(None, "UNSEEN")
        if status != "OK" or not msg_ids[0]:
            logger.info("No new emails in '%s' folder", GMAIL_FOLDER)
            conn.logout()
            return []

        id_list = msg_ids[0].split()
        logger.info("Found %d unread email(s) in '%s'", len(id_list), GMAIL_FOLDER)

        for msg_id in id_list:
            status, data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not data[0]:
                continue

            msg = email.message_from_bytes(data[0][1])
            message_id = msg.get("Message-ID", str(msg_id))
            subject = _decode_subject(msg)
            sender = msg.get("From", "unknown")

            try:
                published = parsedate_to_datetime(msg.get("Date", ""))
            except Exception:
                published = datetime.now(timezone.utc)

            html_body = None
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html_body = payload.decode(charset, errors="replace")
                        break

            if not html_body:
                continue

            # Detect newsletter type and use specific parser
            nl_type = _detect_newsletter_type(sender, subject)
            if nl_type == "beehiiv":
                links = _parse_beehiiv(html_body, subject)
            elif nl_type == "googlealerts":
                links = _parse_google_alerts(html_body, subject)
            elif nl_type == "deeplearning.ai":
                links = _parse_deeplearning(html_body, subject)
            else:
                links = _parse_generic(html_body, subject)

            logger.info("Extracted %d link(s) from '%s' [%s] (%s)",
                       len(links), subject, nl_type, sender)

            for url, title in links:
                link_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                items.append(
                    CollectedItem(
                        source="gmail",
                        source_id=f"{message_id}:{link_hash}",
                        title=title,
                        url=url,
                        published_at=published,
                        metadata={
                            "email_subject": subject,
                            "sender": sender,
                            "newsletter_type": nl_type,
                        },
                    )
                )

            conn.store(msg_id, "+FLAGS", "\\Seen")

        conn.logout()

    except imaplib.IMAP4.error as exc:
        logger.error("IMAP error: %s", exc)
        if conn:
            try: conn.logout()
            except: pass
    except Exception as exc:
        logger.error("Gmail collector error: %s", exc)
        if conn:
            try: conn.logout()
            except: pass

    logger.info("Gmail collector returned %d item(s)", len(items))
    return items
