# Veille → LinkedIn + gpt-image-2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre depuis veille.bubblestone.ai de valider un article qui devient un post LinkedIn draft (texte généré par Claude Opus), avec génération d'image manuelle via OpenAI gpt-image-2.

**Architecture:** Bouton "Valider pour LinkedIn" sur veille → POST interne sur `bubblestone-net` vers linkedin → Claude Opus 4.7 génère post_text+image_prompt+article_md → INSERT DB linkedin status=proposed. Côté linkedin, retrait Gemini, bascule complète vers gpt-image-2. Pas de check d'auth applicatif (sécurité = ACL NPM en amont, cf. spec section 5).

**Tech Stack:** Python 3.11+ Flask, Anthropic SDK, OpenAI Images API (via `requests`), SQLite, Docker Compose, Nginx Proxy Manager.

**Spec source:** [docs/superpowers/specs/2026-04-28-veille-to-linkedin-design.md](../specs/2026-04-28-veille-to-linkedin-design.md)

**Tests:** Pas de framework de tests automatisés sur ces 2 apps. Validation par tests manuels (`curl` + `sqlite3` + screenshot Playwright). Chaque tâche définit explicitement la commande de validation et la sortie attendue.

---

## File map

**Created:**
- `apps/linkedin-generator/llm.py` — Helper Anthropic Claude pour générer post depuis topic.

**Modified:**
- `apps/linkedin-generator/requirements.txt` — Ajout `requests`, `anthropic`.
- `apps/linkedin-generator/app.py` — Nouvelle route `/api/topic/from-veille`, retrait génération auto image dans `/validate`, `generate_image()` switch Gemini → gpt-image-2, retrait `GEMINI_*`.
- `apps/linkedin-generator/templates/post_detail.html` — Bouton "Valider + Générer image" devient "Valider" (sans génération).
- `apps/linkedin-generator/BRIEF.md` — Mise à jour mention Gemini → OpenAI gpt-image-2.
- `apps/555-trend-monitor/ai_trend_monitor/web/app.py` — Nouvelle route `/api/validate-topic/<id>`.
- `apps/555-trend-monitor/ai_trend_monitor/web/templates/dashboard.html` — Bouton "Valider pour LinkedIn".
- `apps/555-trend-monitor/ai_trend_monitor/web/templates/topic_detail.html` — Bouton "Valider pour LinkedIn".

**Untouched (statu quo):**
- `infra/docker-compose.yml` — pas besoin (les 2 services sont déjà sur `bubblestone-net`).
- DB schema (`linkedin.db`, `trends.db`) — aucune migration.

---

## Pre-requisites (côté Florent, hors plan)

À faire **avant** la Tâche 1, sinon les tests Tâche 4+ échoueront :

- [ ] `OPENAI_API_KEY=sk-...` ajoutée dans `/opt/bubblestone-config/.env` (déjà fait le 2026-04-28).
- [ ] `ANTHROPIC_API_KEY=sk-ant-...` confirmée présente dans `/opt/bubblestone-config/.env` (déjà là, vérifié `docker exec bubblestone-linkedin-generator env | grep ANTHROPIC` → `=set`).
- [ ] (Optionnel) Retirer `GEMINI_API_KEY` du `.env` après Tâche 7 — pas critique, juste du cleanup.

---

## Task 1: Ajouter dépendances Python (anthropic + requests) au container linkedin

**Files:**
- Modify: `apps/linkedin-generator/requirements.txt`

- [ ] **Step 1: Mettre à jour requirements.txt**

Remplacer le contenu complet par :

```
flask==3.1.3
gunicorn==25.3.0
requests>=2.31,<3
anthropic>=0.40,<1
```

- [ ] **Step 2: Vérifier que le rebuild local du container réussit**

```bash
cd /opt/repos/bubblestone/infra
docker compose -p bubblestone build linkedin-generator
```

Expected output: `Successfully built ...` ou `=> => exporting layers ... DONE`. Pas d'erreur de résolution pip.

- [ ] **Step 3: Commit**

