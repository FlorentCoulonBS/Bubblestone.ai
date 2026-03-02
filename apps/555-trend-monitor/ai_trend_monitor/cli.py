"""CLI interface with Rich table output, source indicators, and velocity display."""

import argparse
import logging

from rich.console import Console
from rich.table import Table

from ai_trend_monitor import config


def main() -> None:
    """Entry point for ai-trend-monitor CLI."""
    parser = argparse.ArgumentParser(
        description="AI Trend Monitor - detect revolutionary AI developments early",
    )
    parser.add_argument("--limit", type=int, default=20, help="Max topics to display (default: 20)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--collect", action="store_true", help="Run collection silently (for cron)")
    parser.add_argument("--health", action="store_true", help="Show detailed health status")
    parser.add_argument("--install-cron", action="store_true", help="Install cron schedule")
    parser.add_argument("--uninstall-cron", action="store_true", help="Remove cron schedule")
    parser.add_argument("--show-schedule", action="store_true", help="Show cron schedule")
    parser.add_argument("--digest", action="store_true", help="Generate and send email digest")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(name)s - %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    # Cron management commands
    if args.install_cron:
        from ai_trend_monitor.scheduler import install_cron
        install_cron()
        return

    if args.uninstall_cron:
        from ai_trend_monitor.scheduler import uninstall_cron
        uninstall_cron()
        return

    if args.show_schedule:
        from ai_trend_monitor.scheduler import show_schedule
        show_schedule()
        return

    # Digest command
    if args.digest:
        from ai_trend_monitor.digest import send_digest
        ok = send_digest()
        raise SystemExit(0 if ok else 1)

    # Health status command
    if args.health:
        _show_health()
        return

    # Silent collection mode for cron
    if args.collect:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s - %(message)s", force=True)
        from ai_trend_monitor.pipeline import run_pipeline
        result = run_pipeline()
        logging.getLogger(__name__).info(
            "Collected %d items, %d topics (%.1fs)",
            result["total_items"], len(result["topics"]), result["duration"],
        )
        return

    # Interactive mode: collect and display
    from ai_trend_monitor.pipeline import run_pipeline

    console = Console()
    console.print("[bold]AI Trend Monitor[/bold] - scanning all sources...\n")

    result = run_pipeline()
    topics = result["topics"]
    sources = result["sources"]
    health = result["health"]
    total = len(topics)
    display_topics = topics[: args.limit]

    if not topics:
        console.print("[yellow]No topics found. Try again later or check collector configs.[/yellow]")
        _print_health_warnings(console, health)
        return

    # Build table with source indicators and velocity
    table = Table(title="AI Trend Topics")
    table.add_column("Score", justify="right", width=6)
    table.add_column("", width=3)  # status indicators
    table.add_column("Title", width=70)
    table.add_column("Sources", width=8)
    table.add_column("Velocity", width=8)
    table.add_column("Upvotes", justify="right", width=8)
    table.add_column("Comments", justify="right", width=8)

    for topic in display_topics:
        score = topic.score
        if score >= 8:
            style = "green bold"
        elif score >= 5:
            style = "yellow"
        else:
            style = "dim"

        # Status badges
        badges = ""
        if score >= config.TRENDING_THRESHOLD:
            badges += "T"
        if topic.is_official:
            badges += "*"

        # Title with optional markers
        title = topic.title
        if len(title) > 70:
            title = title[:67] + "..."

        # Source indicators: R=Reddit, F=RSS/Feed, G=Gmail, Y=YouTube
        source_list = [s.strip() for s in topic.sources.split(",") if s.strip()] if topic.sources else []
        source_map = {"reddit": "R", "rss": "F", "gmail": "G", "youtube": "Y"}
        source_str = " ".join(source_map.get(s, s[0].upper()) for s in source_list)

        # Velocity indicator
        v1 = topic.velocity_1h
        v24 = topic.velocity_24h
        if v1 > 0 and v24 > 0 and v1 > v24 * 2:
            velocity_str = "[green bold]RISING[/green bold]"
        elif v1 > 0:
            velocity_str = "[yellow]steady[/yellow]"
        else:
            velocity_str = "-"

        table.add_row(
            f"{score:.1f}",
            f"[red bold]{badges}[/red bold]" if badges else "",
            title,
            source_str,
            velocity_str,
            str(topic.upvotes_total),
            str(topic.comments_total),
            style=style,
        )

    console.print(table)

    # Legend
    console.print(
        "\n[dim]T=Trending  *=Official  R=Reddit  F=RSS  G=Gmail  X=Twitter[/dim]"
    )

    # Source counts summary
    parts = []
    for name, count in sources.items():
        if count > 0:
            parts.append(f"{name.title()} ({count})")
    source_summary = " | ".join(parts) if parts else "No items collected"
    console.print(
        f"\nShowing {len(display_topics)} of {total} topics | "
        f"Sources: {source_summary} | "
        f"{result['topics_created']} new topics | "
        f"{result['duration']}s"
    )

    # Health warnings
    _print_health_warnings(console, health)


def _print_health_warnings(console: Console, health: dict[str, dict]) -> None:
    """Print warnings for collectors with consecutive failures."""
    for name, info in health.items():
        failures = info.get("consecutive_failures", 0)
        if failures > 0:
            console.print(
                f"[yellow][WARNING][/yellow] {name} collector: "
                f"{failures} consecutive failure{'s' if failures != 1 else ''}"
            )


def _show_health() -> None:
    """Show detailed health status for all collectors."""
    from ai_trend_monitor.health import check_health

    console = Console()
    health = check_health()

    if not health:
        console.print("[yellow]No health data yet. Run a collection first.[/yellow]")
        return

    table = Table(title="Collector Health Status")
    table.add_column("Collector", width=12)
    table.add_column("Status", width=10)
    table.add_column("Failures", justify="right", width=10)
    table.add_column("Last Success", width=22)
    table.add_column("Last Count", justify="right", width=10)
    table.add_column("Avg Count", justify="right", width=10)

    for name, info in sorted(health.items()):
        status = info["status"]
        if status == "healthy":
            status_str = "[green]healthy[/green]"
        elif status == "degraded":
            status_str = "[yellow]degraded[/yellow]"
        else:
            status_str = "[red bold]failing[/red bold]"

        last_success = info["last_success"] or "never"
        if last_success != "never":
            # Trim to datetime without microseconds
            last_success = last_success[:19].replace("T", " ")

        table.add_row(
            name,
            status_str,
            str(info["consecutive_failures"]),
            last_success,
            str(info["last_item_count"]),
            str(info["avg_item_count"]),
        )

    console.print(table)


if __name__ == "__main__":
    main()
