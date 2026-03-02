# LinkedIn Post Generator — linkedin.bubblestone.ai

## Objectif
Plateforme web de génération de posts LinkedIn à partir des trending topics IA collectés par la veille (dashboard 555).

## Architecture
- **Backend** : Python Flask
- **DB** : SQLite (posts, validations, images)
- **Source de données** : `/root/data/trends.db` (DB veille 555, montée en volume)
- **Génération d'images** : Google Gemini API — modèle `gemini-3.1-flash-image-preview` (Nano Banana 2)
  - Clé API : `AIzaSyBkVO9mXqfkUgMmU7qb9heT9CqzyILcfIs`
  - Images générées à la validation uniquement (pas avant)
  - Style : photoréaliste, éditorial, PAS d'illustrations IA cartoon
- **Déploiement** : Container Docker sur BubbleStoneAI (72.62.190.147)
- **Proxy** : NPM → linkedin.bubblestone.ai
- **Réseau** : npmnet

## Sécurité (double couche)
1. **NPM** : ACL "Florent Only" (restriction IP)
2. **App** : Login utilisateur + mot de passe (Flask-Login ou session-based)
   - User par défaut : `florent` / mot de passe à définir au premier lancement via variable d'env

## Fonctionnalités

### 1. Dashboard quotidien
- Affiche les propositions de posts du jour (3-5 par jour)
- Chaque proposition contient :
  - **Titre/accroche** du post
  - **Texte complet** du post LinkedIn (prêt à copier)
  - **Prompt image** (pas encore généré)
  - **Sources** : liens vers les articles originaux de la veille
  - **Score/signal** du topic source
- Filtres : par date, par statut (proposé / validé / rejeté / publié)

### 2. Génération de posts
- Source : topics de trends.db avec combined_signal élevé
- Ton : drôle, percutant, sincère. Tech accessible, pas imbitable.
- Structure LinkedIn optimale : hook → développement → CTA/conclusion
- Hashtags pertinents
- Pensé pour l'algo LinkedIn (engagement, commentaires)

### 3. Validation workflow
- Bouton "Valider" → génère l'image Nano Banana 2 à ce moment seulement
- Bouton "Rejeter" → archivé
- Bouton "Modifier" → édition inline du texte avant validation
- Bouton "Régénérer" → nouveau post sur le même sujet

### 4. Export
- Copier le texte en un clic
- Télécharger l'image
- Format article pour bubblestone.ai (Markdown)

### 5. Cron quotidien
- Tourne chaque soir (~20h Paris)
- Lit les top topics de trends.db des dernières 24h
- Génère 3-5 propositions via Claude (prompt système dédié)
- Sauvegarde dans la DB locale

## Stack technique
- Python 3.12 + Flask
- SQLite3
- Jinja2 templates
- CSS moderne (pas de framework lourd, Tailwind ou custom)
- Pas de JS framework (vanilla JS suffisant)

## Structure DB (linkedin.db)

### posts
- id, created_at, topic_id, topic_title, topic_url, topic_score
- post_text (texte LinkedIn complet)
- image_prompt (prompt pour Nano Banana 2)
- image_path (NULL tant que pas validé)
- status (proposed / validated / rejected / published)
- validated_at, published_at
- article_md (version article pour le site)

## Volume Docker
- `/root/data/trends.db` → lecture seule (source veille)
- `/data/linkedin.db` → DB posts (persistante)
- `/data/images/` → images générées (persistantes)