```bash
cd /opt/repos/bubblestone
git add apps/linkedin-generator/requirements.txt
git commit -m "deps(linkedin): add anthropic + requests for Claude/OpenAI calls

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Switch generate_image Gemini → OpenAI gpt-image-2

**Files:**
- Modify: `apps/linkedin-generator/app.py` (fonction `generate_image` lignes ~159-200, et imports en tête de fichier, et la constante `GEMINI_MODEL`/`GEMINI_API_KEY`)

- [ ] **Step 1: Lire le contenu actuel pour situer les modifs**

```bash
sed -n '1,40p' /opt/repos/bubblestone/apps/linkedin-generator/app.py
sed -n '155,210p' /opt/repos/bubblestone/apps/linkedin-generator/app.py
```

Note les numéros de lignes exacts pour `GEMINI_MODEL`, `GEMINI_API_KEY`, et la fonction `generate_image`.

- [ ] **Step 2: Modifier les imports en tête de fichier**

Trouver le bloc d'imports (lignes 1-15). Ajouter (s'ils n'y sont pas déjà) :

```python
import base64
import os
from datetime import datetime
from pathlib import Path
import requests
```

Retirer tout import `google.generativeai` ou similaire si présent (probablement aucun, l'appel Gemini se faisait en HTTP brut via `urllib`).

- [ ] **Step 3: Remplacer les constantes Gemini par OpenAI**

Trouver la ligne `GEMINI_MODEL = "gemini-3.1-flash-image-preview"` (~ligne 24) et la ligne où `GEMINI_API_KEY` est lue (`os.environ.get("GEMINI_API_KEY")`).

Remplacer ces 2 lignes par :

```python
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = "gpt-image-2"
```

- [ ] **Step 4: Réécrire la fonction `generate_image`**

Remplacer **tout le corps** de la fonction `generate_image` (de `def generate_image(post_id, prompt):` jusqu'à la fin de la fonction, identifiée par le retour) par :

```python
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
```

- [ ] **Step 5: Vérifier qu'il ne reste plus aucune référence Gemini dans `app.py`**

```bash
grep -niE "gemini|nano.banana|generativelanguage" /opt/repos/bubblestone/apps/linkedin-generator/app.py
```

Expected output: vide (no match).

- [ ] **Step 6: Build + redéployer le container**

```bash
cd /opt/repos/bubblestone/infra
docker compose -p bubblestone build linkedin-generator
docker compose -p bubblestone up -d linkedin-generator
sleep 3
docker ps --filter name=bubblestone-linkedin-generator --format "table {{.Names}}\t{{.Status}}"
```

Expected: `Up X seconds`.

- [ ] **Step 7: Test manuel `regenerate-image` sur un post existant**

D'abord identifier un post sans image actuelle :

```bash
sqlite3 /opt/bubblestone-linkedin-data/linkedin.db "SELECT id, image_prompt FROM posts WHERE (image_path IS NULL OR image_path='') AND image_prompt IS NOT NULL AND image_prompt != '' LIMIT 1;"
```

Puis se connecter à linkedin (UI), aller sur le post, cliquer "Générer l'image". Attendre ~30-60s. Vérifier qu'une image s'affiche.

Vérification SQL :

```bash
sqlite3 /opt/bubblestone-linkedin-data/linkedin.db "SELECT id, image_path FROM posts WHERE id=<ID_POST>;"
```

Expected: `image_path` = `post_<ID>_<TIMESTAMP>.png`.

```bash
ls -la /opt/bubblestone-linkedin-data/images/ | tail -3
```

Expected: nouveau fichier `.png` daté de la minute.

- [ ] **Step 8: Commit**

```bash
cd /opt/repos/bubblestone
git add apps/linkedin-generator/app.py
git commit -m "feat(linkedin): switch image gen Gemini -> OpenAI gpt-image-2

- New OPENAI_API_KEY + OPENAI_IMAGE_MODEL='gpt-image-2' constants.
- generate_image() uses requests.post(.../v1/images/generations),
  decodes b64_json into PNG, writes to IMAGES_DIR.
- Drops GEMINI_API_KEY/GEMINI_MODEL completely.
- quality=high (editorial), size=1024x1024.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Retirer la génération auto d'image dans /api/post/<id>/validate

**Files:**
- Modify: `apps/linkedin-generator/app.py` route `api_validate` (lignes ~93-115)
- Modify: `apps/linkedin-generator/templates/post_detail.html` (bouton ligne ~99)

- [ ] **Step 1: Localiser la route validate**

```bash
sed -n '93,120p' /opt/repos/bubblestone/apps/linkedin-generator/app.py
```

Note les lignes exactes du corps de la fonction `api_validate(post_id)`.

- [ ] **Step 2: Réécrire la route validate**

