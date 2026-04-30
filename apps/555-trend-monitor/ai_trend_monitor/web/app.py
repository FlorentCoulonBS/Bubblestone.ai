"""AI Trend Digest V2 — Dashboard Flask app."""
import os
import sys
import json
import sqlite3
import hashlib
import urllib.request
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, render_template, request, Response, jsonify, redirect, url_for

from ai_trend_monitor.dump_topics import (
    cluster_topics, merge_cluster, get_trend_history, normalize, extract_entities
)

DB_PATH = os.environ.get("DATABASE_PATH", "/root/data/trends.db")
OG_CACHE_PATH = os.environ.get("OG_CACHE_PATH", "/root/data/og_cache.json")
YOUTUBE_DATA_PATH = os.environ.get("YOUTUBE_DATA_PATH", "/data/youtube_latest.json")

# Load env
env_file = "/etc/ai-trend-monitor.env"
if os.path.exists(env_file):
    for line in open(env_file):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

VEILLE_USER = os.environ.get("VEILLE_USER", "")
VEILLE_PASS = os.environ.get("VEILLE_PASS", "")
INTERNAL_SECRET = os.environ.get("SECRET_KEY", "")
LINKEDIN_INGEST_URL = os.environ.get(
    "LINKEDIN_INGEST_URL",
    "http://linkedin-generator:5001/api/intake-topic",
)

app = Flask(__name__)
app.config["SECRET_KEY"] = hashlib.sha256(VEILLE_PASS.encode()).hexdigest()


# --- Auth ---
def check_auth(username, password):
    return username == VEILLE_USER and password == VEILLE_PASS


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not VEILLE_USER:  # No auth configured
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response("Access denied", 401,
                            {"WWW-Authenticate": 'Basic realm="AI Trend Digest"'})
        return f(*args, **kwargs)
    return decorated


# --- OG Image cache ---
def load_og_cache():
    if os.path.exists(OG_CACHE_PATH):
        try:
            return json.load(open(OG_CACHE_PATH))
        except Exception:
            return {}
    return {}


def save_og_cache(cache):
    try:
        with open(OG_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _extract_og_from_html(html):
    """Extract og:image from HTML, trying multiple patterns."""
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return None


def _reddit_thumbnail(url):
    """Get thumbnail from Reddit JSON API."""
    try:
        # Convert old.reddit.com to www for JSON API
        json_url = url.replace("old.reddit.com", "www.reddit.com")
        if not json_url.endswith(".json"):
            json_url = json_url.rstrip("/") + ".json"
        req = urllib.request.Request(json_url, headers={
            "User-Agent": "Mozilla/5.0 (BubbleStoneBot/2.0)"
        })
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read(200000))
        if isinstance(data, list) and len(data) > 0:
            post = data[0]["data"]["children"][0]["data"]
            # Try preview images first (higher quality)
            preview = post.get("preview", {}).get("images", [])
            if preview:
                src = preview[0].get("source", {}).get("url", "")
                if src:
                    return src.replace("&amp;", "&")
            # Fallback to thumbnail
            thumb = post.get("thumbnail", "")
            if thumb and thumb.startswith("http"):
                return thumb
    except Exception:
        pass
    return None


