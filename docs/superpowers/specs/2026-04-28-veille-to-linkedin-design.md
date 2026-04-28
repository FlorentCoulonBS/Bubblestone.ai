# Spec — Veille → LinkedIn → Blog

**Date** : 2026-04-28
**Auteur** : FlorentCoulonBS (avec Claude)
**Repos concernés** : `bubblestone` (apps `555-trend-monitor`, `linkedin-generator`, `site`)
**Statut** : à valider avant implémentation

---

## 1. Objectif

Permettre à Florent de **valider un article depuis veille.bubblestone.ai** pour qu'il devienne automatiquement un **post LinkedIn draft** sur linkedin.bubblestone.ai (texte généré par Claude). La génération d'image reste manuelle (bouton `gpt-image-2`). La publication sur le blog Bubblestone reste manuelle (statu quo).

Hors scope : intégration API LinkedIn, push automatique du blog, refonte des 143 posts existants.

## 2. État actuel (constaté 2026-04-28)

- `apps/555-trend-monitor` (`web/app.py`) expose `/`, `/source/<key>`, `/search`, `/api/og-image`, `/api/dismiss/<id>`. UI actuelle : boutons **"Read"** et **"Skip"**. **Pas de fonction de validation pour LinkedIn.**
- `apps/linkedin-generator` (`app.py`) expose `/login`, `/`, `/post/<id>`, `/api/post/<id>/{update,validate,reject,publish,regenerate-image}`, `/images/<filename>`. La génération d'image actuelle utilise **Gemini Nano Banana 2** (`gemini-3.1-flash-image-preview`). Le `/validate` génère l'image au moment du clic, ce qu'il ne faut plus.
- DB linkedin schéma `posts` : colonnes `topic_title`, `post_text`, `image_prompt`, `topic_url`, `topic_score`, `article_md`, `sources`, `image_path`, `status` ∈ `proposed|validated|rejected|published`. Schema préservé tel quel — aucune migration.
- API OpenAI `gpt-image-2` validée en live (orga vérifiée 2026-04-28). Endpoint : `POST https://api.openai.com/v1/images/generations`, retourne `b64_json`. Param requis : `quality: "high"` sinon downgrade auto en low.

## 3. Architecture

```
┌─────────────────────────┐         ┌──────────────────────────────────┐         ┌─────────────────┐
│ veille.bubblestone.ai   │         │ linkedin.bubblestone.ai          │         │ Blog (Astro)    │
│ container bubblestone-555│         │ container bubblestone-linkedin   │         │ commit manuel   │
│                         │         │                                  │         │  par Florent    │
│ Bouton "Valider LinkedIn" ───POST──► /api/topic/from-veille          │         │                 │
│ sur dashboard.html      │         │  → Anthropic Claude (post_text,  │         │                 │
│ + topic_detail.html     │         │     image_prompt, article_md)    │         │                 │
│                         │         │  → INSERT posts (status=proposed)│         │                 │
│                         │ ◄─JSON──── 200 {post_id, post_url}         │         │                 │
└─────────────────────────┘         │                                  │         │                 │
                                    │ UI : /post/<id>                  │         │                 │
                                    │  - bouton "Générer image" (manuel)│        │                 │
                                    │     ↓                            │         │                 │
                                    │     POST /api/post/<id>/regenerate-image    │                 │
                                    │     → OpenAI gpt-image-2          │         │                 │
                                    │  - bouton "Valider" : status only │         │                 │
                                    │  - bouton "Publier" : status only │         │                 │
                                    │  - copier `article_md` à la main  │ ─────► │ .md dans        │
                                    │     pour publier sur le blog      │         │ site/src/content/│
                                    └──────────────────────────────────┘         │ blog/*.md       │
                                                                                  └─────────────────┘
```

Communication 555 → linkedin via HTTP interne sur le réseau Docker `bubblestone-net` (subnet `172.18.0.0/16`). URL interne : `http://bubblestone-linkedin-generator:5001/api/topic/from-veille`. Pas d'auth token : la route est protégée par un filtre `request.remote_addr` qui doit être dans `172.18.0.0/16` — sinon 404 (silently fail pour ne pas révéler la route à un scanner externe).

## 4. Composants à modifier

### 4.1 `apps/555-trend-monitor/ai_trend_monitor/web/`

