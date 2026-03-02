"""URL exact match, fuzzy title, and semantic embedding deduplication."""

import logging
from datetime import datetime, timedelta, timezone

from rapidfuzz import fuzz
from sqlmodel import Session, select

from ai_trend_monitor import config
from ai_trend_monitor.collectors import CollectedItem
from ai_trend_monitor.database import get_engine, init_db
from ai_trend_monitor.models import Post, Topic

logger = logging.getLogger(__name__)


def deduplicate_posts() -> dict[str, int]:
    """Group unassigned posts into topics by URL and title similarity.

    Backward-compatible Reddit-only dedup using rapidfuzz.

    Returns:
        Dict with "created" and "updated" topic counts.
    """
    init_db()
    engine = get_engine()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.DEDUP_TIME_WINDOW_HOURS)
    created = 0
    updated = 0

    with Session(engine) as session:
        # Get unassigned posts from last 48h
        unassigned = session.exec(
            select(Post).where(
                Post.topic_id == None,  # noqa: E711
                Post.collected_at >= cutoff,
            )
        ).all()

        if not unassigned:
            logger.info("No unassigned posts to deduplicate")
            return {"created": 0, "updated": 0}

        # Get existing topics from last 48h for matching
        existing_topics = session.exec(
            select(Topic).where(Topic.last_seen >= cutoff)
        ).all()

        # Phase 1: Group by URL exact match
        url_groups: dict[str, list[Post]] = {}
        no_url_posts: list[Post] = []

        for post in unassigned:
            # Skip reddit self-post URLs (they're unique per post)
            if post.url and not post.url.startswith("https://www.reddit.com/r/"):
                url_groups.setdefault(post.url, []).append(post)
            else:
                no_url_posts.append(post)

        # Process URL groups
        for url, posts in url_groups.items():
            # Check if existing topic has this URL
            matched_topic = None
            for topic in existing_topics:
                if topic.url == url:
                    matched_topic = topic
                    break

            if matched_topic:
                _update_topic_with_posts(matched_topic, posts)
                updated += 1
            else:
                topic = _create_topic_from_posts(posts)
                session.add(topic)
                session.flush()
                existing_topics.append(topic)
                created += 1

            for post in posts:
                post.topic_id = topic.id if not matched_topic else matched_topic.id
                session.add(post)

        # Phase 2: Fuzzy title matching for remaining posts
        for post in no_url_posts:
            matched_topic = None
            best_score = 0.0

            for topic in existing_topics:
                ratio = fuzz.ratio(post.title.lower(), topic.title.lower()) / 100.0
                if ratio >= config.DEDUP_SIMILARITY_THRESHOLD and ratio > best_score:
                    best_score = ratio
                    matched_topic = topic

            if matched_topic:
                _update_topic_with_posts(matched_topic, [post])
                post.topic_id = matched_topic.id
                session.add(post)
                updated += 1
            else:
                topic = _create_topic_from_posts([post])
                session.add(topic)
                session.flush()
                post.topic_id = topic.id
                session.add(post)
                existing_topics.append(topic)
                created += 1

        session.commit()

    logger.info("Deduplication complete: %d created, %d updated", created, updated)
    return {"created": created, "updated": updated}


def deduplicate_items(items: list[CollectedItem]) -> dict[str, int]:
    """Deduplicate CollectedItem objects from all sources using semantic matching.

    Strategy:
    1. URL exact match - group items sharing the same URL
    2. Semantic match - use embeddings for cross-source title matching
    3. Create new topics for unmatched items

    Returns:
        Dict with "created" and "updated" topic counts.
    """
    if not items:
        return {"created": 0, "updated": 0}

    init_db()
    engine = get_engine()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.DEDUP_TIME_WINDOW_HOURS)
    created = 0
    updated = 0

    with Session(engine) as session:
        # Get existing topics for matching
        existing_topics = session.exec(
            select(Topic).where(Topic.last_seen >= cutoff)
        ).all()

        # Phase 1: URL exact match
        url_groups: dict[str, list[CollectedItem]] = {}
        no_url_items: list[CollectedItem] = []

        for item in items:
            if item.url:
                url_groups.setdefault(item.url, []).append(item)
            else:
                no_url_items.append(item)

        # Process URL groups against existing topics
        for url, group_items in url_groups.items():
            matched_topic = None
            for topic in existing_topics:
                if topic.url == url:
                    matched_topic = topic
                    break

            if matched_topic:
                _update_topic_with_items(matched_topic, group_items)
                updated += 1
            else:
                topic = _create_topic_from_items(group_items)
                session.add(topic)
                session.flush()
                existing_topics.append(topic)
                created += 1

        # Phase 2: Semantic matching for items without URL match
        if no_url_items and existing_topics:
            from ai_trend_monitor.embeddings import find_matching_topics

            new_titles = [item.title for item in no_url_items]
            existing_titles = [t.title for t in existing_topics]

            matches = find_matching_topics(
                new_titles, existing_titles, threshold=config.DEDUP_SIMILARITY_THRESHOLD
            )

            matched_indices = set()
            for new_idx, existing_idx in matches.items():
                topic = existing_topics[existing_idx]
                _update_topic_with_items(topic, [no_url_items[new_idx]])
                matched_indices.add(new_idx)
                updated += 1

            # Create new topics for unmatched items
            for i, item in enumerate(no_url_items):
                if i not in matched_indices:
                    topic = _create_topic_from_items([item])
                    session.add(topic)
                    session.flush()
                    existing_topics.append(topic)
                    created += 1
        elif no_url_items:
            # No existing topics - create all new
            for item in no_url_items:
                topic = _create_topic_from_items([item])
                session.add(topic)
                session.flush()
                existing_topics.append(topic)
                created += 1

        session.commit()

    logger.info(
        "Cross-source dedup complete: %d created, %d updated", created, updated
    )
    return {"created": created, "updated": updated}


