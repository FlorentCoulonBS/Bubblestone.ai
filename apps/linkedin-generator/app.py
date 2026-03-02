#!/usr/bin/env python3
"""LinkedIn Post Generator — linkedin.bubblestone.ai"""

import os
import json
import base64
import urllib.request
import urllib.parse
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, session, send_from_directory, flash)
from models import (init_db, get_posts, get_post, update_post_text,
                    update_post_status, update_post_image, get_post_counts,
                    IMAGES_DIR)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex()

LOGIN_USER = os.environ.get("LOGIN_USER") or "florent"
LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD") or "Bricks2026!AI"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or ""
GEMINI_MODEL = "gemini-3.1-flash-image-preview"


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
    if post["image_prompt"] and GEMINI_API_KEY:
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


@app.route("/images/<path:filename>")
@login_required
def serve_image(filename):
    return send_from_directory(IMAGES_DIR, filename)


# --- Image Generation ---

def generate_image(post_id, prompt):
    """Generate image using Nano Banana 2 (Gemini API)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    full_prompt = (
        f"Generate a photorealistic editorial photograph for a LinkedIn post. "
        f"Style: photojournalism, magazine quality, shot on Canon R5, dramatic lighting, "
        f"shallow depth of field. NO cartoon, NO illustration, NO AI-generated look. "
        f"Aspect ratio 1200x627 (landscape). Subject: {prompt}"
    )

    payload = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}
    }).encode()

    req = urllib.request.Request(url, data=payload,
                                headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read())

    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        if "inlineData" in part:
            img_data = base64.b64decode(part["inlineData"]["data"])
            mime = part["inlineData"].get("mimeType", "image/png")
            ext = "png" if "png" in mime else "jpg"
            filename = f"post_{post_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
            filepath = os.path.join(IMAGES_DIR, filename)
            os.makedirs(IMAGES_DIR, exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(img_data)
            return filename

    raise Exception("No image returned by Gemini API")


# --- Init ---

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=os.environ.get("DEBUG", "0") == "1")
