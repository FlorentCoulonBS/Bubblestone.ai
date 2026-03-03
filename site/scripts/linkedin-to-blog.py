#!/usr/bin/env python3
"""
LinkedIn → Blog Pipeline
Converts a validated LinkedIn post into a full blog article.

Usage:
  python3 linkedin-to-blog.py --title "Title" --text "LinkedIn post content" --tags "tag1,tag2"
  
Or via stdin (JSON):
  echo '{"title":"...","text":"...","tags":["a","b"]}' | python3 linkedin-to-blog.py --stdin

Requires: ANTHROPIC_API_KEY env var
Writes to: ../src/content/blog/<slug>.md
Then: git add, commit, push
"""

import os
import sys
import json
import re
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent
BLOG_DIR = SITE_DIR / "src" / "content" / "blog"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-20250514"


def slugify(text: str) -> str:
    """Generate URL-safe slug from title."""
    text = text.lower().strip()
    # Remove accents (basic)
    replacements = {
        'à': 'a', 'â': 'a', 'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'î': 'i', 'ï': 'i', 'ô': 'o', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'œ': 'oe', 'æ': 'ae'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text.strip('-')[:80]


def generate_article(title: str, linkedin_text: str, tags: list[str]) -> str:
    """Call Claude to expand LinkedIn post into a full blog article."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    prompt = f"""Tu es un rédacteur expert en IA et transformation digitale pour le blog de BubbleStone AI (bubblestone.ai).

À partir du post LinkedIn ci-dessous, génère un article de blog complet en français.

RÈGLES :
- 1500-2500 mots
- Ton professionnel mais accessible, direct, pas de bullshit
- Structure : intro answer-first (répondre à la question dès les premières lignes), puis développement avec H2/H3
- Ajouter une section FAQ avec 3-4 questions en H3 à la fin
- Inclure des exemples concrets, chiffres si pertinent
- Terminer par un CTA vers [Contactez-nous](https://bubblestone.ai/#contact)
- Ne PAS mettre de titre H1 (il est géré par le template)
- Ne PAS inclure de frontmatter
- Format Markdown pur

POST LINKEDIN :
---
{linkedin_text}
---

Titre de l'article : {title}
Tags : {', '.join(tags)}"""

    payload = json.dumps({
        "model": MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01"
        }
    )

    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())

    content = data.get("content", [{}])
    for block in content:
        if block.get("type") == "text":
            return block["text"]

    raise Exception(f"No text in Claude response: {data}")


def create_blog_post(title: str, description: str, article_body: str,
                     tags: list[str], linkedin_url: str = "") -> Path:
    """Write the markdown file for Astro Content Collections."""
    slug = slugify(title)
    filepath = BLOG_DIR / f"{slug}.md"

    today = datetime.now().strftime("%Y-%m-%d")
    tags_yaml = json.dumps(tags, ensure_ascii=False)

    frontmatter = f"""---
title: "{title}"
description: "{description}"
date: {today}
author: "Florent Coulon"
image: ""
tags: {tags_yaml}
linkedin: "{linkedin_url}"
draft: false
---"""

    filepath.write_text(f"{frontmatter}\n\n{article_body}", encoding="utf-8")
    print(f"✅ Article written: {filepath}")
    return filepath


def git_push(filepath: Path, title: str):
    """Git add, commit, push the new article."""
    repo_dir = SITE_DIR.parent  # /opt/bubblestone/src
    
    subprocess.run(["git", "add", str(filepath)], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"blog: {title}"],
        cwd=repo_dir, check=True
    )
    subprocess.run(
        ["git", "push", "origin", "master"],
        cwd=repo_dir, check=True, timeout=30
    )
    print("✅ Pushed to GitHub → staging deploy triggered")


def main():
    if "--stdin" in sys.argv:
        data = json.loads(sys.stdin.read())
    else:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--title", required=True)
        parser.add_argument("--text", required=True)
        parser.add_argument("--tags", default="")
        parser.add_argument("--description", default="")
        parser.add_argument("--linkedin-url", default="")
        parser.add_argument("--no-push", action="store_true")
        args = parser.parse_args()
        data = {
            "title": args.title,
            "text": args.text,
            "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
            "description": args.description,
            "linkedin_url": args.linkedin_url,
            "no_push": args.no_push
        }

    title = data["title"]
    text = data["text"]
    tags = data.get("tags", [])
    description = data.get("description", "")
    linkedin_url = data.get("linkedin_url", "")
    no_push = data.get("no_push", False)

    if not description:
        # Use first 160 chars of the LinkedIn post as description
        description = text[:157].rsplit(" ", 1)[0] + "..." if len(text) > 160 else text

    print(f"📝 Generating article: {title}")
    print(f"   Tags: {tags}")

    article_body = generate_article(title, text, tags)
    filepath = create_blog_post(title, description, article_body, tags, linkedin_url)

    if not no_push:
        git_push(filepath, title)
    else:
        print("⏭️  --no-push: skipping git push")

    print("🎉 Done!")


if __name__ == "__main__":
    main()
