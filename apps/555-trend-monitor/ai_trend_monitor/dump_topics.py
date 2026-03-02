"""Dump last 24h topics for Claude analysis."""
import sqlite3
import json
from datetime import datetime, timedelta, timezone

DB_PATH = "/root/data/trends.db"

def dump():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    
    c.execute("""
        SELECT title, score, sources, url, last_seen 
        FROM topic 
        WHERE last_seen >= ? 
        ORDER BY score DESC 
        LIMIT 100
    """, (cutoff,))
    
    topics = []
    for row in c.fetchall():
        topics.append({
            "title": row[0],
            "old_score": row[1],
            "sources": row[2],
            "url": row[3],
            "seen": row[4]
        })
    
    conn.close()
    print(json.dumps(topics, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    dump()
