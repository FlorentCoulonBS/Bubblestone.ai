"""SQLModel models for AI Trend Monitor."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, LargeBinary
from sqlmodel import Field, SQLModel


class Topic(SQLModel, table=True):
    """A deduplicated topic aggregating related posts."""

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    url: Optional[str] = None
    score: float = Field(default=0.0)
    upvotes_total: int = Field(default=0)
    comments_total: int = Field(default=0)
    post_count: int = Field(default=1)
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    subreddits: str = Field(default="")
    sources: str = Field(default="reddit")
    velocity_1h: float = Field(default=0.0)
    velocity_6h: float = Field(default=0.0)
    velocity_24h: float = Field(default=0.0)
    is_official: bool = Field(default=False)
    dismissed_at: Optional[datetime] = Field(default=None)
    dismiss_action: Optional[str] = Field(default=None)
    notified_at: Optional[datetime] = Field(default=None)
    embedding: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary, nullable=True))


class Post(SQLModel, table=True):
    """A single Reddit post."""

    id: Optional[int] = Field(default=None, primary_key=True)
    reddit_id: str = Field(unique=True)
    subreddit: str
    title: str
    url: Optional[str] = None
    selftext: Optional[str] = None
    upvotes: int = Field(default=0)
    num_comments: int = Field(default=0)
    created_utc: float
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_stickied: bool = Field(default=False)
    topic_id: Optional[int] = Field(default=None, foreign_key="topic.id")


class CollectorHealth(SQLModel, table=True):
    """Health tracking for each collector source."""

    id: Optional[int] = Field(default=None, primary_key=True)
    collector_name: str = Field(unique=True)
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = Field(default=0)
    last_item_count: int = Field(default=0)
    avg_item_count: float = Field(default=0.0)


class TopicSnapshot(SQLModel, table=True):
    """Point-in-time snapshot of topic activity for velocity tracking."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mention_count: int = Field(default=0)
    source_count: int = Field(default=0)