**`app.py`** — nouvelle route :
```python
@app.route("/api/validate-topic/<int:topic_id>", methods=["POST"])
@requires_auth
def api_validate_topic(topic_id):
    # 1. récupère topic depuis trends.db
    # 2. POST vers http://bubblestone-linkedin-generator:5001/api/topic/from-veille
    #    Headers: Content-Type: application/json
    #    Body: {"topic_id", "title", "url", "score", "sources"}
    # 3. Retourne 200 {ok: true, post_id, post_url} pour redirection UI
    #    ou 502 si linkedin renvoie erreur
```

**`templates/dashboard.html`** et **`templates/topic_detail.html`** — bouton :
```html
<button class="validate-btn primary" onclick="validateForLinkedIn({{ topic.id }}, this)">
  ✓ Valider pour LinkedIn
</button>
```
+ JS `validateForLinkedIn(id, btn)` : POST `/api/validate-topic/{id}`, désactive bouton, affiche le `post_url` retourné.

**Variables d'env** (lues dans `app.py`) :
- `LINKEDIN_GENERATOR_URL` (défaut `http://bubblestone-linkedin-generator:5001`)

### 4.2 `apps/linkedin-generator/`

**`app.py`** — nouvelle route :
```python
@app.route("/api/topic/from-veille", methods=["POST"])
def api_from_veille():
    # 1. Filtre IP source: ipaddress.ip_address(request.remote_addr) dans
    #    ipaddress.ip_network("172.18.0.0/16"), sinon abort(404).
    # 2. Reçoit {topic_id, title, url, score, sources}
    # 3. Appelle Anthropic Claude pour générer JSON {post_text, image_prompt, article_md}
    #    Modèle: claude-opus-4-7 (clé existante ANTHROPIC_API_KEY)
    #    Prompt système: ton du BRIEF.md (drôle, percutant, sincère)
    #    Format de sortie strict: JSON {post_text, image_prompt, article_md}
    # 4. INSERT dans posts avec status='proposed', image_path=NULL
    # 5. Retourne 200 {ok: true, post_id, post_url: f"/post/{post_id}"}
    #    ou 502 si Anthropic renvoie erreur (Florent re-cliquera depuis veille)
```

**`app.py /api/post/<id>/validate`** — modifié : retire le bloc de génération d'image. Ne fait plus que `update_post_status(post_id, "validated")`.

**`app.py generate_image()`** — bascule complète Gemini → OpenAI gpt-image-2 :
```python
def generate_image(post_id, prompt):
    """Generate image using OpenAI gpt-image-2."""
    full_prompt = (
        f"Photorealistic editorial photograph for a LinkedIn post. "
        f"Style: photojournalism, magazine quality, dramatic lighting, "
        f"natural composition, no AI-generated cartoonish look. "
        f"Subject: {prompt}"
    )
    payload = {
        "model": "gpt-image-2",
        "prompt": full_prompt,
        "size": "1024x1024",
        "quality": "high",
        "n": 1,
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    r = requests.post("https://api.openai.com/v1/images/generations", json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    b64 = r.json()["data"][0]["b64_json"]
    img_bytes = base64.b64decode(b64)
    filename = f"post_{post_id}_{datetime.utcnow():%Y%m%d_%H%M%S}.png"
    (Path(IMAGES_DIR) / filename).write_bytes(img_bytes)
    return filename
```

**Suppressions** :
- `GEMINI_API_KEY` et `GEMINI_MODEL` (plus utilisés)
- Toute logique d'appel Gemini (`generativelanguage.googleapis.com`)
- Mise à jour du `BRIEF.md` (changer mention Gemini → OpenAI gpt-image-2)
- Variable d'env `GEMINI_API_KEY` à retirer manuellement de `/opt/bubblestone-config/.env` (Florent — règle absolue)

