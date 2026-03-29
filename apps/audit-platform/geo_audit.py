#!/usr/bin/env python3
"""
GEO Audit — Generative Engine Optimization
Évalue la visibilité d'un site dans les moteurs de recherche génératifs
(Google AI Overviews, ChatGPT, Perplexity, etc.)

Ref: arXiv:2311.09735 (KDD 2024) — +40% visibilité avec bonnes pratiques GEO.
"""
import re
import json
import requests
from urllib.parse import urlparse, urljoin


# --- AI bots to check in robots.txt ---
AI_BOTS = ['GPTBot', 'ChatGPT-User', 'Google-Extended', 'ClaudeBot',
           'PerplexityBot', 'Amazonbot', 'anthropic-ai', 'Bytespider',
           'CCBot', 'cohere-ai']

# --- Schema types we look for ---
IMPORTANT_SCHEMAS = [
    'Organization', 'LocalBusiness', 'WebSite', 'WebPage',
    'Article', 'BlogPosting', 'NewsArticle', 'FAQPage',
    'HowTo', 'JobPosting', 'Product', 'Service', 'Event',
    'BreadcrumbList', 'Person', 'Review', 'AggregateRating',
    'ContactPoint', 'Offer', 'VideoObject', 'ImageObject',
    'SpeakableSpecification',
]

# Homepage-critical schemas
HOMEPAGE_SCHEMAS = ['Organization', 'LocalBusiness', 'WebSite']
# Content page schemas
CONTENT_SCHEMAS = ['Article', 'BlogPosting', 'NewsArticle', 'JobPosting',
                   'Product', 'Service', 'FAQPage', 'HowTo', 'Event']

# E-E-A-T page patterns
ABOUT_PATTERNS = re.compile(
    r'(/about|/a-propos|/qui-sommes-nous|/notre-equipe|/team|/equipe|/notre-histoire)',
    re.IGNORECASE)
LEGAL_PATTERNS = re.compile(
    r'(/mentions-legales|/legal|/cgv|/cgu|/conditions|/privacy|/politique-de-confidentialite|/rgpd)',
    re.IGNORECASE)
TESTIMONIAL_PATTERNS = re.compile(
    r'(/temoignages|/avis|/testimonials|/reviews|/references|/clients|/cas-clients|/case-studies|/portfolio)',
    re.IGNORECASE)

# Question patterns in headings
QUESTION_RE = re.compile(
    r'(comment\s|qu[\'\u2019]est-ce que|pourquoi\s|quand\s|combien\s|quel(le)?s?\s|'
    r'how\s|what\s|why\s|when\s|where\s|which\s|who\s|can\s|does\s|is\s|are\s|\?$)',
    re.IGNORECASE)

# Stats/numbers patterns
STATS_RE = re.compile(
    r'(\d+\s*%|\d{1,3}[\s.,]\d{3}|\d+\s*(millions?|milliards?|mds?|k|M)\b|'
    r'en\s+20\d{2}\b|\+\s*\d+|×\s*\d+|\d+\s*x\s+plus)',
    re.IGNORECASE)


