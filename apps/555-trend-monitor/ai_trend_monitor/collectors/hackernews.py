"""Collect trending AI stories from Hacker News API."""
import json
import logging
import urllib.request
from datetime import datetime, timezone

from ai_trend_monitor.collectors import CollectedItem

logger = logging.getLogger(__name__)

AI_KEYWORDS = [
    'ai ', 'ai,', 'ai.', 'ai:', 'ai-', 'artificial intelligence',
    'llm', 'gpt', 'claude', 'openai', 'anthropic', 'gemini', 'deepmind',
    'machine learning', 'deep learning', 'neural', 'transformer',
    'chatbot', 'copilot', 'midjourney', 'stable diffusion',
    'kling', 'sora', 'agent', 'hugging face', 'huggingface',
    'langchain', 'rag ', 'embedding', 'diffusion model',
    'foundation model', 'open source ai', 'ai safety',
    'agentic', 'multimodal', 'vision model', 'language model',
]


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Trend-Monitor/1.0"})
    resp = urllib.request.urlopen(req, timeout=10)  # nosemgrep: dynamic-urllib-use-detected  # HN API URLs are hardcoded constants
    return json.loads(resp.read())


def is_ai_related(title):
    t = f" {title.lower()} "
    return any(k in t for k in AI_KEYWORDS)


def collect_hackernews(max_stories=200, min_score=10):
    """Collect AI-related stories from HN top stories."""
    logger.info("Collecting HN top stories (max %d)...", max_stories)
    
    try:
        top_ids = _fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    except Exception:
        logger.exception("Failed to fetch HN top stories")
        return []
    
    items = []
    checked = 0
    
    for story_id in top_ids[:max_stories]:
        try:
            story = _fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
            if not story or story.get("type") != "story":
                continue
            
            title = story.get("title", "")
            score = story.get("score", 0)
            checked += 1
            
            if score < min_score:
                continue
            
            if not is_ai_related(title):
                continue
            
            url = story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
            ts = story.get("time", 0)
            published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
            
            items.append(CollectedItem(
                source="hackernews",
                source_id=f"hn:{story_id}",
                title=title,
                body=None,
                url=url,
                author=story.get("by"),
                published_at=published,
                metadata={
                    "hn_id": story_id,
                    "score": score,
                    "comments": story.get("descendants", 0),
                    "hn_url": f"https://news.ycombinator.com/item?id={story_id}",
                },
            ))
        except Exception:
            continue
    
    logger.info("HN: checked %d stories, found %d AI-related (score >= %d)", checked, len(items), min_score)
    return items