Remplacer **tout le corps** de la fonction `api_validate(post_id)` (du `def api_validate(post_id):` jusqu'à `return jsonify(...)` inclus) par :

```python
def api_validate(post_id):
    post = get_post(post_id)
    if not post:
        return jsonify({"error": "Post introuvable"}), 404

    update_post_status(post_id, "validated")
    return jsonify({"ok": True})
```

- [ ] **Step 3: Mettre à jour le bouton dans `post_detail.html`**

Trouver la ligne (~99) :

```html
<button class="btn btn-primary btn-full" onclick="validatePost({{ post.id }}, true)" id="validateBtn">✅ Valider + Générer image</button>
```

La remplacer par :

```html
<button class="btn btn-primary btn-full" onclick="validatePost({{ post.id }}, false)" id="validateBtn">✅ Valider</button>
```

(Le `false` sur le 2e arg signifie "ne pas générer image". Le JS existant `validatePost(id, withImage)` lit ce flag et n'affiche plus le spinner image. Vérifier le JS dans `<script>` du template — si la signature a changé, ajuster.)

- [ ] **Step 4: Vérifier le JS validatePost**

```bash
grep -A 20 "function validatePost" /opt/repos/bubblestone/apps/linkedin-generator/templates/post_detail.html
```

Si le JS appelle systématiquement la génération d'image côté client (par exemple un spinner "Génération de l'image..."), simplifier pour qu'il ne fasse qu'un POST `/api/post/<id>/validate` et un reload. Exemple cible :

```javascript
async function validatePost(id, withImage) {
  const btn = document.getElementById('validateBtn');
  btn.disabled = true;
  btn.textContent = 'Validation...';
  try {
    const r = await fetch('/api/post/' + id + '/validate', {method: 'POST'});
    const data = await r.json();
    if (data.ok) {
      window.location.reload();
    } else {
      alert(data.error || 'Erreur');
      btn.disabled = false;
      btn.textContent = '✅ Valider';
    }
  } catch (e) {
    alert('Erreur réseau: ' + e);
    btn.disabled = false;
  }
}
```

(Adapter à la lib JS utilisée — si pas de fetch, utiliser ce qui est déjà là.)

- [ ] **Step 5: Build + redéployer**

```bash
cd /opt/repos/bubblestone/infra
docker compose -p bubblestone build linkedin-generator
docker compose -p bubblestone up -d linkedin-generator
```

- [ ] **Step 6: Test manuel "Valider" sans génération d'image**

Identifier un post `proposed` sans image :

```bash
sqlite3 /opt/bubblestone-linkedin-data/linkedin.db "SELECT id FROM posts WHERE status='proposed' AND (image_path IS NULL OR image_path='') LIMIT 1;"
```

Sur l'UI linkedin, cliquer "Valider" sur ce post. Vérifier :

```bash
sqlite3 /opt/bubblestone-linkedin-data/linkedin.db "SELECT id, status, image_path FROM posts WHERE id=<ID>;"
```

Expected: `status=validated`, `image_path` reste vide. Confirmer qu'aucun nouveau fichier `images/` n'a été créé pendant ce clic :

```bash
ls -la /opt/bubblestone-linkedin-data/images/ | wc -l
```

(Compteur identique à avant le clic.)

- [ ] **Step 7: Commit**

```bash
cd /opt/repos/bubblestone
git add apps/linkedin-generator/app.py apps/linkedin-generator/templates/post_detail.html
git commit -m "feat(linkedin): /validate no longer auto-generates image

Florent will click 'Générer image' separately. Splits the concerns:
validation = status flip, image gen = explicit user action.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Helper LLM Anthropic + endpoint /api/topic/from-veille

**Files:**
- Create: `apps/linkedin-generator/llm.py`
- Modify: `apps/linkedin-generator/app.py` (nouvelle route + import)

- [ ] **Step 1: Créer `apps/linkedin-generator/llm.py`**

Contenu complet :

```python
"""LLM helper: turn a veille topic into (post_text, image_prompt, article_md) via Claude Opus."""

import json
import os

from anthropic import Anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """Tu es l'éditeur LinkedIn de Bubblestone, un cabinet d'IA français.

Style:
- Drôle, percutant, sincère.
- Tech accessible, pas imbitable.
- Ton qui sonne humain (pas LinkedIn-bro générique, pas corporate-fluffy).
- Pensé pour l'algo LinkedIn: hook fort en 1ère ligne, paragraphes courts, retours à la ligne fréquents, CTA en fin (question ouverte).

Tu reçois un topic tendance IA (titre + URL + score). Tu produis trois choses:

1. `post_text`: un post LinkedIn de 1200-1800 caractères. Markdown léger autorisé (gras avec **, listes avec -). Hashtags pertinents en fin (3-5 max). Émojis avec parcimonie (0-2 max). Ne pas mentionner Bubblestone par son nom.

2. `image_prompt`: une description courte (1-2 phrases) pour générer une image éditoriale photoréaliste qui illustre le post. Pas de typo, pas de scène trop chargée — un plan visuel fort, type photojournalisme.

3. `article_md`: la version blog du post. Markdown complet avec un H1 en titre, intro accrocheuse, 2-4 sections H2, conclusion. 600-1200 mots. Plus posé et analytique que le post LinkedIn, mais même ton. Pas de mention "ce post LinkedIn".

Tu réponds STRICTEMENT en JSON valide, rien d'autre, avec ces 3 clés exactement: `post_text`, `image_prompt`, `article_md`."""


def generate_post_from_topic(title: str, url: str, score: float, sources: str) -> dict:
    """Call Claude Opus and return {post_text, image_prompt, article_md}.

    Raises anthropic.APIError on API failure, ValueError if JSON parse fails.
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    user_msg = (
        f"Topic à transformer en post LinkedIn + article blog:\n\n"
        f"- Titre: {title}\n"
        f"- URL: {url}\n"
        f"- Score (signal): {score}\n"
        f"- Sources: {sources}\n\n"
        f"Réponds en JSON strict avec post_text, image_prompt, article_md."
    )

    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = resp.content[0].text.strip()

    # Strip code fences if Claude added them despite instructions
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

    data = json.loads(raw)
    for key in ("post_text", "image_prompt", "article_md"):
        if key not in data or not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"LLM response missing or empty key: {key}")
    return data
```

- [ ] **Step 2: Ajouter la route `/api/topic/from-veille` dans `app.py`**

Trouver une bonne emplacement (après `api_publish`, avant `api_regenerate_image`). Ajouter en haut de `app.py` (avec les autres imports) :

```python
from llm import generate_post_from_topic
```

Puis ajouter la nouvelle route. Note: pas de `@login_required`, pas d'auth applicative (cf. spec section 5).

```python
@app.route("/api/topic/from-veille", methods=["POST"])
def api_from_veille():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    url = (data.get("url") or "").strip()
    score = float(data.get("score") or 0.0)
    sources = (data.get("sources") or "").strip()
    topic_id = data.get("topic_id")

    if not title:
        return jsonify({"error": "title required"}), 400

    try:
        gen = generate_post_from_topic(title, url, score, sources)
    except Exception as e:
        return jsonify({"error": f"LLM failed: {e}"}), 502

    post_id = create_post(
        topic_title=title,
        post_text=gen["post_text"],
        image_prompt=gen["image_prompt"],
        topic_id=str(topic_id) if topic_id else None,
        topic_url=url,
        topic_score=score,
        article_md=gen["article_md"],
        sources=sources,
    )

    return jsonify({
        "ok": True,
        "post_id": post_id,
        "post_url": f"/post/{post_id}",
    })
```

- [ ] **Step 3: Vérifier la signature de `create_post` dans `models.py`**

```bash
grep -A 8 "def create_post" /opt/repos/bubblestone/apps/linkedin-generator/models.py
```

Expected: la signature `def create_post(topic_title, post_text, image_prompt, topic_id=None, topic_url=None, topic_score=None, article_md=None, sources=None)` retourne le `post_id` (lastrowid). Si elle ne retourne rien, modifier `models.py` pour ajouter `return cursor.lastrowid` après le commit.

- [ ] **Step 4: Build + redéployer**

```bash
cd /opt/repos/bubblestone/infra
docker compose -p bubblestone build linkedin-generator
docker compose -p bubblestone up -d linkedin-generator
sleep 3
docker logs --tail 20 bubblestone-linkedin-generator
```

Expected: démarrage gunicorn sans `ImportError`.

- [ ] **Step 5: Test manuel — appel direct depuis le réseau Docker**

Depuis le serveur, simuler l'appel que veille fera, en passant par le DNS interne :

```bash
docker exec bubblestone-555 python3 -c "
import requests, json
r = requests.post(
    'http://bubblestone-linkedin-generator:5001/api/topic/from-veille',
    json={
        'topic_id': 999,
        'title': 'Anthropic publie Claude Opus 4.7 avec contexte 1M tokens',
        'url': 'https://www.anthropic.com/news/claude-opus-4-7',
        'score': 8.5,
        'sources': 'hackernews,rss',
    },
    timeout=120,
)
print('status:', r.status_code)
print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:600])
"
```

Expected: `status: 200`, JSON `{"ok": true, "post_id": <N>, "post_url": "/post/<N>"}`.

- [ ] **Step 6: Vérifier en DB**

```bash
sqlite3 -header -column /opt/bubblestone-linkedin-data/linkedin.db "SELECT id, status, length(post_text), length(image_prompt), length(article_md), image_path FROM posts ORDER BY id DESC LIMIT 1;"
```

Expected: `status=proposed`, `length(post_text)` entre 600 et 2500, `length(image_prompt)` 30-400, `length(article_md)` 1500-8000, `image_path` vide.

Inspect du contenu :

```bash
sqlite3 /opt/bubblestone-linkedin-data/linkedin.db "SELECT post_text FROM posts WHERE id=(SELECT MAX(id) FROM posts);" | head -50
```

Expected: texte LinkedIn cohérent en français, ton conforme au BRIEF.md.

- [ ] **Step 7: Test cas d'erreur — body invalide**

```bash
docker exec bubblestone-555 python3 -c "
import requests, json
r = requests.post('http://bubblestone-linkedin-generator:5001/api/topic/from-veille', json={'url': 'x'}, timeout=10)
print(r.status_code, r.json())
"
```

Expected: `400 {'error': 'title required'}`.

- [ ] **Step 8: Commit**

```bash
cd /opt/repos/bubblestone
git add apps/linkedin-generator/llm.py apps/linkedin-generator/app.py
git commit -m "feat(linkedin): /api/topic/from-veille generates post via Claude Opus

- New llm.py with generate_post_from_topic() calling Claude Opus 4.7.
- System prompt enforces ton + JSON-strict response with
  post_text/image_prompt/article_md.
- Route /api/topic/from-veille (no auth, NPM ACL upstream is
  authoritative — cf. spec section 5).
- 502 on LLM failure, Florent re-clicks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Endpoint /api/validate-topic/<id> côté veille (relais HTTP)

**Files:**
- Modify: `apps/555-trend-monitor/ai_trend_monitor/web/app.py`

- [ ] **Step 1: Localiser le bon endroit dans app.py veille**

```bash
grep -nE "@app.route|def " /opt/repos/bubblestone/apps/555-trend-monitor/ai_trend_monitor/web/app.py | head -30
```

Note l'emplacement de `api_dismiss` (route `/api/dismiss/<int:topic_id>`). On va ajouter la nouvelle route juste après.

- [ ] **Step 2: Ajouter les imports nécessaires en tête de fichier**

Vérifier que `requests` et `os` sont importés. Sinon, ajouter en tête :

```python
import os
import requests
```

Vérifier que `requests` est dans le pyproject.toml de 555 :

```bash
grep "requests" /opt/repos/bubblestone/apps/555-trend-monitor/pyproject.toml
```

Expected: `"requests>=2.31",` présent. (Déjà là, vérifié 2026-04-28.)

- [ ] **Step 3: Ajouter la nouvelle route**

Trouver la fin de `api_dismiss` et ajouter après :

```python
LINKEDIN_GENERATOR_URL = os.environ.get(
    "LINKEDIN_GENERATOR_URL",
    "http://bubblestone-linkedin-generator:5001",
)


@app.route("/api/validate-topic/<int:topic_id>", methods=["POST"])
@auth.login_required
def api_validate_topic(topic_id):
    """Forward a topic to linkedin-generator to create a draft post."""
    db = get_db()
    row = db.execute(
        "SELECT id, title, url, score, sources FROM topic WHERE id = ? LIMIT 1",
        (topic_id,),
    ).fetchone()
    if not row:
        return jsonify({"error": "topic introuvable"}), 404

    payload = {
        "topic_id": row["id"],
        "title": row["title"],
        "url": row["url"] or "",
        "score": float(row["score"] or 0.0),
        "sources": row["sources"] or "",
    }

    try:
        r = requests.post(
            f"{LINKEDIN_GENERATOR_URL}/api/topic/from-veille",
            json=payload,
            timeout=120,
        )
    except requests.RequestException as e:
        return jsonify({"error": f"linkedin-generator unreachable: {e}"}), 502

    if r.status_code != 200:
        return jsonify({"error": "linkedin-generator returned " + str(r.status_code), "detail": r.text[:300]}), 502

    data = r.json()
    return jsonify({
        "ok": True,
        "post_id": data.get("post_id"),
        "post_url": f"https://linkedin.bubblestone.ai{data.get('post_url')}",
    })
```

Note : `@auth.login_required` est le décorateur de basic auth déjà utilisé par `api_dismiss`. Vérifier le nom exact dans le fichier — si c'est `@requires_auth` ou autre, utiliser celui-là (cohérence avec les autres routes admin).

```bash
grep "auth.login_required\|@requires_auth\|@auth\." /opt/repos/bubblestone/apps/555-trend-monitor/ai_trend_monitor/web/app.py | head -5
```

- [ ] **Step 4: Build + redéployer le container 555**

```bash
cd /opt/repos/bubblestone/infra
docker compose -p bubblestone build 555
docker compose -p bubblestone up -d 555
sleep 3
docker logs --tail 10 bubblestone-555
```

Expected: gunicorn running, pas d'`ImportError`.

- [ ] **Step 5: Test manuel — relais 555 → linkedin**

Identifier un topic_id réel :

```bash
sqlite3 /opt/bubblestone-555-data/trends.db "SELECT id, title FROM topic WHERE dismissed_at IS NULL ORDER BY score DESC LIMIT 3;"
```

Tester depuis le serveur :

```bash
# Récupérer creds basic auth depuis l'env du container
ADMIN_USER=$(docker exec bubblestone-555 printenv ADMIN_USER 2>/dev/null || echo florent)
ADMIN_PASS=$(docker exec bubblestone-555 printenv ADMIN_PASSWORD 2>/dev/null)

# (Note: adapte ces var names à ce qui est réellement dans l'env du container.
# Si tu ne les retrouves pas, regarde docker exec bubblestone-555 env | grep -i auth)

curl -sS -u "$ADMIN_USER:$ADMIN_PASS" -X POST \
  http://127.0.0.1:5000/api/validate-topic/<TOPIC_ID> | jq
```

Expected: `{"ok": true, "post_id": <N>, "post_url": "https://linkedin.bubblestone.ai/post/<N>"}`.

Vérifier qu'un post a bien été créé :

```bash
sqlite3 /opt/bubblestone-linkedin-data/linkedin.db "SELECT id, status, topic_title FROM posts ORDER BY id DESC LIMIT 1;"
```

- [ ] **Step 6: Commit**

```bash
cd /opt/repos/bubblestone
git add apps/555-trend-monitor/ai_trend_monitor/web/app.py
git commit -m "feat(veille): /api/validate-topic relays topic to linkedin-generator

POSTs the topic title/url/score/sources to bubblestone-linkedin-generator
on the internal Docker network. Returns the post_url for the UI to
redirect/show. 502 on linkedin failure (Florent re-clicks).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Bouton "Valider pour LinkedIn" dans dashboard.html + topic_detail.html

**Files:**
- Modify: `apps/555-trend-monitor/ai_trend_monitor/web/templates/dashboard.html`
- Modify: `apps/555-trend-monitor/ai_trend_monitor/web/templates/topic_detail.html`

- [ ] **Step 1: Modifier dashboard.html — ajouter bouton dans la cellule actions**

Trouver dans `dashboard.html` les boutons `Read`/`Skip` (autour de la ligne 47) :

```html
<button class="dismiss-btn outline secondary" onclick="event.stopPropagation(); dismiss({{ topic.id }}, 'read', this)">Read</button>
<button class="dismiss-btn outline secondary" onclick="event.stopPropagation(); dismiss({{ topic.id }}, 'not_interested', this)">Skip</button>
```

Ajouter **avant** ces 2 boutons un nouveau bouton :

```html
<button class="validate-btn outline" onclick="event.stopPropagation(); validateForLinkedIn({{ topic.id }}, this)">📝 LinkedIn</button>
```

- [ ] **Step 2: Ajouter le JS `validateForLinkedIn` dans le `<script>` de dashboard.html**

Trouver le bloc `<script>` (vers la fin du fichier, après `function dismiss(...)`). Ajouter juste avant `</script>` :

```javascript
async function validateForLinkedIn(topicId, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ Génération...';
  try {
    const r = await fetch('/api/validate-topic/' + topicId, {method: 'POST'});
    const data = await r.json();
    if (r.ok && data.ok) {
      btn.textContent = '✓ ' + 'Voir le post';
      btn.classList.add('contrast');
      btn.onclick = () => window.open(data.post_url, '_blank');
    } else {
      btn.textContent = '⚠ Erreur';
      alert(data.error || 'Échec génération LinkedIn');
      setTimeout(() => { btn.disabled = false; btn.textContent = original; }, 3000);
    }
  } catch (e) {
    btn.textContent = '⚠ Réseau';
    alert('Erreur réseau: ' + e);
    setTimeout(() => { btn.disabled = false; btn.textContent = original; }, 3000);
  }
}
```

- [ ] **Step 3: Modifier topic_detail.html (même bouton + même JS)**

```bash
sed -n '1,80p' /opt/repos/bubblestone/apps/555-trend-monitor/ai_trend_monitor/web/templates/topic_detail.html
```

Trouver l'endroit où sont les boutons Read/Skip (s'ils existent) ou dans un panneau d'actions. Ajouter le même bouton :

```html
<button class="validate-btn outline" onclick="validateForLinkedIn({{ topic.id }}, this)">📝 Valider pour LinkedIn</button>
```

Et le même JS dans le bloc `<script>` du template (ou dans un `static/main.js` partagé si la base le permet — vérifier). Si JS dupliqué dans 2 templates, c'est OK pour ce scope (factorisation = scope creep).

- [ ] **Step 4: Style CSS minimal pour `validate-btn`**

Vérifier où vit le CSS de l'app :

```bash
grep -rn "dismiss-btn" /opt/repos/bubblestone/apps/555-trend-monitor/ai_trend_monitor/web/static/ /opt/repos/bubblestone/apps/555-trend-monitor/ai_trend_monitor/web/templates/ 2>&1 | head -5
```

Si `dismiss-btn` est défini dans un fichier CSS, ajouter dans le même fichier :

```css
.validate-btn {
  background: linear-gradient(135deg, #0a66c2, #084d92);
  color: white;
  border: none;
  font-weight: 600;
}
.validate-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #084d92, #063870);
}
.validate-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}
```

Si `dismiss-btn` n'est défini nulle part (style par défaut Pico CSS), pas besoin de CSS — laisser tomber le step.

- [ ] **Step 5: Build + redéployer**

```bash
cd /opt/repos/bubblestone/infra
docker compose -p bubblestone build 555
docker compose -p bubblestone up -d 555
sleep 3
docker ps --filter name=bubblestone-555 --format "table {{.Names}}\t{{.Status}}"
```

- [ ] **Step 6: Test visuel obligatoire (Règle #4 CLAUDE.md)**

Screenshot avant/après depuis le serveur via Playwright :

```bash
# Récupère le contenu rendu HTML pour vérifier que le bouton est là
curl -sS -u "$ADMIN_USER:$ADMIN_PASS" http://127.0.0.1:5000/ | grep -o "validate-btn" | head -3
```

Expected: au moins 1 occurrence par topic affiché.

Visual screenshot (depuis BubbleStone, Playwright en interne) :

```bash
npx playwright screenshot --browser chromium --full-page --wait-for-timeout 3000 \
  --auth "$ADMIN_USER:$ADMIN_PASS" \
  http://127.0.0.1:5000/ /tmp/veille-after.png

ls -la /tmp/veille-after.png
```

(Si `--auth` n'est pas supporté par le wrapper, passer par un script playwright dédié — voir CLAUDE.md.)

Comparer visuellement avec le HEAD précédent en ouvrant `/tmp/veille-after.png` localement (Florent regarde).

- [ ] **Step 7: Test fonctionnel E2E depuis l'UI**

1. Ouvrir https://veille.bubblestone.ai (Florent depuis son IP).
2. Cliquer "📝 LinkedIn" sur un topic.
3. Vérifier : bouton passe à "⏳ Génération..." (~30-60s) puis à "✓ Voir le post".
4. Cliquer le bouton, vérifier qu'il ouvre `https://linkedin.bubblestone.ai/post/<N>` dans un nouvel onglet.
5. Sur cette page linkedin, vérifier le post_text et l'absence d'image.
6. Cliquer "Générer l'image", attendre, vérifier qu'une image apparaît.
7. Cliquer "Valider", vérifier que le statut passe à "validated" (pas de génération auto d'image).
8. Copier `article_md` et créer manuellement le `.md` dans `site/src/content/blog/` (statu quo).

- [ ] **Step 8: Commit**

```bash
cd /opt/repos/bubblestone
git add apps/555-trend-monitor/ai_trend_monitor/web/templates/
git commit -m "feat(veille): button 'Valider pour LinkedIn' on dashboard + detail

Click triggers POST /api/validate-topic/<id> which generates the post
on linkedin-generator via Claude Opus, then opens the post URL on
linkedin.bubblestone.ai. Image generation stays manual (separate
button on linkedin-generator).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Mise à jour BRIEF.md + nettoyage final

**Files:**
- Modify: `apps/linkedin-generator/BRIEF.md`

- [ ] **Step 1: Localiser les mentions Gemini dans BRIEF.md**

```bash
grep -n -iE "gemini|nano.banana|generativelanguage" /opt/repos/bubblestone/apps/linkedin-generator/BRIEF.md
```

- [ ] **Step 2: Remplacer la section "Génération d'images"**

Trouver le bloc :

```markdown
- **Génération d'images** : Google Gemini API — modèle `gemini-3.1-flash-image-preview` (Nano Banana 2)
  - Clé API : `AIzaSyBkVO9mXqfkUgMmU7qb9heT9CqzyILcfIs`
  - Images générées à la validation uniquement (pas avant)
  - Style : photoréaliste, éditorial, PAS d'illustrations IA cartoon
```

Remplacer par :

```markdown
- **Génération d'images** : OpenAI Images 2 — modèle `gpt-image-2`
  - Endpoint : `POST https://api.openai.com/v1/images/generations`
  - Clé API : variable d'env `OPENAI_API_KEY` dans `/opt/bubblestone-config/.env` (org Bubblestone vérifiée 2026-04-28)
  - Images générées **uniquement** sur clic explicite "Générer image" (pas à la validation)
  - Param: `quality=high`, `size=1024x1024`, retour en `b64_json` décodé en PNG local
  - Style: photoréaliste, éditorial, PAS d'illustrations IA cartoon
```

- [ ] **Step 3: Ajouter la section "Source des posts" si elle n'y est pas**

Chercher si BRIEF.md mentionne déjà "validation depuis veille" :

```bash
grep -n -iE "veille|validation.*depuis|topic.*from" /opt/repos/bubblestone/apps/linkedin-generator/BRIEF.md
```

Si non, ajouter une section sous "Fonctionnalités" :

```markdown
### Création de posts

Les posts sont créés depuis veille.bubblestone.ai : un clic sur "📝 Valider pour LinkedIn" sur un topic envoie une requête HTTP interne (sur `bubblestone-net`) à `linkedin-generator` qui appelle Claude Opus 4.7 (modèle `claude-opus-4-7`, clé `ANTHROPIC_API_KEY`) pour générer en un seul appel : le `post_text` LinkedIn (1200-1800 caractères, ton drôle/percutant/sincère), l'`image_prompt` (description courte pour gpt-image-2), et l'`article_md` (version blog 600-1200 mots). Le post est inséré en DB avec `status='proposed'` et sans image.

Pas d'auth applicative sur la route `/api/topic/from-veille` : la sécurité repose sur l'ACL NPM "Florent Only" en amont (cf. `docs/superpowers/specs/2026-04-28-veille-to-linkedin-design.md`).
```

- [ ] **Step 4: Vérifier qu'il n'y a plus de mention Gemini dans tout le repo**

```bash
cd /opt/repos/bubblestone
grep -rn -iE "gemini|nano.banana" apps/linkedin-generator/ docs/ 2>&1 | grep -v ".git/" | grep -v "__pycache__"
```

Expected: vide (no match) ou uniquement dans des changelogs/historique.

- [ ] **Step 5: Commit**

```bash
cd /opt/repos/bubblestone
git add apps/linkedin-generator/BRIEF.md
git commit -m "docs(linkedin): update BRIEF.md — Gemini removed, OpenAI gpt-image-2 + veille flow

- Section 'Génération d'images' updated to gpt-image-2.
- New section 'Création de posts' documenting the veille → linkedin
  flow via Claude Opus 4.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: PR + merge + verification prod

**Files:** none (just git/gh ops)

- [ ] **Step 1: Push la branche**

```bash
cd /opt/repos/bubblestone
sudo -u codex-ops -H git push -u origin feat/veille-to-linkedin-and-gpt-image-2
```

- [ ] **Step 2: Créer la PR**

```bash
sudo -u codex-ops -H gh pr create --base main \
  --head feat/veille-to-linkedin-and-gpt-image-2 \
  --title "feat: veille → LinkedIn + OpenAI gpt-image-2 (drop Gemini)" \
  --body "$(cat <<'EOF'
## Summary
- Bouton "📝 Valider pour LinkedIn" sur veille.bubblestone.ai → POST interne → Claude Opus 4.7 génère post_text + image_prompt + article_md → INSERT DB linkedin (status=proposed).
- Génération d'image: bascule complète Gemini Nano Banana 2 → OpenAI `gpt-image-2` (quality=high). Plus de Gemini dans le repo.
- /api/post/<id>/validate ne génère plus d'image (séparation): Florent clique "Générer image" séparément.
- Blog: statu quo (copy-paste manuel `article_md` → `site/src/content/blog/*.md`).
- LinkedIn API: hors scope (copy-paste manuel).
- Pas d'auth applicative sur `/api/topic/from-veille`: protection via ACL NPM "Florent Only" (cf. spec section 5).

## Spec + Plan
- Spec: `docs/superpowers/specs/2026-04-28-veille-to-linkedin-design.md`
- Plan: `docs/superpowers/plans/2026-04-28-veille-to-linkedin-and-gpt-image-2.md`

## Test plan
- [ ] CI Security Scan + Deploy 555 + Deploy LinkedIn passent (workflows main).
- [ ] Test E2E manuel post-merge: validation depuis veille → post linkedin → "Générer image" → "Valider" → copy article_md vers blog.
- [ ] Vérifier qu'aucun fichier `.png` n'est créé pendant le clic "Valider" (séparation effective).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Suivre les checks CI**

```bash
sudo -u codex-ops -H gh pr checks --watch
```

Expected: `Security Scan / semgrep`, `trivy`, `secrets` tous PASS. `auto-merge` skipping (normal, PR humaine).

- [ ] **Step 4: Admin-merge (Florent est seul opérateur)**

```bash
sudo -u codex-ops -H gh pr merge --admin --squash --delete-branch
```

- [ ] **Step 5: Suivre les déploiements main**

```bash
sleep 10
sudo -u codex-ops -H gh run list --repo FlorentCoulonBS/Bubblestone.ai --branch main --limit 5 --json conclusion,name,status,databaseId
```

Expected: `Deploy 555` et `Deploy LinkedIn` `success`.

Si fail, regarder les logs :

```bash
sudo -u codex-ops -H gh run view <RUN_ID> --log-failed | tail -80
```

- [ ] **Step 6: Smoke test prod**

```bash
# 555 vivant
curl -sS -o /dev/null -w "555 HTTP %{http_code}\n" -u "$ADMIN_USER:$ADMIN_PASS" http://127.0.0.1:5000/

# linkedin vivant
curl -sS -o /dev/null -w "linkedin HTTP %{http_code}\n" http://127.0.0.1:5001/

# Bouton "📝 LinkedIn" présent dans le HTML rendu
curl -sS -u "$ADMIN_USER:$ADMIN_PASS" http://127.0.0.1:5000/ | grep -c "validateForLinkedIn"
```

Expected: 555 et linkedin → 200/302, et au moins 1 occurrence de `validateForLinkedIn` (= au moins 1 topic affiché avec son bouton).

- [ ] **Step 7: Test E2E final depuis le browser de Florent**

Florent fait le tour complet :
1. veille.bubblestone.ai → cliquer "📝 LinkedIn" sur un topic récent
2. Attendre la génération (~30-60s, modèle Opus est plus lent que Sonnet)
3. Cliquer "✓ Voir le post" → ouvre linkedin.bubblestone.ai/post/<N>
4. Vérifier post_text, image_prompt, article_md
5. Cliquer "Générer image" → image apparaît
6. Cliquer "Valider" → status validated, pas de regénération d'image
7. Copier `article_md` → créer un fichier .md dans `site/src/content/blog/` localement, commit, push (statu quo)

Si tout passe : **plan terminé**.

---

## Self-Review

**Spec coverage check:**

| Spec section | Tasks |
|--------------|-------|
| 4.1 veille app.py + bouton | Task 5, 6 |
| 4.2 linkedin /api/topic/from-veille + Claude | Task 4 |
| 4.2 linkedin /validate sans image | Task 3 |
| 4.2 linkedin generate_image gpt-image-2 | Task 2 |
| 4.2 retrait GEMINI_* + BRIEF | Task 2, 7 |
| 4.4 requirements.txt | Task 1 |
| 5 sécurité (ACL NPM) | documenté dans Task 4 + BRIEF.md (Task 7) |
| 6 gestion d'erreur | 502 dans Task 4 + Task 5 |
| 7 tests manuels | steps "Test manuel" dans chaque tâche, Task 8 step 7 |
| 8 déploiement (1 PR) | Task 8 |

**Type consistency check:**
- `generate_post_from_topic` retourne `dict` avec clés `post_text`, `image_prompt`, `article_md` — utilisées identiques dans Task 4 step 2 (route handler) et Task 4 step 1 (helper).
- `create_post(topic_title, post_text, image_prompt, ...)` signature préservée (Task 4 step 3 vérifie qu'on retourne `lastrowid`).
- JS `validateForLinkedIn(topicId, btn)` signature identique entre dashboard.html et topic_detail.html (Task 6 steps 2 & 3).

**No placeholders** : tous les blocs de code sont complets, pas de TBD/TODO/"similar to".