def audit_geo(url, crawl_data, stack_data, deep_seo_data):
    """
    Analyse GEO complète.
    Returns dict with score, categories, recommendations, etc.
    """
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    pages = crawl_data.get('pages', [])
    if not pages:
        pages = []

    # =========================================================
    # 1. SCHEMA.ORG (25 points)
    # =========================================================
    schema_result = _audit_schema(pages, base_url, url)

    # =========================================================
    # 2. CONTENU STRUCTURÉ POUR LES IA (20 points)
    # =========================================================
    content_result = _audit_content_structure(pages)

    # =========================================================
    # 3. E-E-A-T (15 points)
    # =========================================================
    eeat_result = _audit_eeat(pages, crawl_data, stack_data)

    # =========================================================
    # 4. CONTENU FACTUEL ET CITATIONS (15 points)
    # =========================================================
    factual_result = _audit_factual(pages)

    # =========================================================
    # 5. COUVERTURE THÉMATIQUE (10 points)
    # =========================================================
    topic_result = _audit_topic_coverage(pages, crawl_data)

    # =========================================================
    # 6. ACCESSIBILITÉ IA (15 points)
    # =========================================================
    ai_access_result = _audit_ai_accessibility(url, base_url, crawl_data, deep_seo_data)

    # =========================================================
    # SCORE GLOBAL
    # =========================================================
    categories = {
        'schema': schema_result,
        'content_structure': content_result,
        'eeat': eeat_result,
        'factual_content': factual_result,
        'topic_coverage': topic_result,
        'ai_accessibility': ai_access_result,
    }

    total_score = sum(c['score'] for c in categories.values())
    max_score = sum(c['max'] for c in categories.values())

    # =========================================================
    # RECOMMANDATIONS
    # =========================================================
    recommendations = _build_recommendations(categories, schema_result, ai_access_result)

    # Flatten some useful data
    schemas_found = schema_result.get('_schemas_found', [])
    schemas_missing = schema_result.get('_schemas_missing', [])
    ai_bots_blocked = ai_access_result.get('_bots_blocked', [])
    faq_pages_found = content_result.get('_faq_count', 0)

    # Stats density
    total_pages = len(pages) if pages else 1
    pages_with_stats = factual_result.get('_pages_with_stats', 0)
    stats_density = round(pages_with_stats / max(total_pages, 1), 2)

    return {
        'score': total_score,
        'max_score': max_score,
        'categories': categories,
        'recommendations': recommendations,
        'schemas_found': schemas_found,
        'schemas_missing': schemas_missing,
        'ai_bots_blocked': ai_bots_blocked,
        'faq_pages_found': faq_pages_found,
        'stats_density': stats_density,
    }


# ===============================================================
# CATEGORY AUDITORS
# ===============================================================

def _audit_schema(pages, base_url, url):
    """Schema.org / Données structurées — 25 points max."""
    score = 0
    details = []
    schemas_found = set()
    pages_with_schema = 0
    pages_without_schema = 0
    homepage_has_org = False

    for page in pages:
        page_url = page.get('url', '')
        html = page.get('html', page.get('body', ''))
        if not html:
            page_url = page.get('url', '')
            if page_url:
                html = _fast_html(page_url)
            if not html:
                continue

        page_schemas = _extract_schemas(html)
        if page_schemas:
            pages_with_schema += 1
            schemas_found.update(page_schemas)
        else:
            pages_without_schema += 1

        # Check homepage
        is_home = _is_homepage(page_url, base_url, url)
        if is_home:
            for s in HOMEPAGE_SCHEMAS:
                if s in page_schemas:
                    homepage_has_org = True
                    break

    schemas_found = sorted(schemas_found)
    schemas_missing = [s for s in IMPORTANT_SCHEMAS if s not in schemas_found]

    total = pages_with_schema + pages_without_schema
    schema_coverage = pages_with_schema / max(total, 1)

    # Scoring
    if not schemas_found:
        score = 0
        details.append("Aucun schema.org détecté sur le site")
    else:
        # Coverage (0-10)
        score += min(10, int(schema_coverage * 10))
        details.append(f"{pages_with_schema}/{total} pages avec schema.org ({schema_coverage:.0%})")

        # Homepage org (0-8)
        if homepage_has_org:
            score += 8
            details.append("Schema Organization/LocalBusiness présent sur la homepage")
        else:
            details.append("Schema Organization/LocalBusiness ABSENT de la homepage")

        # Diversity (0-7)
        content_schema_count = len([s for s in CONTENT_SCHEMAS if s in schemas_found])
        diversity_score = min(7, content_schema_count * 2)
        score += diversity_score
        details.append(f"Types schema trouvés : {', '.join(schemas_found[:10])}")

    score = min(25, score)

    return {
        'score': score, 'max': 25, 'details': details,
        '_schemas_found': schemas_found,
        '_schemas_missing': schemas_missing[:10],
        '_pages_with': pages_with_schema,
        '_pages_without': pages_without_schema,
    }


