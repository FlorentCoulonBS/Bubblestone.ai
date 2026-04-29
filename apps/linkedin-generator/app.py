#!/usr/bin/env python3
"""LinkedIn Post Generator — linkedin.bubblestone.ai"""

import os
import json
import base64
import hmac
from datetime import datetime
from functools import wraps
from pathlib import Path

import requests

from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, session, send_from_directory, flash)
from models import (init_db, get_posts, get_post, update_post_text,
                    update_post_status, update_post_image, get_post_counts,
                    create_post, get_post_by_topic_id, IMAGES_DIR)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex()

LOGIN_USER = os.environ.get("LOGIN_USER") or "florent"
LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD") or "Bricks2026!AI"
INTERNAL_SECRET = os.environ.get("SECRET_KEY", "")
PUBLIC_BASE_URL = os.environ.get("LINKEDIN_PUBLIC_BASE_URL", "https://linkedin.bubblestone.ai")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = "gpt-image-2"


# --- Auth ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "")
        pwd = request.form.get("password", "")
        if user == LOGIN_USER and pwd == LOGIN_PASSWORD:
            session["logged_in"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
        flash("Identifiants incorrects", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --- Dashboard ---

@app.route("/")
@login_required
def dashboard():
    status = request.args.get("status")
    date = request.args.get("date")
    posts = get_posts(status=status, date=date, limit=100)
    counts = get_post_counts()
    return render_template("dashboard.html", posts=posts, counts=counts,
                           current_status=status, current_date=date)


@app.route("/post/<int:post_id>")
@login_required
def post_detail(post_id):
    post = get_post(post_id)
    if not post:
        flash("Post introuvable", "error")
        return redirect(url_for("dashboard"))
    return render_template("post_detail.html", post=post)


# --- API ---

@app.route("/api/post/<int:post_id>/update", methods=["POST"])
@login_required
def api_update_text(post_id):
    data = request.get_json()
    text = data.get("post_text", "").strip()
    if not text:
        return jsonify({"error": "Texte vide"}), 400
    update_post_text(post_id, text)
    return jsonify({"ok": True, "chars": len(text)})


@app.route("/api/post/<int:post_id>/validate", methods=["POST"])
@login_required
def api_validate(post_id):
    post = get_post(post_id)
    if not post:
        return jsonify({"error": "Post introuvable"}), 404

    # Generate image
    image_path = None
    error = None
    if post["image_prompt"] and OPENAI_API_KEY:
        try:
            image_path = generate_image(post_id, post["image_prompt"])
        except Exception as e:
            error = f"Image generation failed: {e}"

    update_post_status(post_id, "validated")
    if image_path:
        update_post_image(post_id, image_path)

    return jsonify({"ok": True, "image_path": image_path, "error": error})


@app.route("/api/post/<int:post_id>/reject", methods=["POST"])
@login_required
def api_reject(post_id):
    update_post_status(post_id, "rejected")
    return jsonify({"ok": True})


@app.route("/api/post/<int:post_id>/publish", methods=["POST"])
@login_required
def api_publish(post_id):
    update_post_status(post_id, "published")
    return jsonify({"ok": True})


@app.route("/api/post/<int:post_id>/regenerate-image", methods=["POST"])
@login_required
def api_regenerate_image(post_id):
    post = get_post(post_id)
    if not post:
        return jsonify({"error": "Post introuvable"}), 404

    data = request.get_json() or {}
    prompt = data.get("image_prompt", post["image_prompt"])

    if not prompt:
        return jsonify({"error": "Pas de prompt image"}), 400

    try:
        image_path = generate_image(post_id, prompt)
        update_post_image(post_id, image_path)
        return jsonify({"ok": True, "image_path": image_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _internal_authorized():
    sent = request.headers.get("X-Internal-Secret", "")
    return bool(INTERNAL_SECRET) and hmac.compare_digest(sent, INTERNAL_SECRET)


def _build_linkedin_draft(topic):
    title = (topic.get("title") or "").strip()
    sources = (topic.get("sources") or "veille").strip()
    score = topic.get("score")
    score_line = f"Signal veille: {score:.1f}." if isinstance(score, (int, float)) else "Signal veille a qualifier."

    post_text = (
        f"{title}\n\n"
        "Ce signal merite attention parce qu'il touche directement la facon dont les equipes vont produire, "
        "automatiser ou arbitrer leurs outils IA dans les prochains jours.\n\n"
        f"{score_line} Sources detectees: {sources}.\n\n"
        "Mon angle de lecture: verifier si c'est une annonce cosmetique ou un vrai changement d'usage, "
        "puis identifier ce que cela change concretement pour une equipe commerciale, marketing ou operationnelle.\n\n"
        "A surveiller: adoption reelle, limites techniques, cout total et impact sur les workflows existants."
    )
    image_prompt = (
        "Scene realiste en photographie editoriale: une equipe professionnelle dans un bureau moderne analyse "
        "un tableau de veille IA sur de grands ecrans, ambiance business sobre, lumiere naturelle, "
        "details credibles, aucune interface lisible, aucun texte incruste."
    )
    return post_text, image_prompt


@app.route("/api/intake-topic", methods=["POST"])
def api_intake_topic():
    if not _internal_authorized():
        return jsonify({"error": "Non autorise"}), 401

    topic = request.get_json(silent=True) or {}
    topic_id = str(topic.get("id") or topic.get("topic_id") or "").strip()
    title = (topic.get("title") or "").strip()
    if not topic_id or not title:
        return jsonify({"error": "Topic incomplet"}), 400

    existing = get_post_by_topic_id(topic_id)
    if existing:
        return jsonify({
            "ok": True,
            "created": False,
            "post_id": existing["id"],
            "post_url": f"{PUBLIC_BASE_URL}/post/{existing['id']}",
        })

    post_text, image_prompt = _build_linkedin_draft(topic)
    try:
        score = float(topic["score"]) if topic.get("score") is not None else None
    except (TypeError, ValueError):
        score = None
    post_id = create_post(
        topic_title=title,
        post_text=post_text,
        image_prompt=image_prompt,
        topic_id=topic_id,
        topic_url=topic.get("url"),
        topic_score=score,
        article_md=json.dumps(topic, ensure_ascii=False, indent=2),
        sources=topic.get("sources"),
    )
    return jsonify({
        "ok": True,
        "created": True,
        "post_id": post_id,
        "post_url": f"{PUBLIC_BASE_URL}/post/{post_id}",
    })


@app.route("/images/<path:filename>")
@login_required
def serve_image(filename):
    return send_from_directory(IMAGES_DIR, filename)


# --- Image Generation ---

def generate_image(post_id, prompt):
    """Generate image using OpenAI gpt-image-2.

    Returns the saved filename (no path), suitable for storage in posts.image_path.
    Raises requests.HTTPError or ValueError on failure — caller handles.
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")

    full_prompt = (
        "Photorealistic editorial photograph for a LinkedIn post. "
        "Style: photojournalism, magazine quality, dramatic natural lighting, "
        "shallow depth of field, no AI-cartoonish look, no text overlay. "
        f"Subject: {prompt}"
    )

    payload = {
        "model": OPENAI_IMAGE_MODEL,
        "prompt": full_prompt,
        "size": "1024x1024",
        "quality": "high",
        "n": 1,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    r = requests.post(
        "https://api.openai.com/v1/images/generations",
        json=payload,
        headers=headers,
        timeout=120,
    )
    r.raise_for_status()

    b64 = r.json()["data"][0]["b64_json"]
    img_bytes = base64.b64decode(b64)

    filename = f"post_{post_id}_{datetime.utcnow():%Y%m%d_%H%M%S}.png"
    Path(IMAGES_DIR).mkdir(parents=True, exist_ok=True)
    (Path(IMAGES_DIR) / filename).write_bytes(img_bytes)
    return filename


# --- Init ---

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=os.environ.get("DEBUG", "0") == "1")
