"""Velocity tracking with time-window calculations."""

import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ai_trend_monitor import config
from ai_trend_monitor.database import get_engine, init_db
from ai_trend_monitor.models import TopicSnapshot

logger = logging.getLogger(__name__)


def record_snapshot(
    topic_id: int,
    mention_count: int,
    source_count: int,
    session: Session | None = None,
) -> None:
    """Create a TopicSnapshot record with current timestamp."""
    snapshot = TopicSnapshot(
        topic_id=topic_id,
        mention_count=mention_count,
        source_count=source_count,
    )
    if session is not None:
        session.add(snapshot)
        return

    init_db()
    engine = get_engine()
    with Session(engine) as session:
        session.add(snapshot)
        session.commit()


def calculate_velocity(topic_id: int, session: Session | None = None) -> dict[str, float]:
    """Calculate velocity for each configured time window.

    Returns dict with velocity_1h, velocity_6h, velocity_24h values.
    Velocity = mentions_in_window / window_hours (rate).
    """
    now = datetime.utcnow()
    result = {f"velocity_{w}h": 0.0 for w in config.VELOCITY_WINDOWS}

    if session is not None:
        return _calculate_velocity_with_session(topic_id, session, now, result)

    init_db()
    engine = get_engine()
    with Session(engine) as session:
        return _calculate_velocity_with_session(topic_id, session, now, result)


def _calculate_velocity_with_session(
    topic_id: int,
    session: Session,
    now: datetime,
    result: dict[str, float],
) -> dict[str, float]:
    snapshots = session.exec(
        select(TopicSnapshot)
        .where(TopicSnapshot.topic_id == topic_id)
        .order_by(TopicSnapshot.timestamp.desc())  # type: ignore[union-attr]
    ).all()

    if len(snapshots) < 2:
        return result

    for window in config.VELOCITY_WINDOWS:
        window_start = now - timedelta(hours=window)
        prior_start = window_start - timedelta(hours=window)

        mentions_current = sum(
            s.mention_count for s in snapshots if s.timestamp >= window_start
        )
        mentions_prior = sum(
            s.mention_count
            for s in snapshots
            if prior_start <= s.timestamp < window_start
        )

        velocity = mentions_current / window if window > 0 else 0.0

        # Acceleration: ratio of current to prior velocity
        if mentions_prior > 0:
            prior_velocity = mentions_prior / window
            acceleration = velocity / prior_velocity if prior_velocity > 0 else 0.0
            # Use acceleration-weighted velocity for the score
            result[f"velocity_{window}h"] = round(velocity * acceleration, 2)
        else:
            result[f"velocity_{window}h"] = round(velocity, 2)

    return result
