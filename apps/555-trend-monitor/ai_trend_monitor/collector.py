"""Backward-compatible re-exports from collectors package."""

from ai_trend_monitor.collectors.reddit import collect_posts, is_ai_related, AI_KEYWORDS

__all__ = ["collect_posts", "is_ai_related", "AI_KEYWORDS"]