def _create_topic_from_posts(posts: list[Post]) -> Topic:
    """Create a new Topic from a list of posts."""
    # Use highest-engagement post as representative
    best = max(posts, key=lambda p: p.upvotes + p.num_comments)
    subreddits = sorted(set(p.subreddit for p in posts))

    return Topic(
        title=best.title,
        url=best.url if best.url and not best.url.startswith("https://www.reddit.com/r/") else None,
        upvotes_total=sum(p.upvotes for p in posts),
        comments_total=sum(p.num_comments for p in posts),
        post_count=len(posts),
        first_seen=min(p.collected_at for p in posts),
        last_seen=max(p.collected_at for p in posts),
        subreddits=",".join(subreddits),
        sources="reddit",
    )


def _update_topic_with_posts(topic: Topic, posts: list[Post]) -> None:
    """Update an existing topic with additional posts."""
    topic.upvotes_total += sum(p.upvotes for p in posts)
    topic.comments_total += sum(p.num_comments for p in posts)
    topic.post_count += len(posts)
    existing_subs = set(topic.subreddits.split(",")) if topic.subreddits else set()
    existing_subs.update(p.subreddit for p in posts)
    existing_subs.discard("")
    topic.subreddits = ",".join(sorted(existing_subs))
    latest = max(p.collected_at for p in posts)
    if latest > topic.last_seen:
        topic.last_seen = latest


def _create_topic_from_items(items: list[CollectedItem]) -> Topic:
    """Create a new Topic from CollectedItem objects."""
    # Use first item as representative (items may come from different sources)
    best = items[0]
    sources = sorted(set(item.source for item in items))
    subreddits = sorted(
        set(
            item.metadata.get("subreddit", "")
            for item in items
            if item.metadata.get("subreddit")
        )
    )

    # Sum engagement metrics from metadata
    upvotes = sum(item.metadata.get("upvotes", 0) for item in items)
    comments = sum(item.metadata.get("num_comments", item.metadata.get("comments", 0)) for item in items)

    return Topic(
        title=best.title,
        url=best.url,
        upvotes_total=upvotes,
        comments_total=comments,
        post_count=len(items),
        first_seen=min(item.published_at for item in items),
        last_seen=max(item.published_at for item in items),
        subreddits=",".join(subreddits),
        sources=",".join(sources),
    )


def _update_topic_with_items(topic: Topic, items: list[CollectedItem]) -> None:
    """Update an existing topic with CollectedItem objects."""
    from sqlalchemy.orm.attributes import flag_modified
    # Add sources
    existing_sources = set(topic.sources.split(",")) if topic.sources else set()
    existing_sources.update(item.source for item in items)
    existing_sources.discard("")
    topic.sources = ",".join(sorted(existing_sources))
    flag_modified(topic, "sources")

    # Add subreddits if any
    existing_subs = set(topic.subreddits.split(",")) if topic.subreddits else set()
    for item in items:
        sub = item.metadata.get("subreddit")
        if sub:
            existing_subs.add(sub)
    existing_subs.discard("")
    topic.subreddits = ",".join(sorted(existing_subs))

    # Aggregate engagement
    topic.upvotes_total += sum(item.metadata.get("upvotes", 0) for item in items)
    topic.comments_total += sum(item.metadata.get("num_comments", item.metadata.get("comments", 0)) for item in items)
    topic.post_count += len(items)

    latest = max(item.published_at for item in items)
    # Normalize to naive UTC for comparison (DB stores naive)
    if latest.tzinfo is not None:
        latest = latest.replace(tzinfo=None)
    if latest > topic.last_seen:
        topic.last_seen = latest
