"""Pipeline orchestrator: collect from all sources, dedup, score."""

import logging
import time

from ai_trend_monitor import config
from ai_trend_monitor.collectors.reddit import collect_reddit
from ai_trend_monitor.collectors.rss import collect_rss
from ai_trend_monitor.collectors.gmail import collect_gmail
from ai_trend_monitor.collectors.youtube import collect_youtube
from ai_trend_monitor.collectors.hackernews import collect_hackernews
from ai_trend_monitor.database import get_engine, init_db
from ai_trend_monitor.dedup import deduplicate_items
from ai_trend_monitor.health import check_health, record_failure, record_success
from ai_trend_monitor.models import Topic
from ai_trend_monitor.scorer import score_topics

from sqlmodel import Session, select

logger = logging.getLogger(__name__)


def run_pipeline() -> dict:
    """Run the full multi-source pipeline: collect -> dedup -> score.

    Each collector runs independently with health tracking.
    Failed collectors do not stop others from running.

    Returns:
        Dict with topics, per-source counts, and health status.
    """
    init_db()
    all_items = []
    source_counts: dict[str, int] = {"reddit": 0, "rss": 0, "gmail": 0, "youtube": 0, "hackernews": 0}

    # Step 1: Run each collector with health tracking
    t0 = time.monotonic()

    # Reddit
    try:
        t1 = time.monotonic()
        reddit_items = collect_reddit()
        source_counts["reddit"] = len(reddit_items)
        all_items.extend(reddit_items)
        record_success("reddit", len(reddit_items))
        logger.info("Reddit: %d items in %.1fs", len(reddit_items), time.monotonic() - t1)
    except Exception as e:
        record_failure("reddit", str(e))
        logger.exception("Reddit collector failed")

    # RSS
    try:
        t1 = time.monotonic()
        rss_items = collect_rss()
        source_counts["rss"] = len(rss_items)
        all_items.extend(rss_items)
        record_success("rss", len(rss_items))
        logger.info("RSS: %d items in %.1fs", len(rss_items), time.monotonic() - t1)
    except Exception as e:
        record_failure("rss", str(e))
        logger.exception("RSS collector failed")

    # Gmail
    try:
        t1 = time.monotonic()
        gmail_items = collect_gmail()
        source_counts["gmail"] = len(gmail_items)
        all_items.extend(gmail_items)
        record_success("gmail", len(gmail_items))
        logger.info("Gmail: %d items in %.1fs", len(gmail_items), time.monotonic() - t1)
    except Exception as e:
        record_failure("gmail", str(e))
        logger.exception("Gmail collector failed")

    # YouTube
    try:
        t1 = time.monotonic()
        youtube_items = collect_youtube()
        source_counts["youtube"] = len(youtube_items)
        all_items.extend(youtube_items)
        record_success("youtube", len(youtube_items))
        logger.info("YouTube: %d items in %.1fs", len(youtube_items), time.monotonic() - t1)
    except Exception as e:
        record_failure("youtube", str(e))
        logger.exception("YouTube collector failed")

    # Hacker News
    try:
        t1 = time.monotonic()
        hn_items = collect_hackernews()
        source_counts["hackernews"] = len(hn_items)
        all_items.extend(hn_items)
        record_success("hackernews", len(hn_items))
        logger.info("HN: %d items in %.1fs", len(hn_items), time.monotonic() - t1)
    except Exception as e:
        record_failure("hackernews", str(e))
        logger.exception("Hacker News collector failed")

    logger.info(
        "Collection complete: %d total items in %.1fs",
        len(all_items), time.monotonic() - t0,
    )

    # Step 2: Cross-source deduplication
    try:
        t1 = time.monotonic()
        dedup_result = deduplicate_items(all_items)
        topics_created = dedup_result["created"]
        topics_updated = dedup_result["updated"]
        logger.info(
            "Dedup: %d created, %d updated in %.1fs",
            topics_created, topics_updated, time.monotonic() - t1,
        )
    except Exception:
        logger.exception("Error during deduplication")
        topics_created = 0
        topics_updated = 0

    # Step 3: Score all topics
    try:
        t1 = time.monotonic()
        score_topics()
        logger.info("Scoring complete in %.1fs", time.monotonic() - t1)
    except Exception:
        logger.exception("Error during scoring")

    engine = get_engine()

    # Step 3.5: Notify high-score topics
    try:
        from ai_trend_monitor.notifications import notify_high_score_topics
        notify_high_score_topics()
    except Exception:
        logger.exception("Error during high-score notifications")

    # Step 3.6: Store embeddings for topics missing them
    try:
        from ai_trend_monitor.embeddings import get_model
        import numpy as np

        model = get_model()
        with Session(engine) as session:
            stmt = select(Topic).where(Topic.embedding.is_(None))  # type: ignore[union-attr]
            topics_no_emb = session.exec(stmt).all()
            if topics_no_emb:
                titles = [t.title for t in topics_no_emb]
                embs = model.encode(titles, normalize_embeddings=True)
                for topic_obj, emb in zip(topics_no_emb, embs):
                    topic_obj.embedding = np.array(emb, dtype=np.float32).tobytes()
                    session.add(topic_obj)
                session.commit()
                logger.info("Stored embeddings for %d topics", len(topics_no_emb))
    except Exception:
        logger.exception("Error storing embeddings (non-fatal)")

    # Step 4: Fetch scored topics
    with Session(engine) as session:
        topics = session.exec(
            select(Topic).order_by(Topic.score.desc())  # type: ignore[attr-defined]
        ).all()
        topics = list(topics)

    total_time = time.monotonic() - t0
    logger.info("Pipeline complete: %d topics in %.1fs", len(topics), total_time)

    return {
        "topics": topics,
        "sources": source_counts,
        "topics_created": topics_created,
        "topics_updated": topics_updated,
        "total_items": len(all_items),
        "health": check_health(),
        "duration": round(total_time, 1),
    }
