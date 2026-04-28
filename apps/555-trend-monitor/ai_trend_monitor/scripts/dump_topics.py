"""Dump last 24h topics, clustered by similarity with volume signal."""
import sqlite3
import json
import urllib.request
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

DB_PATH = os.environ.get("DATABASE_PATH", "/root/data/trends.db")

STOP_WORDS = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for",
              "of", "with", "and", "or", "but", "i", "my", "we", "our", "you", "your",
              "it", "its", "this", "that", "how", "what", "why", "do", "does", "just",
              "from", "by", "as", "be", "been", "has", "have", "had", "not", "no", "so"}

# Key entities to detect (model names, companies, products)
KEY_ENTITIES = [
    r"opus\s*4[\.\s]*6", r"opus\s*4[\.\s]*5", r"gpt[\-\s]*5[\.\s]*3",
    r"gpt[\-\s]*5[\.\s]*2", r"gpt[\-\s]*4o", r"gpt[\-\s]*5",
    r"claude\s*code", r"codex", r"gemini\s*2", r"gemini\s*3",
    r"llama\s*4", r"llama\s*3", r"qwen\s*3", r"qwen\s*2",
    r"grok\s*3", r"grok\s*2", r"deepseek[\-\s]*[rv]\d",
    r"midjourney\s*v\d", r"flux[\.\s]*2", r"dall[\-\s]*e\s*\d",
    r"kling\s*\d", r"sora\s*\d?", r"seedream",
    r"openai", r"anthropic", r"google\s*deepmind", r"meta\s*ai",
    r"nvidia", r"microsoft", r"apple\s*intelligence",
    r"super\s*bowl", r"tsmc", r"waymo",
]


def normalize(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s\.]', ' ', text)
    words = [w for w in text.split() if w not in STOP_WORDS and len(w) > 2]
    return ' '.join(words)


def extract_entities(text):
    """Extract key entity matches from text."""
    text_lower = text.lower()
    found = set()
    for pattern in KEY_ENTITIES:
        if re.search(pattern, text_lower):
            found.add(pattern)
    return found


def similarity(a, b):
    na, nb = normalize(a), normalize(b)
    wa, wb = set(na.split()), set(nb.split())
    if not wa or not wb:
        return 0

    # Entity-based similarity: shared key entities boost similarity
    ea, eb = extract_entities(a), extract_entities(b)
    shared_entities = ea & eb
    if len(shared_entities) >= 2:
        return 0.8  # Two shared key entities = almost certainly same topic
    if len(shared_entities) == 1:
        # One shared entity + some word overlap = likely same topic
        word_overlap = len(wa & wb) / min(len(wa), len(wb))
        if word_overlap > 0.2:
            return 0.6

    # Fallback: word overlap
    overlap = len(wa & wb) / min(len(wa), len(wb))
    if overlap > 0.4:
        seq = SequenceMatcher(None, na, nb).ratio()
        return max(overlap, seq)
    return overlap


