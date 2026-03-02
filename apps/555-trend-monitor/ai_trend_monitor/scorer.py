"""Relevance scoring with engagement, keyword, cross-source, and official signals."""

import logging
import math

from sqlmodel import Session, select

from ai_trend_monitor import config
from ai_trend_monitor.cross_source import calculate_cross_source_score, detect_official_source
from ai_trend_monitor.database import get_engine, init_db
from ai_trend_monitor.models import Post, Topic
from ai_trend_monitor.velocity import calculate_velocity, record_snapshot

logger = logging.getLogger(__name__)


def score_topics(only_unscored: bool = False) -> list[tuple[str, float]]:
    """Score all topics using weighted multi-signal formula.

    Args:
        only_unscored: If True, only score topics with score == 0.

    Returns:
        List of (title, score) tuples sorted by score descending.
    """
    init_db()
    engine = get_engine()
    results: list[tuple[str, float]] = []

    with Session(engine) as session:
        statement = select(Topic)
        if only_unscored:
            statement = statement.where(Topic.score == 0.0)

        topics = session.exec(statement).all()

        for topic in topics:
            score = _calculate_score(topic, session)

            # Update velocity fields
            velocities = calculate_velocity(topic.id)
            topic.velocity_1h = velocities["velocity_1h"]
            topic.velocity_6h = velocities["velocity_6h"]
            topic.velocity_24h = velocities["velocity_24h"]

            # Update official status
            topic.is_official = detect_official_source(topic)

            # Apply official boost
            if topic.is_official:
                score += config.OFFICIAL_BOOST

            # Clamp to 0-10
            score = max(0.0, min(10.0, round(score, 2)))
            topic.score = score
            session.add(topic)
            results.append((topic.title, score))

        session.commit()

        # Record snapshots for velocity tracking (after commit so IDs are stable)
        for topic in topics:
            source_count = len(
                [s for s in topic.sources.split(",") if s.strip()]
            ) if topic.sources else 0
            record_snapshot(topic.id, topic.post_count, source_count)

    results.sort(key=lambda x: x[1], reverse=True)
    logger.info("Scored %d topics", len(results))
    return results


def _calculate_score(topic: Topic, session: Session) -> float:
    """Calculate relevance score 0-10 for a topic."""
    title_lower = topic.title.lower()

    # --- Engagement (log scale, 0-10) ---
    upvote_score = min(math.log2(max(topic.upvotes_total, 1)) / math.log2(500), 1.0) * 10
    comment_score = min(math.log2(max(topic.comments_total, 1)) / math.log2(100), 1.0) * 10

    # --- Keyword relevance (0-10) ---
    # Check both revolutionary keywords AND AI keywords from collector
    from ai_trend_monitor.collectors.reddit import _AI_PATTERNS
    keyword_score = 0.0
    # Revolutionary keywords = high signal
    rev_count = sum(1 for kw in config.REVOLUTIONARY_KEYWORDS if kw.lower() in title_lower)
    # AI keywords = baseline relevance
    ai_count = sum(1 for pat in _AI_PATTERNS if pat.search(title_lower))
    # Score: any AI keyword = 5, revolutionary = 8-10
    if rev_count >= 2:
        keyword_score = 10.0
    elif rev_count == 1:
        keyword_score = 8.0
    elif ai_count >= 2:
        keyword_score = 6.0
    elif ai_count >= 1:
        keyword_score = 4.0

    # --- Source diversity (0-10) ---
    source_count = len([s for s in topic.sources.split(",") if s.strip()]) if topic.sources else 0
    sub_count = len([s for s in topic.subreddits.split(",") if s]) if topic.subreddits else 0
    # Each source type = 3.3 pts, each subreddit = 1 pt (capped)
    diversity_score = min((source_count * 3.3 + min(sub_count, 3) * 1.0), 10.0)

    # --- Cross-source score (0-10) ---
    cross_source_score = calculate_cross_source_score(topic)

    # --- Official score (binary: 10 or 0) ---
    official_score = 10.0 if detect_official_source(topic) else 0.0

    # Weighted sum
    weights = config.SCORING_WEIGHTS
    score = (
        upvote_score * weights["upvotes"]
        + comment_score * weights["comments"]
        + keyword_score * weights["keywords"]
        + diversity_score * weights["subreddit"]
        + cross_source_score * weights["cross_source"]
        + official_score * weights["official"]
    )

    # Revolutionary keyword boost: +0.5 per match in title+body, capped at +2.0
    text_to_check = [title_lower]
    if topic.id is not None:
        posts = session.exec(
            select(Post).where(Post.topic_id == topic.id)
        ).all()
        for post in posts:
            if post.selftext:
                text_to_check.append(post.selftext.lower())

    matched_keywords: set[str] = set()
    for text in text_to_check:
        for kw in config.REVOLUTIONARY_KEYWORDS:
            if kw.lower() in text:
                matched_keywords.add(kw.lower())

    rev_boost = min(len(matched_keywords) * 0.5, 2.0)
    score += rev_boost

    return score
