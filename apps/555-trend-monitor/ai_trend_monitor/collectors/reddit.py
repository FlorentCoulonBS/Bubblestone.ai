"""Reddit post collection via public .json endpoints."""

import logging
import re
import time
from datetime import datetime, timezone

import requests
from sqlmodel import Session, select

from ai_trend_monitor import config
from ai_trend_monitor.collectors import CollectedItem
from ai_trend_monitor.database import get_engine, init_db
from ai_trend_monitor.models import Post

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
REQUEST_DELAY = 2  # seconds between subreddit requests

# AI and automation keywords - posts must contain at least one to be collected
AI_KEYWORDS = [
    # General AI
    "ai", "artificial intelligence", "ml", "machine learning", "deep learning",
    "neural network", "neural net", "deep neural", "convolutional", "recurrent",

    # LLMs & Models
    "llm", "large language model", "gpt", "claude", "chatgpt", "gemini",
    "llama", "mistral", "falcon", "bloom", "palm", "bard", "copilot",
    "language model", "foundation model", "multimodal",

    # Companies & Labs
    "openai", "anthropic", "deepmind", "google ai", "meta ai", "nvidia ai",
    "stability ai", "hugging face", "cohere", "midjourney",

    # Techniques & Concepts
    "transformer", "attention mechanism", "diffusion", "gan", "generative",
    "embedding", "vector", "fine-tuning", "rlhf", "prompt", "prompting",
    "few-shot", "zero-shot", "chain-of-thought", "rag", "retrieval",
    "agent", "autonomous agent", "multi-agent", "reasoning",

    # Image/Video AI
    "stable diffusion", "dall-e", "dalle", "midjourney", "imagen",
    "text-to-image", "image generation", "video generation", "sora",

    # AI Alignment & Safety
    "agi", "artificial general intelligence", "superintelligence",
    "alignment", "ai safety", "ai risk", "existential risk",

    # Automation & Workflows
    "automation", "workflow automation", "automate", "n8n", "zapier",
    "make.com", "langchain", "llama index", "semantic kernel",
    "ai workflow", "autonomous", "orchestration",

    # Technical terms
    "inference", "training", "fine-tune", "quantization", "lora",
    "gpu", "tensor", "pytorch", "tensorflow", "tokenization",
    "benchmark", "eval", "evaluation", "dataset", "model card",

    # Applications
    "chatbot", "voice assistant", "code generation", "coprogramming",
    "ai coding", "ai assistant", "virtual assistant", "semantic search",
]


# Precompile patterns: short keywords (<=3 chars) use word boundaries
_AI_PATTERNS = []
for _kw in AI_KEYWORDS:
    if len(_kw) <= 3:
        _AI_PATTERNS.append(re.compile(r"\b" + re.escape(_kw) + r"\b", re.IGNORECASE))
    else:
        _AI_PATTERNS.append(re.compile(re.escape(_kw), re.IGNORECASE))


def is_ai_related(title: str, selftext: str | None) -> bool:
    """Check if post is related to AI/automation based on keywords.

    Uses word-boundary matching for short keywords (ai, ml, gan, rag)
    to avoid false positives like 'email', 'Airtable', etc.
    """
    text = f"{title} {selftext or ''}"
    return any(pat.search(text) for pat in _AI_PATTERNS)


def collect_reddit() -> list[CollectedItem]:
    """Collect hot posts from all configured subreddits as CollectedItems.

    Uses Reddit's public .json endpoints (no API credentials needed).

    Returns:
        List of CollectedItem objects from Reddit.
    """
    items: list[CollectedItem] = []
    now = time.time()
    max_age_seconds = 86400  # 24 hours

    for subreddit_name in config.SUBREDDITS:
        try:
            url = f"https://old.reddit.com/r/{subreddit_name}/hot.json"
            resp = requests.get(
                url,
                params={"limit": config.POSTS_PER_SUBREDDIT},
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            children = data.get("data", {}).get("children", [])

            for child in children:
                post_data = child.get("data", {})

                if post_data.get("stickied", False):
                    continue

                created_utc = post_data.get("created_utc", 0)
                if now - created_utc > max_age_seconds:
                    continue

                reddit_id = post_data.get("id", "")
                if not reddit_id:
                    continue

                title = post_data.get("title", "")
                selftext = post_data.get("selftext") or None
                if not is_ai_related(title, selftext):
                    continue

                items.append(CollectedItem(
                    source="reddit",
                    source_id=f"reddit:{reddit_id}",
                    title=title,
                    body=selftext,
                    url=post_data.get("url", ""),
                    author=post_data.get("author"),
                    published_at=datetime.fromtimestamp(created_utc, tz=timezone.utc),
                    metadata={
                        "subreddit": subreddit_name,
                        "upvotes": post_data.get("score", 0),
                        "num_comments": post_data.get("num_comments", 0),
                        "reddit_id": reddit_id,
                    },
                ))

            logger.info("Collected from r/%s", subreddit_name)

        except Exception:
            logger.exception("Error collecting from r/%s", subreddit_name)
            continue

        # Rate limit between subreddits
        if subreddit_name != config.SUBREDDITS[-1]:
            time.sleep(REQUEST_DELAY)

    return items


def collect_posts() -> dict[str, int]:
    """Collect hot posts from all configured subreddits and write to DB.

    Backward-compatible wrapper around collect_reddit().

    Returns:
        Dict with "new" and "updated" counts.
    """
    init_db()

    items = collect_reddit()
    new_count = 0
    updated_count = 0
    engine = get_engine()

    for item in items:
        reddit_id = item.metadata["reddit_id"]

        with Session(engine) as session:
            statement = select(Post).where(Post.reddit_id == reddit_id)
            existing = session.exec(statement).first()

            if existing:
                existing.upvotes = item.metadata["upvotes"]
                existing.num_comments = item.metadata["num_comments"]
                session.add(existing)
                session.commit()
                updated_count += 1
            else:
                post = Post(
                    reddit_id=reddit_id,
                    subreddit=item.metadata["subreddit"],
                    title=item.title,
                    url=item.url,
                    selftext=item.body,
                    upvotes=item.metadata["upvotes"],
                    num_comments=item.metadata["num_comments"],
                    created_utc=item.published_at.timestamp(),
                    is_stickied=False,
                )
                session.add(post)
                session.commit()
                new_count += 1

    return {"new": new_count, "updated": updated_count}