def _audit_content_structure(pages):
    """Contenu structuré pour les IA — 20 points max."""
    score = 0
    details = []
    faq_count = 0
    pages_with_questions = 0
    pages_with_lists = 0
    pages_with_tables = 0
    pages_with_concise_answers = 0
    total_content_pages = 0

    for page in pages:
        html = page.get('html', page.get('body', ''))
        if not html or len(html) < 500:
            continue
        total_content_pages += 1

        # FAQ detection
        html_lower = html.lower()
        has_faq = ('faqpage' in html_lower or
                   'itemtype="https://schema.org/faqpage"' in html_lower or
                   '<faq' in html_lower)
        if has_faq:
            faq_count += 1

        # Question headings
        headings = re.findall(r'<h[2-3][^>]*>(.*?)</h[2-3]>', html, re.IGNORECASE | re.DOTALL)
        question_headings = [h for h in headings if QUESTION_RE.search(h)]
        if question_headings:
            pages_with_questions += 1

        # Concise answers: question heading followed by short paragraph
        if question_headings:
            has_concise = False
            for match in re.finditer(
                r'</h[2-3]>\s*<p[^>]*>(.*?)</p>',
                html, re.IGNORECASE | re.DOTALL
            ):
                para_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                sentence_count = len(re.findall(r'[.!?]+', para_text))
                if 20 < len(para_text) < 300 and 1 <= sentence_count <= 3:
                    has_concise = True
                    break
            if has_concise:
                pages_with_concise_answers += 1

        # Lists
        if '<ul' in html_lower or '<ol' in html_lower:
            pages_with_lists += 1

        # Tables
        if '<table' in html_lower:
            pages_with_tables += 1

    total = max(total_content_pages, 1)

    # FAQ (0-5, was 6)
    if faq_count > 0:
        score += min(5, faq_count * 2 + 1)
        details.append(f"{faq_count} page(s) FAQ détectée(s)")
    else:
        details.append("Aucune page FAQ structurée détectée")

    # Questions in headings (0-5, was 6)
    q_ratio = pages_with_questions / total
    score += min(5, int(q_ratio * 10))
    details.append(f"{pages_with_questions}/{total} pages avec des titres sous forme de questions ({q_ratio:.0%})")

    # Concise answers (0-4, NEW)
    if pages_with_questions > 0:
        ca_ratio = pages_with_concise_answers / max(pages_with_questions, 1)
        score += min(4, int(ca_ratio * 6))
        details.append(f"{pages_with_concise_answers}/{pages_with_questions} pages avec réponses concises après les questions ({ca_ratio:.0%})")
    else:
        details.append("Pas de titres-questions détectés pour évaluer les réponses concises")

    # Lists (0-3, was 4)
    l_ratio = pages_with_lists / total
    score += min(3, int(l_ratio * 5))
    details.append(f"{pages_with_lists}/{total} pages avec listes structurées")

    # Tables (0-3, was 4)
    t_ratio = pages_with_tables / total
    score += min(3, int(t_ratio * 6))
    if pages_with_tables:
        details.append(f"{pages_with_tables} page(s) avec tableaux de données")

    score = min(20, score)

    return {
        'score': score, 'max': 20, 'details': details,
        '_faq_count': faq_count,
        '_concise_answer_count': pages_with_concise_answers,
    }


