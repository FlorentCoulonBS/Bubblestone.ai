"""RSS/OPML collector - fetches AI-related entries from RSS feeds."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser

from ai_trend_monitor import config
from ai_trend_monitor.collectors import CollectedItem
from ai_trend_monitor.collectors.reddit import is_ai_related

logger = logging.getLogger(__name__)

FETCH_WINDOW_HOURS = 48


def parse_opml(opml_path: str) -> list[str]:
    """Parse OPML file and extract feed URLs.

    Args:
        opml_path: Path to OPML file.

    Returns:
        List of feed URLs found in the OPML file.
        Returns empty list if file is missing or malformed.
    """
    try:
        tree = ET.parse(opml_path)
    except FileNotFoundError:
        logger.warning("OPML file not found: %s", opml_path)
        return []
    except ET.ParseError:
        logger.warning("OPML file is malformed: %s", opml_path)
        return []

    root = tree.getroot()
    urls = []
    for outline in root.iter("outline"):
        xml_url = outline.get("xmlUrl")
        if xml_url:
            urls.append(xml_url)

    logger.info("Parsed %d feed URLs from OPML: %s", len(urls), opml_path)
    return urls


def collect_rss() -> list[CollectedItem]:
    """Collect AI-related items from RSS feeds.

    Loads feed URLs from OPML file (if exists) or falls back to
    config.RSS_FEED_URLS. Fetches each feed, filters to last 48 hours
    and AI-related entries, returns CollectedItem objects.

    Returns:
        List of CollectedItem from RSS feeds.
    """
    import os

    feed_urls: list[str] = []

    if os.path.exists(config.OPML_PATH):
        feed_urls = parse_opml(config.OPML_PATH)

    if not feed_urls:
        feed_urls = config.RSS_FEED_URLS

    if not feed_urls:
        logger.info("No RSS feed URLs configured (no OPML file and RSS_FEED_URLS is empty)")
        return []

    logger.info("Fetching %d RSS feeds", len(feed_urls))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FETCH_WINDOW_HOURS)
    items: list[CollectedItem] = []

    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                logger.warning("Feed error for %s: %s", url, feed.bozo_exception)
                continue

            feed_title = feed.feed.get("title", "")
            feed_count = 0

            for entry in feed.entries:
                # Parse published date
                if entry.get("published_parsed"):
                    published_at = datetime.fromtimestamp(
                        mktime(entry.published_parsed), tz=timezone.utc
                    )
                else:
                    published_at = datetime.now(timezone.utc)

                # Filter to recent entries
                if published_at < cutoff:
                    continue

                title = entry.get("title", "")
                body = entry.get("summary", None)

                # AI keyword filter — skip for AI-dedicated feeds
                AI_DEDICATED_DOMAINS = [
                    "theverge.com/rss/ai", "techcrunch.com/category/artificial-intelligence",
                    "venturebeat.com/category/ai", "technologyreview.com/topic/artificial-intelligen",
                    "deeplearning.ai", "huggingface.co", "anthropic.com", "openai.com",
                    "deepmind.google", "ai.meta.com", "nvidianews.nvidia.com",
                    "blogs.microsoft.com/ai", "blog.google",
                    "nitter.net", "xcancel.com", "youtube.com/feeds",  # Twitter + YouTube feeds
                ]
                is_dedicated = any(d in url for d in AI_DEDICATED_DOMAINS)
                if not is_dedicated and not is_ai_related(title, body):
                    continue

                source_id = entry.get("id") or entry.get("link", url)

                # Detect Twitter/X feeds
                item_source = "rss"
                if "xcancel.com" in url or "nitter.net" in url:
                    item_source = "twitter"

                items.append(CollectedItem(
                    source=item_source,
                    source_id=source_id,
                    title=title,
                    body=body,
                    url=entry.get("link"),
                    author=entry.get("author"),
                    published_at=published_at,
                    metadata={"feed_url": url, "feed_title": feed_title},
                ))
                feed_count += 1

            logger.info("Feed '%s' (%s): %d AI-related items", feed_title, url, feed_count)

        except Exception:
            logger.exception("Error fetching feed: %s", url)
            continue

    logger.info("RSS collection complete: %d items from %d feeds", len(items), len(feed_urls))
    return items
