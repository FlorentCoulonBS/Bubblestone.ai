"""High-score topic notifications via ntfy push."""

import logging
from datetime import datetime, timezone

import requests
from sqlmodel import Session, select

from ai_trend_monitor import config
from ai_trend_monitor.database import get_engine
from ai_trend_monitor.models import Topic

logger = logging.getLogger(__name__)


def _send_topic_ntfy(topic: Topic) -> bool:
    """Send ntfy notification for a single high-score topic. Returns True on success."""
    ntfy_topic = config.NTFY_TOPIC
    if not ntfy_topic:
        logger.warning("NTFY_TOPIC not configured, skipping")
        return False

    title = f"[{topic.score:.0f}/10] {topic.title}"
    message = topic.url or "No URL"
    dashboard_link = f"{config.DASHBOARD_URL}/topic/{topic.id}"

    try:
        resp = requests.post(
            f"https://ntfy.sh/{ntfy_topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "4",
                "Click": dashboard_link,
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("ntfy sent for topic %d: %s", topic.id, topic.title)
        return True
    except Exception:
        logger.exception("Failed to send ntfy for topic %d", topic.id)
        return False


def notify_high_score_topics() -> int:
    """Send ntfy for topics scoring >= threshold that haven't been notified yet.

    Returns count of topics notified.
    """
    engine = get_engine()
    count = 0

    try:
        with Session(engine) as session:
            stmt = select(Topic).where(
                Topic.score >= config.NTFY_HIGH_SCORE_THRESHOLD,  # type: ignore[operator]
                Topic.notified_at.is_(None),  # type: ignore[union-attr]
                Topic.dismissed_at.is_(None),  # type: ignore[union-attr]
            )
            topics = session.exec(stmt).all()

            for topic in topics:
                if _send_topic_ntfy(topic):
                    topic.notified_at = datetime.now(timezone.utc)
                    session.add(topic)
                    session.commit()
                    count += 1

        logger.info("Notified %d high-score topics", count)
    except Exception:
        logger.exception("Error during high-score notifications")

    return count