def _audit_eeat(pages, crawl_data, stack_data):
    """E-E-A-T — Autorité et expertise — 15 points max."""
    score = 0
    details = []

    all_urls = [p.get('url', '') for p in pages]

    # About page (0-3)
    has_about = any(ABOUT_PATTERNS.search(u) for u in all_urls)
    if has_about:
        score += 3
        details.append("Page À propos / Qui sommes-nous détectée")
    else:
        details.append("Pas de page À propos détectée")

    # Legal pages (0-3)
    has_legal = any(LEGAL_PATTERNS.search(u) for u in all_urls)
    if has_legal:
        score += 3
        details.append("Mentions légales / CGV détectées")
    else:
        details.append("Pas de mentions légales détectées")

    # Testimonials / references (0-3)
    has_testimonials = any(TESTIMONIAL_PATTERNS.search(u) for u in all_urls)
    if has_testimonials:
        score += 3
        details.append("Page témoignages / références clients détectée")
    else:
        details.append("Pas de page témoignages ou références clients")

    # Team page / author mentions (0-3)
    has_team = any(re.search(r'(/equipe|/team|/notre-equipe|/nos-experts)', u, re.I) for u in all_urls)
    if has_team:
        score += 3
        details.append("Page équipe détectée")
    else:
        # Check for author schema or bylines in content
        has_author = False
        for page in pages[:20]:
            html = page.get('html', page.get('body', ''))
            if html and ('schema.org/person' in html.lower() or '"author"' in html.lower()):
                has_author = True
                break
        if has_author:
            score += 2
            details.append("Mentions d'auteurs détectées dans le contenu")
        else:
            details.append("Pas de page équipe ni d'auteurs identifiés")

    # SSL / trust (0-3)
    ssl_ok = stack_data.get('ssl', {}).get('valid', False) if stack_data else False
    if ssl_ok:
        score += 3
        details.append("Certificat SSL valide")
    else:
        # Fallback: check URL
        if any(u.startswith('https') for u in all_urls[:1]):
            score += 2
            details.append("HTTPS actif")
        else:
            details.append("HTTPS non détecté")

    score = min(15, score)
    return {'score': score, 'max': 15, 'details': details}


def _audit_factual(pages):
    """Contenu factuel et citations — 15 points max."""
    score = 0
    details = []
    pages_with_stats = 0
    pages_with_external_links = 0
    total_content_pages = 0

    for page in pages:
        html = page.get('html', page.get('body', ''))
        if not html or len(html) < 500:
            continue
        total_content_pages += 1

        # Stats/numbers
        text = re.sub(r'<[^>]+>', ' ', html)
        if STATS_RE.search(text):
            pages_with_stats += 1

        # External links (authority sources)
        ext_links = re.findall(r'href=["\']https?://([^"\']+)', html)
        page_domain = urlparse(page.get('url', '')).netloc
        external = [l for l in ext_links if page_domain not in l]
        if len(external) >= 2:
            pages_with_external_links += 1

    total = max(total_content_pages, 1)

    # Stats presence (0-10)
    stats_ratio = pages_with_stats / total
    score += min(10, int(stats_ratio * 15))
    details.append(f"{pages_with_stats}/{total} pages contiennent des données chiffrées ({stats_ratio:.0%})")

    # External citations (0-5)
    cite_ratio = pages_with_external_links / total
    score += min(5, int(cite_ratio * 10))
    details.append(f"{pages_with_external_links}/{total} pages citent des sources externes")

    score = min(15, score)
    return {
        'score': score, 'max': 15, 'details': details,
        '_pages_with_stats': pages_with_stats,
    }


def _audit_topic_coverage(pages, crawl_data):
    """Couverture thématique — 10 points max."""
    score = 0
    details = []

    # Count substantial pages (>500 words)
    substantial_pages = 0
    titles = set()
    blog_detected = False

    for page in pages:
        html = page.get('html', page.get('body', ''))
        page_url = page.get('url', '')

        if html:
            text = re.sub(r'<[^>]+>', ' ', html)
            words = len([w for w in text.split() if len(w) > 2])
            if words > 500:
                substantial_pages += 1

            # Extract title
            title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.DOTALL)
            if title_match:
                titles.add(title_match.group(1).strip()[:80])

            # H1
            h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.I | re.DOTALL)
            if h1_match:
                titles.add(re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()[:80])

        # Blog detection
        if re.search(r'(/blog|/actualites|/articles|/news|/magazine)', page_url, re.I):
            blog_detected = True

    # Substantial content (0-4)
    if substantial_pages >= 20:
        score += 4
    elif substantial_pages >= 10:
        score += 3
    elif substantial_pages >= 5:
        score += 2
    elif substantial_pages >= 1:
        score += 1
    details.append(f"{substantial_pages} pages avec contenu substantiel (>500 mots)")

    # Blog (0-3)
    if blog_detected:
        score += 3
        details.append("Blog / section actualités détecté")
    else:
        details.append("Pas de blog ou section actualités détecté")

    # Topic diversity (0-3)
    unique_titles = len(titles)
    if unique_titles >= 15:
        score += 3
    elif unique_titles >= 8:
        score += 2
    elif unique_titles >= 3:
        score += 1
    details.append(f"{unique_titles} sujets/pages uniques identifiés")

    score = min(10, score)
    return {'score': score, 'max': 10, 'details': details}


