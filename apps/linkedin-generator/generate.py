#!/usr/bin/env python3
"""Insert LinkedIn post proposals into the database.

Called by the OpenClaw cron agent which generates the content itself.
Usage: python3 generate.py --json '{"posts": [...]}'
   or: python3 generate.py --topics  (dump trending topics as JSON for the agent)
   or: python3 generate.py --file posts.json
"""

import os
import sys
import json
import sqlite3

DB_PATH = os.environ.get("LINKEDIN_DB_PATH", "/root/data/linkedin/linkedin.db")
TRENDS_DB_PATH = os.environ.get("TRENDS_DB_PATH", "/root/data/trends.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            topic_id TEXT,
            topic_title TEXT NOT NULL,
            topic_url TEXT,
            topic_score REAL,
            post_text TEXT NOT NULL,
            image_prompt TEXT,
            image_path TEXT,
            status TEXT DEFAULT 'proposed' CHECK(status IN ('proposed', 'validated', 'rejected', 'published')),
            validated_at TIMESTAMP,
            published_at TIMESTAMP,
            article_md TEXT,
            sources TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
        CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
    """)
    conn.close()


def dump_topics(hours=24, limit=5):
    """Dump trending topics from trends.db as JSON for the agent."""
    try:
        conn = sqlite3.connect(f"file:{TRENDS_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        topics = conn.execute("""
            SELECT title, url, score, sources, last_seen
            FROM topic 
            WHERE dismissed_at IS NULL 
            AND last_seen >= datetime('now', ? || ' hours')
            ORDER BY score DESC LIMIT ?
        """, (f"-{hours}", limit)).fetchall()
        conn.close()
        result = [dict(t) for t in topics]
        if not result and hours < 72:
            return dump_topics(hours=hours * 2, limit=limit)
        return result
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return []


def insert_posts(posts_json):
    """Insert posts from JSON into the database."""
    init_db()
    if isinstance(posts_json, str):
        data = json.loads(posts_json)
    else:
        data = posts_json

    posts = data.get("posts", data) if isinstance(data, dict) else data
    conn = sqlite3.connect(DB_PATH)
    count = 0
    for p in posts:
        conn.execute(
            """INSERT INTO posts (topic_title, post_text, image_prompt, 
               topic_url, topic_score, article_md, sources)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (p.get("topic_title", ""), p.get("post_text", ""),
             p.get("image_prompt", ""), p.get("topic_url"),
             p.get("topic_score"), p.get("article_md"),
             p.get("sources"))
        )
        count += 1
        print(f"✅ Post #{count}: {p.get('topic_title', '')[:60]}")
    conn.commit()
    conn.close()
    print(f"Done. {count} posts inserted.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--topics":
        topics = dump_topics()
        print(json.dumps(topics, indent=2, ensure_ascii=False, default=str))
    elif len(sys.argv) > 2 and sys.argv[1] == "--json":
        insert_posts(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--file":
        with open(sys.argv[2]) as f:
            insert_posts(f.read())
    else:
        print("Usage:")
        print("  python3 generate.py --topics           # Dump trending topics")
        print("  python3 generate.py --json '{...}'     # Insert posts from JSON")
        print("  python3 generate.py --file posts.json  # Insert from file")