def fetch_og_image(url):
    if not url:
        return None
    cache = load_og_cache()
    if url in cache and cache[url] is not None:
        return cache[url]
    
    img = None
    try:
        # Reddit special handling
        if "reddit.com" in url or "redd.it" in url:
            img = _reddit_thumbnail(url)
        
        # YouTube thumbnail shortcut
        elif "youtube.com/watch" in url or "youtu.be/" in url:
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            vid = qs.get("v", [""])[0]
            if not vid and "youtu.be" in url:
                vid = parsed.path.lstrip("/")
            if vid:
                img = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
        
        if not img:
            import subprocess
            result = subprocess.run(
                ["curl", "-sL", "--max-time", "8", "-A",
                 "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                 "-H", "Accept: text/html", url],
                capture_output=True, timeout=10
            )
            html = result.stdout[:150000].decode("utf-8", errors="ignore")
            img = _extract_og_from_html(html)
    except Exception:
        pass
    
    cache[url] = img
    save_og_cache(cache)
    return img


# --- DB helpers ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_topics_for_date(date_str):
    """Get clustered topics for a given date (YYYY-MM-DD)."""
    conn = get_db()
    c = conn.cursor()
    start = f"{date_str} 00:00:00"
    end = f"{date_str} 23:59:59.999999"
    c.execute("""
        SELECT id, title, score, sources, url, last_seen, post_count, velocity_1h, velocity_6h, velocity_24h, first_seen
        FROM topic WHERE last_seen BETWEEN ? AND ?
        ORDER BY score DESC LIMIT 150
    """, (start, end))
    raw = []
    for r in c.fetchall():
        raw.append({
            "id": r[0], "title": r[1], "old_score": r[2], "sources": r[3] or "unknown",
            "url": r[4], "seen": r[5], "post_count": r[6],
            "velocity_1h": r[7], "velocity_6h": r[8], "velocity_24h": r[9],
            "first_seen": r[10]
        })

    # Add YouTube items from API collector
    yt_path = YOUTUBE_DATA_PATH
    try:
        if os.path.exists(yt_path):
            mtime = os.path.getmtime(yt_path)
            age_hours = (datetime.now(timezone.utc).timestamp() - mtime) / 3600
            if age_hours < 24:
                with open(yt_path) as f:
                    yt_items = json.load(f)
                # Filter: only AI-dedicated channels or AI-related titles
                AI_CHANNELS = {"Matt Wolfe", "AI Jason", "All About AI", "Matthew Berman", "Sam Witteveen"}
                for it in yt_items:
                    if it.get("channel") in AI_CHANNELS:
                        # Check if video date matches requested date
                        pub = it.get("published", "")[:10]
                        if pub >= date_str or date_str == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                            raw.append({
                                "id": None,
                                "title": it["title"], "old_score": 1.5, "sources": "youtube",
                                "url": it["url"], "seen": it.get("published", ""),
                                "post_count": 1, "velocity_1h": 0, "velocity_6h": 0,
                                "velocity_24h": 0, "first_seen": it.get("published", "")
                            })
    except Exception:
        pass

    clusters = cluster_topics(raw)
    merged = [merge_cluster(cl) for cl in clusters]
    # combined_signal already computed in merge_cluster
    merged.sort(key=lambda t: t.get("combined_signal", 0), reverse=True)

    # Enrich with trend history and OG images
    og_cache = load_og_cache()
    for t in merged[:20]:
        try:
            hist = get_trend_history(t["title"], conn)
            t.update(hist)
        except Exception:
            t["mentions_24h"] = t["volume"]
            t["mentions_3d"] = t["volume"]
            t["mentions_7d"] = t["volume"]
            t["trend"] = "new"

        url = t.get("url")
        if url and url in og_cache:
            t["og_image"] = og_cache[url]
        else:
            t["og_image"] = None  # fetch lazily via API

        # Determine velocity trend
        v1 = t.get("velocity_1h", 0) if "velocity_1h" in t else 0
        if t.get("trend") == "rising" or (isinstance(v1, (int, float)) and v1 > 0.5):
            t["trend_emoji"] = "📈"
            t["trend_label"] = "rising"
        elif t.get("trend") == "new":
            t["trend_emoji"] = "🆕"
            t["trend_label"] = "new"
        else:
            t["trend_emoji"] = "📊"
            t["trend_label"] = "established"

        # Source badges
        src_list = [s.strip().lower() for s in t["sources"].split(",") if s.strip()]
        t["source_list"] = src_list

        # Score color based on combined_signal
        sig = t.get("combined_signal", 0)
        if sig >= 20:
            t["score_color"] = "red"
        elif sig >= 10:
            t["score_color"] = "orange"
        elif sig >= 5:
            t["score_color"] = "yellow"
        else:
            t["score_color"] = "blue"

    conn.close()
    return merged[:20]


def get_topic(topic_id):
    conn = get_db()
    row = conn.execute("""
        SELECT id, title, score, sources, url, last_seen, first_seen, post_count,
               velocity_1h, velocity_6h, velocity_24h
        FROM topic WHERE id = ?
    """, (topic_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "score": row["score"],
        "sources": row["sources"] or "unknown",
        "url": row["url"],
        "last_seen": row["last_seen"],
        "first_seen": row["first_seen"],
        "post_count": row["post_count"],
        "velocity_1h": row["velocity_1h"],
        "velocity_6h": row["velocity_6h"],
        "velocity_24h": row["velocity_24h"],
    }


def search_topics(query, limit=50):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT title, score, sources, url, last_seen, post_count, first_seen
        FROM topic WHERE title LIKE ? ORDER BY last_seen DESC LIMIT ?
    """, (f"%{query}%", limit))
    results = []
    for r in c.fetchall():
        src_list = [s.strip().lower() for s in (r[2] or "unknown").split(",") if s.strip()]
        score = r[1]
        if score >= 6:
            sc = "red"
        elif score >= 4:
            sc = "orange"
        elif score >= 2:
            sc = "yellow"
        else:
            sc = "blue"
        results.append({
            "title": r[0], "old_score": score, "sources": r[2], "url": r[3],
            "last_seen": r[4], "post_count": r[5], "first_seen": r[6],
            "source_list": src_list, "score_color": sc
        })
    conn.close()
    return results


# --- Routes ---
@app.route("/")
@requires_auth
def index():
    date_str = request.args.get("date")
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    topics = get_topics_for_date(date_str)
    
    # Nav dates
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    prev_date = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    is_today = date_str == today

    return render_template("index.html",
                           topics=topics, date=date_str,
                           prev_date=prev_date, next_date=next_date,
                           is_today=is_today, today=today)


@app.route("/source/youtube")
@requires_auth
def source_youtube():
    yt_path = YOUTUBE_DATA_PATH
    items = []
    try:
        if os.path.exists(yt_path):
            with open(yt_path) as f:
                yt_items = json.load(f)
            for it in yt_items[:10]:
                vid_id = ""
                if "youtube.com/watch" in (it.get("url") or ""):
                    import urllib.parse
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(it["url"]).query)
                    vid_id = qs.get("v", [""])[0]
                items.append({
                    "title": it["title"],
                    "url": it.get("url"),
                    "channel": it.get("channel"),
                    "published": it.get("published", ""),
                    "thumbnail": f"https://img.youtube.com/vi/{vid_id}/maxresdefault.jpg" if vid_id else it.get("thumbnail"),
                })
    except Exception:
        pass
    return render_template("source.html", items=items, source_name="YouTube", source_emoji="▶️", source_key="youtube")


@app.route("/source/<source_key>")
@requires_auth
def source_generic(source_key):
    SOURCE_MAP = {
        "reddit": ("Reddit", "🟠"),
        "rss": ("RSS", "📡"),
        "gmail": ("Google Alerts", "🔔"),
        "twitter": ("X / Twitter", "𝕏"),
        "hackernews": ("Hacker News", "🟧"),
    }
    if source_key not in SOURCE_MAP:
        return redirect(url_for("index"))
    name, emoji = SOURCE_MAP[source_key]
    conn = get_db()
    c = conn.cursor()
    # Get recent topics for this source (last 48h for better coverage)
    from datetime import timedelta as td
    cutoff = (datetime.now(timezone.utc) - td(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        SELECT title, score, sources, url, last_seen, first_seen, post_count
        FROM topic WHERE sources LIKE ? AND last_seen >= ?
        ORDER BY score DESC LIMIT 50
    """, (f"%{source_key}%", cutoff))
    raw = []
    for r in c.fetchall():
        raw.append({
            "title": r[0], "old_score": r[1], "sources": r[2] or source_key,
            "url": r[3], "seen": r[4], "first_seen": r[5], "post_count": r[6] or 1,
        })
    conn.close()

    # Cluster and rank with combined_signal (same as global)
    clusters = cluster_topics(raw)
    merged = [merge_cluster(cl) for cl in clusters]
    merged.sort(key=lambda t: t.get("combined_signal", 0), reverse=True)

    # Load OG cache for thumbnails
    og_cache = {}
    try:
        with open(OG_CACHE_PATH) as f:
            og_cache = json.load(f)
    except Exception:
        pass

    items = []
    for t in merged[:10]:
        sig = t.get("combined_signal", 0)
        if sig >= 20: sc = "red"
        elif sig >= 10: sc = "orange"
        elif sig >= 5: sc = "yellow"
        else: sc = "blue"
        url = t.get("url")
        items.append({
            "title": t["title"], "score": round(sig, 1), "score_color": sc,
            "url": url, "last_seen": t.get("seen"), "first_seen": t.get("first_seen"),
            "og_image": og_cache.get(url) if url else None,
        })
    return render_template("source.html", items=items, source_name=name, source_emoji=emoji, source_key=source_key)


@app.route("/search")
@requires_auth
def search():
    q = request.args.get("q", "").strip()
    results = search_topics(q) if q else []
    return render_template("search.html", query=q, results=results)


@app.route("/api/og-image")
@requires_auth
def api_og_image():
    url = request.args.get("url")
    if not url:
        return jsonify({"image": None})
    img = fetch_og_image(url)
    return jsonify({"image": img})


@app.route("/api/topic/<int:topic_id>/send-linkedin", methods=["POST"])
@requires_auth
def api_send_linkedin(topic_id):
    topic = get_topic(topic_id)
    if not topic:
        return jsonify({"error": "Topic introuvable"}), 404
    if not INTERNAL_SECRET:
        return jsonify({"error": "Secret interne non configuré"}), 503

    body = request.get_json(silent=True) or {}
    payload = dict(topic)
    payload["anecdote"] = (body.get("anecdote") or "").strip()

    try:
        resp = requests.post(
            LINKEDIN_INGEST_URL,
            json=payload,
            headers={"X-Internal-Secret": INTERNAL_SECRET},
            timeout=60,
        )
        payload = resp.json()
    except Exception as exc:
        return jsonify({"error": f"LinkedIn indisponible: {exc}"}), 502

    if resp.status_code >= 400:
        return jsonify(payload), resp.status_code
    return jsonify(payload)


def create_app():
    return app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