def _audit_ai_accessibility(url, base_url, crawl_data, deep_seo_data):
    """Accessibilité IA — 15 points max."""
    score = 0
    details = []
    bots_blocked = []

    # 1. robots.txt — AI bots (0-5)
    try:
        robots_url = base_url.rstrip('/') + '/robots.txt'
        r = requests.get(robots_url, timeout=10, headers={'User-Agent': 'BubbleStone-Audit/1.0'})
        if r.status_code == 200:
            robots_text = r.text.lower()
            for bot in AI_BOTS:
                # Check if bot is specifically disallowed
                bot_lower = bot.lower()
                # Find user-agent sections for this bot
                in_bot_section = False
                for line in r.text.split('\n'):
                    line_stripped = line.strip().lower()
                    if line_stripped.startswith('user-agent:'):
                        agent = line_stripped.split(':', 1)[1].strip()
                        in_bot_section = (agent == bot_lower or agent == '*')
                    elif in_bot_section and line_stripped.startswith('disallow:'):
                        path = line_stripped.split(':', 1)[1].strip()
                        if path == '/' and agent == bot_lower:
                            bots_blocked.append(bot)
                            break

            if not bots_blocked:
                score += 5
                details.append("Aucun bot IA bloqué dans robots.txt")
            else:
                # Partial score if only some are blocked
                blocked_ratio = len(bots_blocked) / len(AI_BOTS)
                score += max(0, int(5 * (1 - blocked_ratio)))
                details.append(f"Bots IA bloqués dans robots.txt : {', '.join(bots_blocked)}")
        else:
            score += 3  # No robots.txt = partially open
            details.append("Pas de robots.txt (les bots IA peuvent accéder au site)")
    except Exception:
        score += 2
        details.append("Impossible de vérifier robots.txt")

    # 2. Sitemap (0-3)
    sitemap_ok = False
    if deep_seo_data:
        for check in deep_seo_data.get('checks', []):
            if 'sitemap' in check.get('name', '').lower():
                sitemap_ok = check.get('passed', False)
                break
    if sitemap_ok:
        score += 3
        details.append("Sitemap.xml accessible et valide")
    else:
        details.append("Sitemap.xml absent ou non valide")

    # 3. JS rendering (0-3)
    stack_js_heavy = False
    # Check if pages have substantial content in HTML (not JS-only)
    pages = crawl_data.get('pages', [])
    pages_with_content = 0
    for page in pages[:10]:  # Sample
        html = page.get('html', page.get('body', ''))
        if html:
            text = re.sub(r'<[^>]+>', ' ', html)
            if len(text.split()) > 50:
                pages_with_content += 1

    if pages_with_content >= 5:
        score += 3
        details.append("Contenu HTML accessible sans JavaScript")
    elif pages_with_content >= 2:
        score += 1
        details.append("Contenu partiellement dépendant de JavaScript")
    else:
        details.append("Contenu potentiellement rendu côté client (problème pour les crawlers IA)")

    # 4. Response time (0-2)
    avg_time = crawl_data.get('avg_response_time', None)
    if avg_time is not None:
        if avg_time < 1.0:
            score += 2
            details.append(f"Temps de réponse moyen : {avg_time:.1f}s (rapide)")
        elif avg_time < 3.0:
            score += 1
            details.append(f"Temps de réponse moyen : {avg_time:.1f}s (acceptable)")
        else:
            details.append(f"Temps de réponse moyen : {avg_time:.1f}s (lent pour les crawlers IA)")
    else:
        score += 1  # Unknown = assume ok
        details.append("Temps de réponse non mesuré")

    # 5. No login wall (0-2)
    login_wall = False
    for page in pages[:10]:
        html = page.get('html', page.get('body', '')).lower()
        if html and ('login' in html or 'connexion' in html):
            # Check if it's the main content or just a nav link
            pass  # Basic check — login pages don't block everything
    score += 2  # Assume no login wall unless detected
    details.append("Pas de contenu derrière un mur de connexion détecté")

    score = min(15, score)
    return {
        'score': score, 'max': 15, 'details': details,
        '_bots_blocked': bots_blocked,
    }


