"""Cron scheduling for automated collection runs."""

import subprocess
import logging

from ai_trend_monitor import config

logger = logging.getLogger(__name__)

CRON_MARKER = "# ai-trend-monitor"
CRON_CMD = "/root/.venv/bin/ai-trend-monitor --collect"
CRON_LOG = "/root/data/cron.log"


def _build_cron_lines() -> list[str]:
    """Build crontab lines from config.COLLECTION_TIMES."""
    hours = sorted(set(int(t.split(":")[0]) for t in config.COLLECTION_TIMES))
    minutes = sorted(set(int(t.split(":")[1]) for t in config.COLLECTION_TIMES))
    # All configured times use same minute (typically 0)
    minute = minutes[0] if minutes else 0
    hour_spec = ",".join(str(h) for h in hours)

    line = f"TZ=Europe/Paris {minute} {hour_spec} * * * {CRON_CMD} >> {CRON_LOG} 2>&1 {CRON_MARKER}"
    return [line]


def _read_crontab() -> str:
    """Read current crontab. Returns empty string if none."""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""


def _write_crontab(content: str) -> None:
    """Write crontab content."""
    subprocess.run(
        ["crontab", "-"], input=content, text=True, check=True, timeout=10,
    )


def install_cron() -> None:
    """Install ai-trend-monitor cron entries."""
    existing = _read_crontab()

    # Remove old ai-trend-monitor lines
    lines = [line for line in existing.splitlines() if CRON_MARKER not in line]

    # Add new lines
    new_lines = _build_cron_lines()
    lines.extend(new_lines)

    # Ensure trailing newline
    content = "\n".join(lines).strip() + "\n"
    _write_crontab(content)

    print("Installed cron schedule:")
    for line in new_lines:
        print(f"  {line}")
    print(f"\nCollection runs {len(config.COLLECTION_TIMES)}x/day (Europe/Paris):")
    for t in config.COLLECTION_TIMES:
        print(f"  {t}")


def uninstall_cron() -> None:
    """Remove ai-trend-monitor entries from crontab."""
    existing = _read_crontab()
    lines = [line for line in existing.splitlines() if CRON_MARKER not in line]
    content = "\n".join(lines).strip() + "\n" if lines else ""
    _write_crontab(content)
    print("Removed ai-trend-monitor cron entries.")


def show_schedule() -> None:
    """Print current ai-trend-monitor cron entries."""
    existing = _read_crontab()
    our_lines = [line for line in existing.splitlines() if CRON_MARKER in line]

    if our_lines:
        print("Current ai-trend-monitor schedule:")
        for line in our_lines:
            print(f"  {line}")
        print(f"\nConfigured times (Europe/Paris): {', '.join(config.COLLECTION_TIMES)}")
    else:
        print("No ai-trend-monitor cron entries found.")
        print(f"Run --install-cron to schedule {len(config.COLLECTION_TIMES)} daily runs.")
