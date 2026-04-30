"""SQLite models for LinkedIn post generator."""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("LINKEDIN_DB_PATH", "/data/linkedin.db")
TRENDS_DB_PATH = os.environ.get("TRENDS_DB_PATH", "/data/trends.db")
IMAGES_DIR = os.environ.get("IMAGES_DIR", "/data/images")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    conn = get_db()
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
            sources TEXT,
            anecdote TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
        CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    migrations = {
        "anecdote": "ALTER TABLE posts ADD COLUMN anecdote TEXT",
        "image_status": "ALTER TABLE posts ADD COLUMN image_status TEXT",
        "image_error": "ALTER TABLE posts ADD COLUMN image_error TEXT",
    }
    for column, sql in migrations.items():
        if column not in columns:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
    conn.commit()
    conn.close()


def get_posts(status=None, date=None, limit=50, offset=0):
    conn = get_db()
    query = "SELECT * FROM posts WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if date:
        query += " AND DATE(created_at) = ?"
        params.append(date)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    posts = conn.execute(query, params).fetchall()
    conn.close()
    return posts


def get_post(post_id):
    conn = get_db()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    return post


def get_post_by_topic_id(topic_id):
    conn = get_db()
    post = conn.execute(
        "SELECT * FROM posts WHERE topic_id = ? ORDER BY created_at DESC LIMIT 1",
        (str(topic_id),)
    ).fetchone()
    conn.close()
    return post


def create_post(topic_title, post_text, image_prompt, topic_id=None,
                topic_url=None, topic_score=None, article_md=None, sources=None,
                anecdote=None):
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO posts (topic_title, post_text, image_prompt, topic_id,
           topic_url, topic_score, article_md, sources, anecdote)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (topic_title, post_text, image_prompt, topic_id,
         topic_url, topic_score, article_md, sources, anecdote)
    )
    post_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return post_id


def update_post_text(post_id, post_text):
    conn = get_db()
    conn.execute("UPDATE posts SET post_text = ? WHERE id = ?", (post_text, post_id))
    conn.commit()
    conn.close()


def update_post_status(post_id, status):
    conn = get_db()
    extras = ""
    if status == "validated":
        extras = ", validated_at = CURRENT_TIMESTAMP"
    elif status == "published":
        extras = ", published_at = CURRENT_TIMESTAMP"
    conn.execute(f"UPDATE posts SET status = ?{extras} WHERE id = ?", (status, post_id))
    conn.commit()
    conn.close()


def update_post_image(post_id, image_path):
    conn = get_db()
    conn.execute(
        "UPDATE posts SET image_path = ?, image_status = ?, image_error = NULL WHERE id = ?",
        (image_path, "ready", post_id),
    )
    conn.commit()
    conn.close()


def update_image_status(post_id, image_status, image_error=None):
    conn = get_db()
    conn.execute(
        "UPDATE posts SET image_status = ?, image_error = ? WHERE id = ?",
        (image_status, image_error, post_id),
    )
    conn.commit()
    conn.close()


def update_post_generation(post_id, post_text, image_prompt, anecdote=None, article_md=None):
    conn = get_db()
    conn.execute(
        """UPDATE posts
           SET post_text = ?, image_prompt = ?, anecdote = ?, article_md = ?
           WHERE id = ?""",
        (post_text, image_prompt, anecdote, article_md, post_id),
    )
    conn.commit()
    conn.close()


def get_post_counts():
    conn = get_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM posts GROUP BY status"
    ).fetchall()
    conn.close()
    counts = {row["status"]: row["cnt"] for row in rows}
    counts["total"] = sum(counts.values())
    return counts
