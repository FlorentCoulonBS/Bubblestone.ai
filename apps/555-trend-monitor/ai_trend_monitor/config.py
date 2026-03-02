"""Configuration for AI Trend Monitor."""

import os

# Subreddits to monitor
SUBREDDITS = [
    "singularity",
    "artificial",
    "artificialintelligence",
    "ChatGPT",
    "Futurology",
    "LocalLLaMA",
    "MachineLearning",
    "ClaudeAI",
    "OpenAI",
    "StableDiffusion",
    "Anthropic",
]

# Collection settings
POSTS_PER_SUBREDDIT = 25

# Deduplication settings
DEDUP_SIMILARITY_THRESHOLD = 0.60
DEDUP_TIME_WINDOW_HOURS = 48

# Scoring weights (must sum to 1.0)
SCORING_WEIGHTS = {
    "upvotes": 0.10,
    "comments": 0.10,
    "keywords": 0.35,
    "subreddit": 0.10,
    "cross_source": 0.15,
    "official": 0.20,
}

# Keywords indicating revolutionary developments
REVOLUTIONARY_KEYWORDS = [
    "breakthrough",
    "game-changer",
    "announcing",
    "launching",
    "architecture",
    "benchmark",
    "performance",
    "open-source",
    "state-of-the-art",
    "SOTA",
    "released",
    "introduces",
]

# Keyword boost points (out of 10)
KEYWORD_BOOST = 3.5

# Database
DATABASE_PATH = os.environ.get("DATABASE_PATH", "/root/data/trends.db")

# Official sources (announcements from these get boosted)
OFFICIAL_SOURCES = [
    "AnthropicAI",
    "OpenAI",
    "GoogleDeepMind",
    "MetaAI",
    "nvidia",
    "Google",
    "Anthropic",
]

OFFICIAL_BOOST = 1.5
TRENDING_THRESHOLD = 7.0

# Gmail / Google Alerts
GMAIL_HOST = "imap.gmail.com"
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_ALERT_SENDER = "googlealerts-noreply@google.com"

# RSS / OPML
OPML_PATH = os.environ.get("OPML_PATH", "/root/data/feeds.opml")
RSS_FEED_URLS: list[str] = []

# Health monitoring
HEALTH_ALERT_THRESHOLD = 3

# Notifications
NTFY_TOPIC = "bubblestone-ai-alerts"
ALERT_EMAIL = "florent.coulon@bubblestone.ai"

# Velocity tracking
VELOCITY_WINDOWS = [1, 6, 24]  # hours

# Collection schedule
COLLECTION_TIMES = ["06:00", "09:00", "12:00", "15:00", "18:00", "21:00"]

# Phase 3: Dashboard & Delivery
NTFY_HIGH_SCORE_THRESHOLD = 8.0
DASHBOARD_URL = "http://localhost:5000"
DIGEST_HOUR = 6
DIGEST_MINUTE = 30
DIGEST_TIMEZONE = "Europe/Paris"
BASIC_AUTH_USER = os.environ.get("VEILLE_USER", "admin")
BASIC_AUTH_PASS = os.environ.get("VEILLE_PASS", "changeme")