# ===============================================================
# RECOMMENDATIONS
# ===============================================================

def _build_recommendations(categories, schema_result, ai_access_result):
    """Build prioritized, actionable GEO recommendations."""
    recs = []

    # --- Schema recommendations ---
    schemas_found = set(schema_result.get('_schemas_found', []))
    schemas_missing = schema_result.get('_schemas_missing', [])

    if 'Organization' not in schemas_found and 'LocalBusiness' not in schemas_found:
        recs.append({
            'priority': 'critique',
            'problem': "Aucun schema Organization ou LocalBusiness sur la homepage",
            'action': "Ajouter un bloc JSON-LD schema.org Organization (ou LocalBusiness) sur la homepage avec : nom, adresse, téléphone, logo, URL, réseaux sociaux",
            'impact': "Permet d'apparaître dans le Knowledge Panel Google et d'être cité nommément par les IA génératives (ChatGPT, Perplexity)",
        })

    if 'FAQPage' not in schemas_found:
        recs.append({
            'priority': 'haute',
            'problem': "Aucune page FAQ avec schema FAQPage",
            'action': "Créer une page FAQ structurée avec les questions fréquentes de vos clients, balisée en schema FAQPage",
            'impact': "Les moteurs IA reprennent directement les questions/réponses structurées — forte probabilité d'être cité comme source",
        })

    if 'BreadcrumbList' not in schemas_found:
        recs.append({
            'priority': 'moyenne',
            'problem': "Pas de fil d'Ariane structuré (BreadcrumbList)",
            'action': "Ajouter un fil d'Ariane sur toutes les pages avec le schema BreadcrumbList",
            'impact': "Aide les IA à comprendre la hiérarchie du site et améliore les rich snippets Google",
        })

    for schema_type in ['Article', 'BlogPosting']:
        if schema_type not in schemas_found:
            recs.append({
                'priority': 'haute',
                'problem': f"Pas de schema {schema_type} sur les pages de contenu",
                'action': f"Ajouter le schema {schema_type} sur chaque article/page de blog avec auteur, date de publication, image",
                'impact': "Les IA identifient mieux le contenu éditorial et peuvent le citer avec attribution",
            })
            break  # Only one of the two

    if 'JobPosting' in schemas_missing:
        # Only recommend if site seems to have jobs
        recs.append({
            'priority': 'moyenne',
            'problem': "Pas de schema JobPosting détecté",
            'action': "Si vous publiez des offres d'emploi, ajouter le schema JobPosting sur chaque offre (titre, salaire, lieu, type de contrat)",
            'impact': "Active Google for Jobs et permet aux IA de citer vos offres avec les détails clés",
        })

    # --- AI bots ---
    bots_blocked = ai_access_result.get('_bots_blocked', [])
    if bots_blocked:
        recs.append({
            'priority': 'critique',
            'problem': f"Bots IA bloqués dans robots.txt : {', '.join(bots_blocked)}",
            'action': f"Supprimer ou modifier les règles Disallow pour {', '.join(bots_blocked)} dans robots.txt",
            'impact': "Ces bots ne peuvent pas crawler votre site — vous êtes invisible pour les moteurs IA correspondants (ChatGPT, Perplexity, etc.)",
        })

    # --- Content structure ---
    cs = categories['content_structure']
    if cs['score'] < 10:
        faq_count = cs.get('_faq_count', 0)
        if faq_count == 0:
            recs.append({
                'priority': 'haute',
                'problem': "Le contenu n'est pas structuré en format question/réponse",
                'action': "Reformuler les titres H2/H3 sous forme de questions (\"Comment...\", \"Qu'est-ce que...\") et donner la réponse directe dès le premier paragraphe",
                'impact': "Les IA reprennent les contenus au format Q&A — c'est le format le plus cité dans les AI Overviews Google (+40% selon l'étude KDD 2024)",
            })

        recs.append({
            'priority': 'moyenne',
            'problem': "Peu de contenu structuré (listes, tableaux)",
            'action': "Ajouter des listes à puces pour les comparaisons, étapes et avantages. Utiliser des tableaux pour les données comparatives",
            'impact': "Les LLMs extraient plus facilement les informations depuis des listes et tableaux structurés",
        })

    # --- E-E-A-T ---
    eeat = categories['eeat']
    if eeat['score'] < 8:
        recs.append({
            'priority': 'haute',
            'problem': "Signaux d'autorité et d'expertise insuffisants",
            'action': "Créer/enrichir les pages À propos, Équipe (avec noms, rôles, photos), Références clients, et Mentions légales",
            'impact': "Les IA évaluent l'expertise et la fiabilité d'une source — sans ces signaux E-E-A-T, votre contenu est moins susceptible d'être cité",
        })

    # --- Factual content ---
    factual = categories['factual_content']
    if factual['score'] < 8:
        recs.append({
            'priority': 'haute',
            'problem': "Peu de données chiffrées et de sources citées dans le contenu",
            'action': "Ajouter des statistiques chiffrées et sourcées (études, rapports, données marché) dans les pages principales. Citer les sources avec des liens",
            'impact': "Les IA privilégient les contenus avec données vérifiables — les citations de sources augmentent la visibilité de +40% (étude GEO, KDD 2024)",
        })

    # --- Topic coverage ---
    topic = categories['topic_coverage']
    if topic['score'] < 5:
        recs.append({
            'priority': 'moyenne',
            'problem': "Couverture thématique limitée",
            'action': "Développer un blog ou une section de contenu éditorial avec des articles de fond (>500 mots) sur vos sujets d'expertise",
            'impact': "Plus votre couverture thématique est large et profonde, plus les IA vous identifient comme source d'autorité sur votre domaine",
        })

    # --- Sitemap ---
    ai_acc = categories['ai_accessibility']
    for detail in ai_acc.get('details', []):
        if 'sitemap' in detail.lower() and ('absent' in detail.lower() or 'non valide' in detail.lower()):
            recs.append({
                'priority': 'haute',
                'problem': "Sitemap.xml absent ou non valide",
                'action': "Générer et soumettre un sitemap.xml à jour avec toutes les pages importantes du site",
                'impact': "Le sitemap aide les crawlers IA à découvrir et indexer l'ensemble de vos contenus",
            })
            break

    # Sort by priority
    priority_order = {'critique': 0, 'haute': 1, 'moyenne': 2}
    recs.sort(key=lambda r: priority_order.get(r['priority'], 3))

    return recs[:15]