def check_reddit_url(url, timeout=5):
    if not url:
        return True
    if "reddit.com" not in url and "redd.it" not in url:
        return True
    try:
        json_url = url.replace("old.reddit.com", "www.reddit.com")
        if not json_url.endswith(".json"):
            json_url = json_url.rstrip("/") + ".json"
        req = urllib.request.Request(json_url,
            headers={"User-Agent": "BubbleStone-Veille/2.0"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode())
        if isinstance(data, list) and len(data) > 0:
            post = data[0].get("data", {}).get("children", [{}])[0].get("data", {})
            if post.get("removed_by_category") or post.get("selftext") == "[removed]":
                return False
        return True
    except Exception:
        return True


def cluster_topics(topics, threshold=0.45):
    clusters = []
    used = set()
    for i, t in enumerate(topics):
        if i in used:
            continue
        cluster = [t]
        used.add(i)
        for j, other in enumerate(topics):
            if j in used:
                continue
            if similarity(t["title"], other["title"]) >= threshold:
                cluster.append(other)
                used.add(j)
        clusters.append(cluster)
    return clusters


def merge_cluster(cluster):
    cluster.sort(key=lambda t: (-len(t["sources"].split(",")), -t["old_score"]))
    best = cluster[0]

    all_sources = set()
    for t in cluster:
        for s in t["sources"].split(","):
            all_sources.add(s.strip())

    urls = []
    for t in cluster:
        if t.get("url"):
            is_reddit = "reddit.com" in t["url"] or "redd.it" in t["url"]
            urls.append((t["url"], not is_reddit, t["old_score"]))
    urls.sort(key=lambda x: (x[1], x[2]), reverse=True)
    best_url = urls[0][0] if urls else None

    volume = len(cluster)
    max_old_score = max(t["old_score"] for t in cluster)
    titles = list(set(t["title"] for t in cluster))

    # Source authority weights
    SOURCE_WEIGHTS = {
        "rss": 3.0,        # Published articles (TechCrunch, Verge, official blogs)
        "gmail": 2.5,      # Newsletters, Google Alerts
        "twitter": 3.0,    # Official announcements
        "youtube": 2.5,    # Video content (Matt Wolfe, AI Jason, etc.)
        "hackernews": 2.5, # HN trending (high signal, catches X/Twitter buzz)
        "reddit": 1.0,     # Community discussion
    }

    # Calculate weighted source score
    source_authority = 0
    for s in all_sources:
        s = s.strip().lower()
        source_authority += SOURCE_WEIGHTS.get(s, 1.0)

    # Cap Reddit volume contribution (diminishing returns after 5)
    import math
    effective_volume = min(volume, 5) + math.log2(max(volume - 4, 1))

    # Combined signal: authority × effective_volume × base_score
    combined_signal = source_authority * effective_volume * max_old_score

    return {
        "title": best["title"],
        "sources": ",".join(sorted(all_sources)),
        "source_count": len(all_sources),
        "volume": volume,
        "old_score": round(max_old_score, 1),
        "combined_signal": round(combined_signal, 1),
        "url": best_url,
        "all_titles": titles[:5],
        "seen": best["seen"]
    }



def get_trend_history(title, conn):
    """Get mention count over 1d, 3d, 7d windows."""
    from dump_topics import normalize, extract_entities
    c = conn.cursor()
    entities = extract_entities(title)
    
    counts = {}
    for days, label in [(1, "24h"), (3, "3d"), (7, "7d")]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        c.execute("SELECT title FROM topic WHERE last_seen >= ?", (cutoff,))
        count = 0
        for (t,) in c.fetchall():
            t_entities = extract_entities(t)
            if entities & t_entities:  # Shared entities
                count += 1
        counts[label] = count
    
    # Trend direction
    if counts["24h"] > 0 and counts["3d"] > counts["24h"] * 2:
        trend = "rising"
    elif counts["7d"] > counts["3d"] * 2:
        trend = "established"
    else:
        trend = "new"
    
    return {"mentions_24h": counts["24h"], "mentions_3d": counts["3d"], 
            "mentions_7d": counts["7d"], "trend": trend}


def load_youtube_items():
    """Load YouTube items from collector file if recent."""
    import os
    yt_path = os.environ.get("YOUTUBE_DATA_PATH", "/data/youtube_latest.json")
    if not os.path.exists(yt_path):
        return []
    try:
        # Only use if file is less than 24h old
        mtime = os.path.getmtime(yt_path)
        age_hours = (datetime.now(timezone.utc).timestamp() - mtime) / 3600
        if age_hours > 24:
            return []
        with open(yt_path) as f:
            items = json.load(f)
        return [{"title": it["title"], "old_score": 1.5, "sources": "youtube",
                 "url": it["url"], "seen": datetime.now(timezone.utc).isoformat()}
                for it in items if it.get("title")]
    except Exception:
        return []


def dump():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    c.execute("""
        SELECT title, score, sources, url, last_seen
        FROM topic WHERE last_seen >= ?
        ORDER BY score DESC LIMIT 150
    """, (cutoff,))
    raw = [{"title": r[0], "old_score": r[1], "sources": r[2] or "unknown",
            "url": r[3], "seen": r[4]} for r in c.fetchall()]
    
    # Add YouTube items from API collector (filter AI-related only)
    yt_items = load_youtube_items()
    import sys
    sys.path.insert(0, "/root/src")
    try:
        from ai_trend_monitor.collectors.reddit import is_ai_related
        AI_CHANNELS = {"Matt Wolfe", "AI Jason", "All About AI", "Matthew Berman", "Sam Witteveen"}
        yt_items = [it for it in yt_items 
                    if it.get("channel") in AI_CHANNELS or is_ai_related(it["title"], None)]
    except Exception:
        pass
    if yt_items:
        raw.extend(yt_items)
    
    conn.close()

    clusters = cluster_topics(raw)
    merged = [merge_cluster(cl) for cl in clusters]
    merged.sort(key=lambda t: t["combined_signal"], reverse=True)

    for t in merged[:30]:
        if t["url"] and ("reddit.com" in t["url"] or "redd.it" in t["url"]):
            t["url_status"] = "ok" if check_reddit_url(t["url"]) else "removed"
        else:
            t["url_status"] = "ok"

    print(json.dumps(merged[:50], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    dump()
