"""YouTube collector - fetches recent AI videos via YouTube RSS feeds."""

import logging
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser

from ai_trend_monitor import config
from ai_trend_monitor.collectors import CollectedItem
from ai_trend_monitor.collectors.reddit import is_ai_related

logger = logging.getLogger(__name__)

FETCH_WINDOW_HOURS = 72  # YouTube uploads less frequently, wider window

# YouTube channel IDs for major AI content creators (verified working RSS feeds)
YOUTUBE_CHANNELS: dict[str, str] = {
    # AI educators & reviewers
    "Two Minute Papers": "UCbfYPyITQ-7l4upoX8nvctg",
    "Yannic Kilcher": "UCZHmQk67mSJgfCCTn7xBfew",
    "AI Explained": "UCNJ1Ymd5yFuUPtn21xtRbbw",
    "TheAIGRID": "UCjWY5hREA6FFYrthD0rZNIw",
    "Fireship": "UCsBjURrPoezykLs9EqgamOA",
    "David Shapiro": "UCnMn36GT_H0X-w5_ckLtlgQ",
    "NetworkChuck": "UC9x0AN7BWHpCDHSm9NiJFJQ",
    "Sentdex": "UCfzlCWGWYyIQ0aLC5w48gBQ",
    "3Blue1Brown": "UCYO_jab_esuFRV4b17AJtAw",
    # From OPML feeds
    "AI Jason": "UCrXSVX9a1mj8l0CMLwKgMVw",
    "Alex Finn": "UCPhYkkcCqoZpiPYHxGZ1WQA",
    "All About AI": "UCR9j1jqqB5Rse69wjUnbYwA",
    "Greg Isenberg": "UCPjNBjflYl0-HQtUvOx0Ibw",
    "Matt Wolfe": "UChpleBmo18P08aKCIgti38g",
    "Sam Witteveen": "UC55ODQSvARtgSyc8ThfiepQ",
    "Yassine Sdiri": "UCmmgGrSL0W9D56dQpqXO9mg",
}

# AI-only channels: skip keyword filtering (all content is AI-relevant)
AI_ONLY_CHANNELS = {
    "Two Minute Papers", "Yannic Kilcher", "AI Explained",
    "TheAIGRID", "David Shapiro", "AI Jason", "All About AI",
    "Matt Wolfe", "Sam Witteveen", "Yassine Sdiri",
}


def collect_youtube() -> list[CollectedItem]:
    """Collect recent AI-related videos from YouTube channels via RSS.

    Uses YouTube's public RSS feeds (no API key needed).
    Each channel has a feed at:
    https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID

    Returns:
        List of CollectedItem from YouTube.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FETCH_WINDOW_HOURS)
    items: list[CollectedItem] = []

    channels = {**YOUTUBE_CHANNELS, **getattr(config, "YOUTUBE_CHANNELS", {})}

    logger.info("Fetching %d YouTube channel feeds", len(channels))

    for channel_name, channel_id in channels.items():
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                logger.warning("YouTube feed error for %s: %s", channel_name, feed.bozo_exception)
                continue

            count = 0
            for entry in feed.entries:
                # Parse published date
                if entry.get("published_parsed"):
                    published_at = datetime.fromtimestamp(
                        mktime(entry.published_parsed), tz=timezone.utc
                    )
                else:
                    published_at = datetime.now(timezone.utc)

                if published_at < cutoff:
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", "")

                # AI keyword filter (skip for known AI-only channels)
                if channel_name not in AI_ONLY_CHANNELS:
                    if not is_ai_related(title, summary):
                        continue

                video_url = entry.get("link", "")
                video_id = entry.get("yt_videoid", "")

                items.append(CollectedItem(
                    source="youtube",
                    source_id=f"yt:{video_id}" if video_id else video_url,
                    title=title,
                    body=summary,
                    url=video_url,
                    author=channel_name,
                    published_at=published_at,
                    metadata={
                        "channel_name": channel_name,
                        "channel_id": channel_id,
                        "video_id": video_id,
                    },
                ))
                count += 1

            if count:
                logger.info("YouTube '%s': %d videos", channel_name, count)

        except Exception:
            logger.exception("Error fetching YouTube feed: %s", channel_name)
            continue

    logger.info("YouTube collection complete: %d items from %d channels", len(items), len(channels))
    return items
