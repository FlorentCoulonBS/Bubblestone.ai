"""Collector health tracking with failure counting and alerting."""

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from ai_trend_monitor import config
from ai_trend_monitor.alerts import send_alert
from ai_trend_monitor.database import get_engine, init_db
from ai_trend_monitor.models import CollectorHealth

logger = logging.getLogger(__name__)


def _get_or_create(session: Session, collector_name: str) -> CollectorHealth:
    """Get existing health record or create a new one."""
    stmt = select(CollectorHealth).where(CollectorHealth.collector_name == collector_name)
    record = session.exec(stmt).first()
    if record is None:
        record = CollectorHealth(collector_name=collector_name)
        session.add(record)
        session.flush()
    return record


def record_success(collector_name: str, item_count: int) -> None:
    """Record a successful collection run. Never raises."""
    try:
        init_db()
        engine = get_engine()
        with Session(engine) as session:
            record = _get_or_create(session, collector_name)
            record.last_success = datetime.now(timezone.utc)
            record.consecutive_failures = 0
            record.last_item_count = item_count

            # Rolling average
            if record.avg_item_count == 0.0:
                record.avg_item_count = float(item_count)
            else:
                record.avg_item_count = (record.avg_item_count * 0.8) + (item_count * 0.2)

            session.add(record)
            session.commit()

            # Volume anomaly detection
            avg = record.avg_item_count
            if item_count < avg * 0.3 and avg > 5:
                send_alert(
                    f"Low volume: {collector_name}",
                    f"{collector_name} returned {item_count} items (avg: {avg:.0f})",
                )

            logger.info("Health: %s success, %d items", collector_name, item_count)
    except Exception:
        logger.exception("Failed to record health success for %s", collector_name)


def record_failure(collector_name: str, error: str) -> None:
    """Record a collection failure. Alerts after threshold. Never raises."""
    try:
        init_db()
        engine = get_engine()
        with Session(engine) as session:
            record = _get_or_create(session, collector_name)
            record.last_failure = datetime.now(timezone.utc)
            record.consecutive_failures += 1
            failures = record.consecutive_failures
            session.add(record)
            session.commit()

        if failures >= config.HEALTH_ALERT_THRESHOLD:
            send_alert(
                f"Collector failing: {collector_name}",
                f"{collector_name} has failed {failures} times consecutively: {error}",
            )

        logger.warning("Health: %s failure #%d: %s", collector_name, failures, error)
    except Exception:
        logger.exception("Failed to record health failure for %s", collector_name)


def check_health() -> dict[str, dict]:
    """Return health status of all collectors. Never raises."""
    try:
        init_db()
        engine = get_engine()
        with Session(engine) as session:
            records = session.exec(select(CollectorHealth)).all()
            result = {}
            for r in records:
                status = "healthy" if r.consecutive_failures == 0 else "degraded"
                if r.consecutive_failures >= config.HEALTH_ALERT_THRESHOLD:
                    status = "failing"
                result[r.collector_name] = {
                    "status": status,
                    "consecutive_failures": r.consecutive_failures,
                    "last_success": r.last_success.isoformat() if r.last_success else None,
                    "last_failure": r.last_failure.isoformat() if r.last_failure else None,
                    "last_item_count": r.last_item_count,
                    "avg_item_count": round(r.avg_item_count, 1),
                }
            return result
    except Exception:
        logger.exception("Failed to check health")
        return {}
