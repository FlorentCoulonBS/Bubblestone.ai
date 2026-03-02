"""HTML email digest generation and sending via msmtp."""

import logging
import subprocess
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from sqlmodel import select

from ai_trend_monitor import config
from ai_trend_monitor.database import get_session, init_db
from ai_trend_monitor.models import Topic

logger = logging.getLogger(__name__)

PARIS = ZoneInfo(config.DIGEST_TIMEZONE)


def generate_digest() -> tuple[str, str]:
    """Generate HTML email digest of top 10 topics from last 24 hours.

    Returns:
        (subject, html_body) tuple.
    """
    init_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    session_gen = get_session()
    session = next(session_gen)
    try:
        stmt = (
            select(Topic)
            .where(Topic.last_seen >= cutoff)
            .where(Topic.dismissed_at.is_(None))  # type: ignore[union-attr]
            .order_by(Topic.score.desc())  # type: ignore[union-attr]
            .limit(10)
        )
        topics = session.exec(stmt).all()
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass

    now_paris = datetime.now(PARIS)
    date_str = now_paris.strftime("%d %b %Y")
    subject = f"AI Trend Digest - {date_str}"

    # Highlights (score >= 8)
    highlights = [t for t in topics if t.score >= 8.0]

    dashboard_url = config.DASHBOARD_URL

    # Build HTML
    rows_html = ""
    for i, t in enumerate(topics, 1):
        link = f"{dashboard_url}/topic/{t.id}" if t.id else "#"
        score_color = "#22c55e" if t.score >= 8 else "#eab308" if t.score >= 5 else "#6b7280"
        rows_html += (
            f'<tr style="border-bottom:1px solid #e5e7eb;">'
            f'<td style="padding:8px;text-align:right;color:{score_color};font-weight:bold;">{t.score:.1f}</td>'
            f'<td style="padding:8px;"><a href="{link}" style="color:#2563eb;text-decoration:none;">{_esc(t.title)}</a></td>'
            f'<td style="padding:8px;text-align:right;">{t.sources or "reddit"}</td>'
            f"</tr>"
        )

    highlights_html = ""
    if highlights:
        items = "".join(
            f'<li style="margin-bottom:4px;"><strong>{h.score:.1f}</strong> - {_esc(h.title)}</li>'
            for h in highlights
        )
        highlights_html = (
            f'<div style="background:#fef9c3;border-left:4px solid #eab308;padding:12px;margin-bottom:20px;">'
            f"<strong>Highlights (score 8+)</strong>"
            f"<ul style=\"margin:8px 0 0 0;padding-left:20px;\">{items}</ul>"
            f"</div>"
        )

    html = (
        f'<div style="font-family:sans-serif;max-width:640px;margin:0 auto;">'
        f'<h1 style="color:#1e293b;font-size:20px;">AI Trend Digest</h1>'
        f'<p style="color:#64748b;">{date_str} | Top topics from the last 24 hours</p>'
        f"{highlights_html}"
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<tr style="background:#f1f5f9;">'
        f'<th style="padding:8px;text-align:right;width:60px;">Score</th>'
        f'<th style="padding:8px;text-align:left;">Topic</th>'
        f'<th style="padding:8px;text-align:right;width:80px;">Sources</th>'
        f"</tr>"
        f"{rows_html}"
        f"</table>"
        f'<p style="margin-top:20px;color:#94a3b8;font-size:12px;">'
        f'<a href="{dashboard_url}" style="color:#2563eb;">Open Dashboard</a>'
        f"</p>"
        f"</div>"
    )

    return subject, html


def send_digest() -> bool:
    """Generate and send the email digest via msmtp. Never raises."""
    try:
        subject, html = generate_digest()
        recipient = config.ALERT_EMAIL

        msg = MIMEText(html, "html")
        msg["From"] = recipient
        msg["To"] = recipient
        msg["Subject"] = subject

        result = subprocess.run(
            ["msmtp", "-t"],
            input=msg.as_string(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error("msmtp failed (rc=%d): %s", result.returncode, result.stderr.strip())
            return False

        logger.info("Digest sent to %s", recipient)
        return True
    except Exception:
        logger.exception("Failed to send digest")
        return False


def _esc(text: str) -> str:
    """Minimal HTML escaping."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
