"""Collectors package - common interface for all data sources."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CollectedItem:
    """Common interface for items collected from any source."""

    source: str
    source_id: str
    title: str
    body: str | None = None
    url: str | None = None
    author: str | None = None
    published_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)


CollectorResult = list[CollectedItem]