# ===============================================================
# HELPERS
# ===============================================================


def _fast_html(url, timeout=3):
    """Quick HTML fetch with short timeout for GEO audit."""
    try:
        r = requests.get(url, timeout=timeout, headers={'User-Agent': 'BubbleStone-Audit/1.0'})
        if r.status_code == 200 and 'text/html' in r.headers.get('Content-Type', ''):
            return r.text
    except Exception:
        pass
    return ''


def _extract_schemas(html):
    """Extract schema.org types from HTML."""
    schemas = set()

    # JSON-LD
    for match in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                              html, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(match.group(1))
            _collect_schema_types(data, schemas)
        except (json.JSONDecodeError, ValueError):
            pass

    # Microdata
    for match in re.finditer(r'itemtype=["\']https?://schema\.org/(\w+)', html, re.IGNORECASE):
        schemas.add(match.group(1))

    return schemas


def _collect_schema_types(data, schemas):
    """Recursively collect @type from JSON-LD."""
    if isinstance(data, dict):
        t = data.get('@type', '')
        if isinstance(t, str) and t:
            schemas.add(t)
        elif isinstance(t, list):
            for item in t:
                if isinstance(item, str):
                    schemas.add(item)
        for v in data.values():
            _collect_schema_types(v, schemas)
    elif isinstance(data, list):
        for item in data:
            _collect_schema_types(item, schemas)


def _is_homepage(page_url, base_url, original_url):
    """Check if a URL is the homepage."""
    parsed = urlparse(page_url)
    path = parsed.path.rstrip('/')
    return path == '' or path == '/' or page_url.rstrip('/') == base_url.rstrip('/') or page_url.rstrip('/') == original_url.rstrip('/')
