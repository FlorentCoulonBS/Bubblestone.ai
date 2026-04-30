"""Cross-source correlation scoring and official detection."""

import logging

from sqlmodel import Session, select

from ai_trend_monitor import config
from ai_trend_monitor.database import get_engine, init_db
from ai_trend_monitor.models import Post, Topic

logger = logging.getLogger(__name__)

# Score mapping: number of unique sources -> score (0-10)
_SOURCE_SCORE_MAP = {0: 0, 1: 0, 2: 5, 3: 8}


def calculate_cross_source_score(topic: Topic) -> float:
    """Score a topic based on how many unique sources it appears in.

    Returns 0-10 score: 0 for 1 source, 5 for 2, 8 for 3, 10 for 4+.
    """
    sources = [s.strip() for s in topic.sources.split(",") if s.strip()]
    unique_count = len(set(sources))
    if unique_count >= 4:
        return 10.0
    return float(_SOURCE_SCORE_MAP.get(unique_count, 0))


def detect_official_source(topic: Topic, session: Session | None = None) -> bool:
    """Check if any post associated with this topic is from an official source.

    Checks Post.author against config.OFFICIAL_SOURCES for rss posts.
    """
    if topic.id is None:
        return False

    if session is not None:
        return _detect_official_source_with_session(topic, session)

    init_db()
    engine = get_engine()

    with Session(engine) as session:
        return _detect_official_source_with_session(topic, session)


def _detect_official_source_with_session(topic: Topic, session: Session) -> bool:
    posts = session.exec(
        select(Post).where(Post.topic_id == topic.id)
    ).all()

    for post in posts:
        source = post.subreddit  # subreddit field doubles as source identifier
        author = getattr(post, "reddit_id", "")  # repurposed field for author

        # For rss posts, check author
        if source == "rss":
            if author in config.OFFICIAL_SOURCES:
                return True
    return False
