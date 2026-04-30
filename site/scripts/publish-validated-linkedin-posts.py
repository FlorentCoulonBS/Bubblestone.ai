#!/usr/bin/env python3
"""Publish validated LinkedIn posts into the Astro blog.

The LinkedIn app stores validated posts in SQLite. This script is intended to
run unattended from the server: it converts unexported validated posts to Astro
Markdown, commits them to main, and lets GitHub Actions deploy the site.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path


SOURCE_REPO_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = Path(os.environ.get("BLOG_PUBLISH_REPO_DIR", SOURCE_REPO_DIR))
REPO_URL = os.environ.get("BLOG_PUBLISH_REPO_URL", "git@github.com:FlorentCoulonBS/Bubblestone.ai.git")
DB_PATH = Path(os.environ.get("LINKEDIN_DB_PATH", "/opt/bubblestone-linkedin-data/linkedin.db"))
IMAGES_DIR = Path(os.environ.get("LINKEDIN_IMAGES_DIR", "/opt/bubblestone-linkedin-data/images"))
SITE_DIR = REPO_DIR / "site"
BLOG_DIR = SITE_DIR / "src" / "content" / "blog"
BLOG_IMAGES_DIR = SITE_DIR / "public" / "images" / "blog"


def run(cmd: list[str], cwd: Path = REPO_DIR) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("ASTRO_TELEMETRY_DISABLED", "1")
    return subprocess.run(cmd, cwd=cwd, env=env, check=True, text=True, capture_output=True)


def slugify(text: str) -> str:
    text = text.lower().strip()
    replacements = {
        "à": "a", "â": "a", "ä": "a",
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "î": "i", "ï": "i", "ô": "o",
        "ù": "u", "û": "u", "ü": "u",
        "ç": "c", "œ": "oe", "æ": "ae",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:80] or "article"


def yaml_string(value: str | None) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def ensure_repo() -> None:
    if REPO_DIR.resolve() == SOURCE_REPO_DIR.resolve():
        return
    if (REPO_DIR / ".git").exists():
        run(["git", "switch", "main"])
        run(["git", "pull", "--ff-only", "origin", "main"])
        return
    REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", REPO_URL, str(REPO_DIR)], check=True)
    run(["git", "switch", "main"])


def ensure_db_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    migrations = {
        "blog_slug": "ALTER TABLE posts ADD COLUMN blog_slug TEXT",
        "blog_published_at": "ALTER TABLE posts ADD COLUMN blog_published_at TIMESTAMP",
        "blog_error": "ALTER TABLE posts ADD COLUMN blog_error TEXT",
    }
    for column, sql in migrations.items():
        if column not in columns:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
    conn.commit()


def description_from(body: str, fallback: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = re.sub(r"\s+", " ", line)
        return (line[:157].rsplit(" ", 1)[0] + "...") if len(line) > 160 else line
    return fallback


def body_from_post(post: sqlite3.Row) -> str:
    article = (post["article_md"] or "").strip()
    if article and not article.startswith("{"):
        return article
    return (post["post_text"] or "").strip()


def copy_image(slug: str, image_path: str | None) -> str:
    if not image_path:
        return ""
    source = IMAGES_DIR / image_path
    if not source.exists():
        return ""
    suffix = source.suffix.lower() or ".png"
    target_name = f"{slug}{suffix}"
    target = BLOG_IMAGES_DIR / target_name
    BLOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return f"/images/blog/{target_name}"


def frontmatter(post: sqlite3.Row, slug: str, body: str, image: str) -> str:
    title = post["topic_title"] or "Article IA"
    date = (post["created_at"] or datetime.utcnow().isoformat())[:10]
    tags = ["IA", "Veille", "LinkedIn"]
    description = description_from(body, title)
    linkedin_url = f"https://linkedin.bubblestone.ai/post/{post['id']}"
    return "\n".join([
        "---",
        f"title: {yaml_string(title)}",
        f"description: {yaml_string(description)}",
        f"date: {date}",
        'author: "Florent Coulon"',
        f"image: {yaml_string(image)}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        f"linkedin: {yaml_string(linkedin_url)}",
        "draft: false",
        "---",
        "",
        body,
        "",
    ])


def candidate_posts(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT *
           FROM posts
           WHERE status = 'validated'
             AND COALESCE(blog_published_at, '') = ''
           ORDER BY validated_at ASC, created_at ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()


def publish_posts(dry_run: bool, limit: int) -> int:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"LinkedIn DB not found: {DB_PATH}")

    ensure_repo()
    BLOG_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_db_schema(conn)
    posts = candidate_posts(conn, limit)
    if not posts:
        print("No validated LinkedIn posts to publish.")
        return 0

    published: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    for post in posts:
        if post["image_status"] == "generating":
            skipped.append((post["id"], "image still generating"))
            continue
        body = body_from_post(post)
        if not body:
            skipped.append((post["id"], "empty article body"))
            continue
        slug = slugify(post["topic_title"] or f"linkedin-post-{post['id']}")
        if dry_run:
            published.append((post["id"], slug))
            continue
        path = BLOG_DIR / f"{slug}.md"
        image = copy_image(slug, post["image_path"])
        if not path.exists():
            path.write_text(frontmatter(post, slug, body, image), encoding="utf-8")
        published.append((post["id"], slug))

    if not dry_run:
        for post_id, reason in skipped:
            conn.execute("UPDATE posts SET blog_error = ? WHERE id = ?", (reason, post_id))
        conn.commit()

    if not published:
        print(f"No posts published. Skipped: {skipped}")
        return 0

    if dry_run:
        print(f"Dry run, would publish: {published}")
        return len(published)

    run(["npm", "run", "build"], cwd=SITE_DIR)
    run(["git", "add", "site/src/content/blog", "site/public/images/blog", "site/scripts/publish-validated-linkedin-posts.py"])
    status = run(["git", "status", "--porcelain"]).stdout.strip()
    if status:
        title = "blog: publish validated LinkedIn posts"
        run(["git", "commit", "-m", title])
        run(["git", "push", "origin", "main"])

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for post_id, slug in published:
        conn.execute(
            "UPDATE posts SET blog_slug = ?, blog_published_at = ?, blog_error = NULL WHERE id = ?",
            (slug, now, post_id),
        )
    conn.commit()
    print(f"Published {len(published)} LinkedIn posts: {published}")
    return len(published)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    publish_posts(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
