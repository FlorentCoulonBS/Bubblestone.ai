"""Collect latest videos from AI YouTube channels via YouTube Data API v3."""
import json
import subprocess
import html
from datetime import datetime, timedelta, timezone

YT_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyAey_Zav8-Eof5GGldNCpifzk40wIlikhQ")
OUTPUT_PATH = os.environ.get("YT_OUTPUT_PATH", "/memory/youtube_latest.json")

# Channel handles -> we resolve IDs first, then cache
CHANNELS = {
    "Matt Wolfe": "UChpleBmo18P08aKCIgti38g",
    "All About AI": None,
    "AI Jason": None,
    "Sam Witteveen": None,
    "Greg Isenberg": None,
    # "Le SamourAI": None,  # Geopolitics, not AI
    "Matthew Berman": "UCawZsQWqfGSbCI5yjkdVkTA",
}

CHANNEL_CACHE = os.environ.get("YT_CHANNEL_CACHE", "/memory/youtube_channels.json")


def api_call(endpoint, params):
    import urllib.request, urllib.parse
    params["key"] = YT_API_KEY
    qs = urllib.parse.urlencode(params)
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{qs}"
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except Exception as e:
        print(f"API error: {e}")
        return {"items": []}


def resolve_channel_id(name):
    """Search for channel by name and return channel ID."""
    data = api_call("search", {
        "part": "snippet", "q": name, "type": "channel", "maxResults": 1
    })
    items = data.get("items", [])
    if items:
        return items[0]["id"]["channelId"]
    return None


def load_channel_cache():
    try:
        with open(CHANNEL_CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_channel_cache(cache):
    with open(CHANNEL_CACHE, "w") as f:
        json.dump(cache, f, indent=2)


def get_latest_videos(channel_id, channel_name, max_results=5):
    """Get latest videos from a channel."""
    data = api_call("search", {
        "part": "snippet",
        "channelId": channel_id,
        "order": "date",
        "maxResults": str(max_results),
        "type": "video",
    })
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    videos = []
    
    for item in data.get("items", []):
        s = item["snippet"]
        published = datetime.fromisoformat(s["publishedAt"].replace("Z", "+00:00"))
        if published < cutoff:
            continue
        
        title = html.unescape(s.get("title", ""))
        vid = item["id"]["videoId"]
        
        videos.append({
            "title": title,
            "url": f"https://youtube.com/watch?v={vid}",
            "channel": channel_name,
            "source": "youtube",
            "published": s["publishedAt"],
            "thumbnail": s.get("thumbnails", {}).get("high", {}).get("url", ""),
        })
    
    return videos


def collect():
    # Load/resolve channel IDs
    cache = load_channel_cache()
    
    for name, cid in CHANNELS.items():
        if cid:
            cache[name] = cid
        elif name not in cache:
            resolved = resolve_channel_id(name)
            if resolved:
                cache[name] = resolved
                print(f"Resolved {name} -> {resolved}")
    
    save_channel_cache(cache)
    
    # Collect videos
    all_videos = []
    for name, cid in cache.items():
        if not cid:
            continue
        try:
            videos = get_latest_videos(cid, name)
            all_videos.extend(videos)
            print(f"✅ {name}: {len(videos)} videos")
        except Exception as e:
            print(f"❌ {name}: {e}")
    
    # Sort by date
    all_videos.sort(key=lambda v: v.get("published", ""), reverse=True)
    
    # Save
    with open(OUTPUT_PATH, "w") as f:
        json.dump(all_videos, f, indent=2, ensure_ascii=False)
    
    print(f"\nTotal: {len(all_videos)} videos saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    collect()
