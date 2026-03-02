"""Alert sending via ntfy push notifications and email."""

import logging
import subprocess

import requests

from ai_trend_monitor import config

logger = logging.getLogger(__name__)


def send_ntfy(title: str, message: str, priority: int = 4) -> bool:
    """Send a push notification via ntfy.sh.

    Returns True on success, False on failure or missing config.
    """
    topic = config.NTFY_TOPIC
    if not topic:
        logger.warning("NTFY_TOPIC not configured, skipping ntfy alert")
        return False
    try:
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": str(priority)},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("ntfy alert sent: %s", title)
        return True
    except Exception:
        logger.exception("Failed to send ntfy alert")
        return False


def send_email(subject: str, body: str) -> bool:
    """Send an email alert via msmtp.

    Returns True on success, False on failure or missing config.
    """
    recipient = config.ALERT_EMAIL
    if not recipient:
        logger.warning("ALERT_EMAIL not configured, skipping email alert")
        return False
    try:
        email_content = f"To: {recipient}\nSubject: {subject}\n\n{body}\n"
        result = subprocess.run(
            ["msmtp", recipient],
            input=email_content,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("Email alert sent: %s", subject)
            return True
        else:
            logger.warning("msmtp failed (rc=%d): %s", result.returncode, result.stderr)
            return False
    except FileNotFoundError:
        logger.warning("msmtp not installed, skipping email alert")
        return False
    except Exception:
        logger.exception("Failed to send email alert")
        return False


def send_alert(title: str, message: str) -> None:
    """Send alert via all configured channels. Never raises."""
    try:
        ntfy_ok = send_ntfy(title, message)
        email_ok = send_email(title, message)
        if ntfy_ok or email_ok:
            channels = []
            if ntfy_ok:
                channels.append("ntfy")
            if email_ok:
                channels.append("email")
            logger.info("Alert delivered via: %s", ", ".join(channels))
        else:
            logger.warning("Alert not delivered (no channels configured): %s", title)
    except Exception:
        logger.exception("Unexpected error in send_alert")
