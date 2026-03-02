"""Le 5·5·5 — Podcast IA quotidien via ElevenLabs.
5 news majeures, 5 minutes, 55 secondes de résumé.
Total cible : 5:55 (~950 mots)
"""
import json
import subprocess
import os
import tempfile
from datetime import datetime, timezone

# ElevenLabs config
ELEVENLABS_API_KEY = "sk_e3800636056d0ba7e67be07600e90befb12534949b0d4c59"
VOICE_ID = "xKyP421sZ7DcSEin6DhE"  # Florent's cloned voice
MODEL_ID = "eleven_v3"
OUTPUT_DIR = os.environ.get("PODCAST_OUTPUT_DIR", "/podcasts")


def get_top_news(n=5):
    """Get top N news from dump_topics."""
    result = subprocess.run(
        ["python3", "/scripts/dump_topics.py"],
        capture_output=True, timeout=30
    )
    topics = json.loads(result.stdout)
    return topics[:n]


def generate_audio(text, output_path):
    """Generate audio via ElevenLabs API."""
    payload = json.dumps({
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.3,
            "use_speaker_boost": True
        }
    })
    
    cmd = [
        "curl", "-s", "-X", "POST",
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        "-H", f"xi-api-key: {ELEVENLABS_API_KEY}",
        "-H", "Content-Type: application/json",
        "-H", "Accept: audio/mpeg",
        "-d", payload,
        "-o", output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    
    # Check if output is valid audio (not an error JSON)
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        if size < 1000:
            with open(output_path, 'r') as f:
                try:
                    error = json.load(f)
                    raise Exception(f"ElevenLabs error: {error}")
                except json.JSONDecodeError:
                    pass
        print(f"Audio generated: {output_path} ({size/1024:.0f} KB)")
        return output_path
    raise Exception("Audio generation failed")


def run():
    """Generate the daily 5·5·5 podcast."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Get news
    news = get_top_news(5)
    if len(news) < 3:
        print("Not enough news for podcast")
        return None
    
    # Build script (~950 words for 5:55)
    script_parts = []
    
    # Intro (~50 words, ~20 sec)
    script_parts.append(
        f"Le 5·5·5, votre digest IA quotidien. "
        f"5 news majeures, 5 minutes pour tout comprendre, "
        f"et 55 secondes de résumé à la fin. "
        f"C'est parti pour l'édition du {_french_date(today)}."
    )
    
    # 5 news (~150 words each, ~55 sec each = ~4:35)
    for i, topic in enumerate(news, 1):
        title = topic["title"]
        sources = topic["sources"]
        signal = topic.get("combined_signal", 0)
        url = topic.get("url", "")
        volume = topic.get("volume", 1)
        
        # Determine source context
        src_list = [s.strip() for s in sources.split(",")]
        if len(src_list) > 1:
            buzz = f"Le sujet fait du bruit sur {' et '.join(src_list)}"
        else:
            buzz = f"Repéré sur {src_list[0]}"
        
        script_parts.append(
            f"News numéro {i}. {title}. {buzz}, "
            f"avec un signal d'impact de {signal:.0f}. "
        )
    
    # Recap (~130 words, ~55 sec)
    recap_items = [f"numéro {i+1}, {n['title']}" for i, n in enumerate(news)]
    script_parts.append(
        "Et maintenant le récap en 55 secondes. "
        "Les 5 actus à retenir aujourd'hui : "
        + ". ".join(recap_items) + ". "
        "C'était le 5·5·5, votre dose quotidienne d'intelligence artificielle. "
        "À demain !"
    )
    
    script = "\n\n".join(script_parts)
    print(f"Script: {len(script.split())} words")
    print("---")
    print(script)
    print("---")
    
    # Generate audio
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"555_{today}.mp3")
    generate_audio(script, output_path)
    
    # Check duration
    try:
        dur_cmd = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", output_path],
            capture_output=True, timeout=10
        )
        duration = float(dur_cmd.stdout.decode().strip())
        mins = int(duration // 60)
        secs = int(duration % 60)
        print(f"Duration: {mins}:{secs:02d}")
    except Exception:
        print("Could not check duration")
    
    return output_path


def _french_date(date_str):
    """Convert YYYY-MM-DD to French date."""
    months = ["janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


if __name__ == "__main__":
    path = run()
    if path:
        print(f"\nReady: {path}")