**Variables d'env nouvelles** :
- `OPENAI_API_KEY` (déjà ajoutée par Florent au `.env` aujourd'hui)
- `BUBBLESTONE_NET_SUBNET` (défaut `172.18.0.0/16`, configurable au cas où le subnet change)

### 4.3 `infra/docker-compose.yml`

Pas de changement structurel. Les 2 containers sont déjà sur `bubblestone-net` et lisent `/opt/bubblestone-config/.env`.

### 4.4 `apps/linkedin-generator/requirements.txt`

État actuel : `flask==3.1.3`, `gunicorn==25.3.0` uniquement (pas de SDK Gemini, l'appel passait par `urllib`/`requests` indirect).

Ajouter :
- `requests>=2.31` (appel `gpt-image-2`, plus lisible que `urllib`)
- `anthropic>=0.40` (SDK officiel pour générer post_text + image_prompt + article_md)

Aucune dépendance Gemini à retirer (il n'y en avait jamais eu dans `requirements.txt` — l'appel se faisait en HTTP brut via `urllib`).

Pas besoin du SDK OpenAI : `requests` suffit pour 1 seul endpoint `/v1/images/generations`.

## 5. Sécurité

- **Veille** : `/api/validate-topic` reste derrière `@requires_auth` (basic auth admin existante).
- **LinkedIn** : `/api/topic/from-veille` n'a PAS `@login_required` ni token partagé — la route est protégée par un filtre `request.remote_addr ∈ 172.18.0.0/16` (subnet `bubblestone-net`). Si une requête arrive d'ailleurs (Internet via NPM, localhost host) : `abort(404)` silencieux pour ne pas révéler la route à un scanner. Justification : sur un réseau Docker fermé entre containers de confiance (mêmes mainteneurs), un secret partagé est de la cérémonie sans gain réel — l'isolation réseau Docker fait déjà le boulot.
- **Réseau** : `linkedin-generator` reste exposé sur `127.0.0.1:5001` (NPM proxy public). L'appel 555 → linkedin se fait via le DNS Docker interne (`bubblestone-linkedin-generator:5001`), donc `request.remote_addr` côté linkedin = `172.18.0.x` (IP du container 555). NPM ne forwarde pas `/api/topic/from-veille` (le check IP rejette tout ce qui ne vient pas du subnet Docker).
- **OpenAI** : `OPENAI_API_KEY` reste dans `/opt/bubblestone-config/.env`, jamais loggée. Rate-limit / 5xx → erreur UI, pas de retry auto.
- **Anthropic** : `ANTHROPIC_API_KEY` (déjà présente). Idem.

## 6. Gestion d'erreurs

| Étape | Erreur | Comportement |
|-------|--------|--------------|
| 555 → linkedin | linkedin down / timeout 5s | UI 555 affiche "linkedin indispo, réessaie" |
| linkedin → Anthropic | API key invalide / quota / 5xx | linkedin renvoie 502, UI 555 affiche "génération échouée" |
| linkedin DB insert | erreur SQLite | 500, log côté linkedin |
| gpt-image-2 | quota / org non vérifiée / 5xx | UI linkedin affiche message d'erreur, pas de partial state (image_path reste NULL) |

Pas de retry auto (Florent peut re-cliquer à la main).

## 7. Tests / validation

**Tests manuels avant prod** :
1. `INTERNAL_API_TOKEN` configuré dans `.env`, containers redémarrés.
2. Sur veille, "Valider pour LinkedIn" sur un topic récent → vérifier post draft créé en DB linkedin avec `post_text` et `article_md` non vides.
3. Sur linkedin, "Générer image" sur le post → vérifier qu'un fichier `.png` est créé dans `/opt/bubblestone-linkedin-data/images/` et que `image_path` est mis à jour.
4. Sur linkedin, "Valider" puis "Publier" → vérifier que les statuts changent sans tenter de regénérer une image.
5. Tester un cas d'erreur : couper temporairement la clé OpenAI dans `.env` + restart linkedin → "Générer image" doit renvoyer un message clair, sans corrompre la DB.
6. Verif schema DB inchangé (`sqlite3 ... ".schema posts"` identique avant/après).

**Pas de tests automatisés écrits** : pas d'infra de tests existants sur ces 2 apps.

## 8. Déploiement

- 1 seule PR sur `bubblestone` qui touche `apps/555-trend-monitor/` + `apps/linkedin-generator/` + `apps/linkedin-generator/BRIEF.md`.
- Push main → workflows `Deploy 555` et `Deploy LinkedIn` se déclenchent en parallèle (déjà en place).
- Pas de migration DB. Si rollback : revert PR, les 143 posts existants ne sont pas touchés.

## 9. Hors scope (statu quo, pas de changement)

- Publication API LinkedIn (Florent copy-paste manuel)
- Push automatique blog (Florent copy-paste `article_md` → fichier .md → commit/push manuel)
- Refonte des 143 posts existants
- Changement de l'auth de linkedin-generator (LOGIN_USER/LOGIN_PASSWORD)
- Changement du flow d'auth du dashboard 555 (basic auth admin)
