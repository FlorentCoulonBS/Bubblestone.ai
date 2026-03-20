#!/usr/bin/env python3
"""BubbleStone.ai — Python audit orchestrator. Replaces audit.sh for webapp mode."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from urllib.parse import urlparse

DB_PATH = os.environ.get('DB_PATH', '/data/audits.db')

# ---------------------------------------------------------------------------
# i18n — Bilingual support (fr/en)
# ---------------------------------------------------------------------------
I18N = {
    'fr': {
        # Deep SEO check names
        'title_present': "Title présent",
        'title_length': "Title < 60 caractères",
        'meta_desc_present': "Meta description présente",
        'meta_desc_length': "Meta description < 155 car.",
        'h1_present': "H1 présent",
        'h1_unique': "H1 unique",
        'h2_present': "H2 présents",
        'canonical_set': "Canonical définie",
        'og_complete': "Open Graph complet",
        'schema_org': "Schema.org / données structurées",
        'images_alt': "Images avec alt",
        'content_sufficient': "Contenu suffisant (>300 mots)",
        'sitemap_accessible': "Sitemap.xml accessible",
        'robots_configured': "Robots.txt configuré",
        'https_active': "HTTPS actif",
        'analysis_error': "Erreur d'analyse",
        # Deep SEO details
        'absent': "Absent",
        'absent_f': "Absente",
        'characters': "caractères",
        'chars_short': "car.",
        'found_h1': "{n} H1 trouvé(s)",
        'found_h2': "{n} H2 trouvé(s)",
        'og_tags': "{n} balises OG",
        'found': "Trouvé",
        'without_alt': "{a}/{b} sans alt",
        'no_image': "Aucune image",
        'words': "{n} mots",
        'sitemap_soft404': "Soft 404 — page existe mais pas de sitemap XML valide",
        'entries': "{n} entrées",
        'error': "Erreur",
        # Recommendations
        'fix_seo_issues': "Corriger les problèmes SEO identifiés",
        'perf_optimize': "Optimiser les performances (images, CSS/JS, cache)",
        'perf_cwv': "Améliorer les Core Web Vitals pour un meilleur référencement",
        'add_security_headers': "Ajouter les headers de sécurité manquants : {headers}",
        'fix_high_vulns': "Corriger {n} vulnérabilité(s) critique(s)",
        'fix_med_vulns': "Corriger {n} vulnérabilité(s) moyennes (CSRF, clickjacking...)",
        'fix_a11y': "Résoudre {n} problème(s) d'accessibilité",
        'fix_broken_links': "Corriger {n} liens cassés (404)",
        'orphan_pages': "{n} pages orphelines sans maillage interne",
        'missing_canonical': "{n} pages sans canonical",
        'images_no_alt': "{n} images sans attribut alt",
        'images_oversized': "{n} images surdimensionnées (>200KB) à optimiser",
        'images_not_webp': "{n} images non optimisées (convertir en WebP/AVIF)",
        'images_no_lazy': "{n} images sans lazy loading",
        'maintain_good': "Maintenir les bonnes pratiques actuelles et surveiller régulièrement",
        # V2: Maillage / Schema / Duplicates recommendations
        'maillage_orphans': "{n} pages orphelines détectées — ajouter des liens internes vers ces pages",
        'maillage_deep': "{n} pages à profondeur > 3 — rapprocher du homepage via le maillage interne",
        'maillage_weak': "{n} pages reçoivent moins de 2 liens internes — renforcer le maillage",
        'schema_missing_org': "Schema Organization/LocalBusiness manquant — essentiel pour le SEO local",
        'schema_missing_breadcrumb': "Schema BreadcrumbList manquant — améliore l'affichage dans les résultats Google",
        'schema_missing_faq': "Schema FAQPage manquant — peut générer des rich snippets FAQ",
        'schema_low_coverage': "Seulement {n}% des pages ont des données structurées — viser > 80%",
        'duplicate_titles': "{n} groupes de pages avec des titles identiques — chaque page doit avoir un title unique",
        'duplicate_descs': "{n} groupes de pages avec des meta descriptions identiques — diversifier",
        'thin_content': "{n} pages avec contenu insuffisant (<300 mots) — enrichir ou consolider",
        'redirect_long_chains': "{n} chaînes de redirections > 1 saut — réduire à 1 redirection directe",
        'cwv_poor_lcp': "{n} pages avec LCP > 4s — optimiser le chargement du contenu principal",
        'cwv_poor_cls': "{n} pages avec CLS > 0.25 — stabiliser la mise en page visuelle",
        # Priorities & categories
        'high': "Haute",
        'medium': "Moyenne",
        'low': "Basse",
        'cat_security': "Sécurité",
        'cat_accessibility': "Accessibilité",
        'cat_general': "Général",
        'cat_maillage': "Maillage interne",
        'cat_schema': "Données structurées",
        'cat_content': "Contenu",
        # Summary
        'summary_good': "Le site {domain} présente de bons résultats globaux avec un score moyen de {avg}/100.",
        'summary_avg': "Le site {domain} présente des résultats moyens ({avg}/100). Des améliorations sont recommandées.",
        'summary_poor': "Le site {domain} nécessite des améliorations significatives (score moyen : {avg}/100).",
    },
    'en': {
        # Deep SEO check names
        'title_present': "Title present",
        'title_length': "Title under 60 characters",
        'meta_desc_present': "Meta description present",
        'meta_desc_length': "Meta description under 155 chars",
        'h1_present': "H1 present",
        'h1_unique': "H1 unique",
        'h2_present': "H2 tags present",
        'canonical_set': "Canonical defined",
        'og_complete': "Open Graph complete",
        'schema_org': "Schema.org / structured data",
        'images_alt': "Images with alt attribute",
        'content_sufficient': "Sufficient content (>300 words)",
        'sitemap_accessible': "Sitemap.xml accessible",
        'robots_configured': "Robots.txt configured",
        'https_active': "HTTPS active",
        'analysis_error': "Analysis error",
        # Deep SEO details
        'absent': "Missing",
        'absent_f': "Missing",
        'characters': "characters",
        'chars_short': "chars",
        'found_h1': "{n} H1 found",
        'found_h2': "{n} H2 found",
        'og_tags': "{n} OG tags",
        'found': "Found",
        'without_alt': "{a}/{b} without alt",
        'no_image': "No images",
        'words': "{n} words",
        'sitemap_soft404': "Soft 404 — page exists but no valid XML sitemap",
        'entries': "{n} entries",
        'error': "Error",
        # Recommendations
        'fix_seo_issues': "Fix identified SEO issues",
        'perf_optimize': "Optimize performance (images, CSS/JS, caching)",
        'perf_cwv': "Improve Core Web Vitals for better search ranking",
        'add_security_headers': "Add missing security headers: {headers}",
        'fix_high_vulns': "Fix {n} critical vulnerability(ies)",
        'fix_med_vulns': "Fix {n} medium vulnerability(ies) (CSRF, clickjacking...)",
        'fix_a11y': "Resolve {n} accessibility issue(s)",
        'fix_broken_links': "Fix {n} broken links (404)",
        'orphan_pages': "{n} orphan pages without internal linking",
        'missing_canonical': "{n} pages without canonical",
        'images_no_alt': "{n} images without alt attribute",
        'images_oversized': "{n} oversized images (>200KB) to optimize",
        'images_not_webp': "{n} unoptimized images (convert to WebP/AVIF)",
        'images_no_lazy': "{n} images without lazy loading",
        'maintain_good': "Maintain current best practices and monitor regularly",
        # V2: Maillage / Schema / Duplicates recommendations
        'maillage_orphans': "{n} orphan pages detected — add internal links pointing to these pages",
        'maillage_deep': "{n} pages at depth > 3 — bring closer to homepage via internal linking",
        'maillage_weak': "{n} pages receive fewer than 2 internal links — strengthen internal linking",
        'schema_missing_org': "Organization/LocalBusiness schema missing — essential for local SEO",
        'schema_missing_breadcrumb': "BreadcrumbList schema missing — improves Google search appearance",
        'schema_missing_faq': "FAQPage schema missing — can generate FAQ rich snippets",
        'schema_low_coverage': "Only {n}% of pages have structured data — aim for > 80%",
        'duplicate_titles': "{n} groups of pages with identical titles — each page should have a unique title",
        'duplicate_descs': "{n} groups of pages with identical meta descriptions — diversify",
        'thin_content': "{n} pages with insufficient content (<300 words) — enrich or consolidate",
        'redirect_long_chains': "{n} redirect chains > 1 hop — reduce to single direct redirects",
        'cwv_poor_lcp': "{n} pages with LCP > 4s — optimize main content loading",
        'cwv_poor_cls': "{n} pages with CLS > 0.25 — stabilize visual layout",
        # Priorities & categories
        'high': "High",
        'medium': "Medium",
        'low': "Low",
        'cat_security': "Security",
        'cat_accessibility': "Accessibility",
        'cat_general': "General",
        'cat_maillage': "Internal linking",
        'cat_schema': "Structured data",
        'cat_content': "Content",
        # Summary
        'summary_good': "The site {domain} shows good overall results with an average score of {avg}/100.",
        'summary_avg': "The site {domain} shows average results ({avg}/100). Improvements are recommended.",
        'summary_poor': "The site {domain} requires significant improvements (average score: {avg}/100).",
    },
}

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def update_status(audit_id, status, results=None):
    db = get_db()
    if results is not None:
        db.execute("UPDATE audits SET status=?, completed_at=?, results_json=? WHERE id=?",
                   (status, datetime.utcnow().isoformat(), json.dumps(results, ensure_ascii=False), audit_id))
    else:
        db.execute("UPDATE audits SET status=? WHERE id=?", (status, audit_id))
    db.commit()
    db.close()

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def score_color(score):
    if score is None: return "#9CA3AF"
    if score >= 80: return "#16A34A"
    if score >= 50: return "#F59E0B"
    return "#DC2626"

def extract_lighthouse(data):
    cats = data.get("categories", {})
    audits = data.get("audits", {})
    scores = {
        "performance": round(cats.get("performance", {}).get("score", 0) * 100),
        "seo": round(cats.get("seo", {}).get("score", 0) * 100),
        "accessibility": round(cats.get("accessibility", {}).get("score", 0) * 100),
        "best_practices": round(cats.get("best-practices", {}).get("score", 0) * 100),
    }
    def audit_val(key):
        a = audits.get(key, {})
        return a.get("displayValue", a.get("numericValue", "N/A"))
    cwv = {
        "LCP": audit_val("largest-contentful-paint"),
        "FID": audit_val("max-potential-fid"),
        "CLS": audit_val("cumulative-layout-shift"),
        "FCP": audit_val("first-contentful-paint"),
        "SI": audit_val("speed-index"),
        "TTI": audit_val("interactive"),
    }
    opportunities = []
    for key, audit in audits.items():
        if audit.get("details", {}).get("type") == "opportunity":
            savings = audit.get("details", {}).get("overallSavingsMs", 0)
            if savings > 100:
                opportunities.append({"title": audit.get("title", key), "savings_ms": round(savings)})
    opportunities.sort(key=lambda x: x["savings_ms"], reverse=True)
    seo_checks = {}
    seo_keys = ["document-title", "meta-description", "http-status-code", "is-crawlable",
                 "robots-txt", "hreflang", "canonical", "image-alt"]
    for k in seo_keys:
        a = audits.get(k, {})
        if a:
            seo_checks[a.get("title", k)] = {
                "score": a.get("score"),
                "value": a.get("displayValue", "")
            }
    a11y_issues = []
    for key, audit in audits.items():
        cat_ids = [r.get("id") for r in cats.get("accessibility", {}).get("auditRefs", [])]
        if key in cat_ids and audit.get("score") == 0:
            a11y_issues.append({"title": audit.get("title", key), "description": audit.get("description", "")})
    return scores, cwv, opportunities, seo_checks, a11y_issues

def extract_zap(data):
    # Alerts that are false positives or already covered by other audit modules
    ZAP_SUPPRESSED = {
        # CSP is checked separately via headers module
        'Content Security Policy (CSP) Header Not Set',
        "CSP: Wildcard Directive",
        "CSP: script-src unsafe-inline",
        "CSP: style-src unsafe-inline",
        # Anti-CSRF on public WP forms is normal (WP uses nonces on admin forms)
        'Absence of Anti-CSRF Tokens',
        # SRI is incompatible with GTM/dynamic script loaders
        'Sub Resource Integrity Attribute Missing',
        # jQuery bundled with WP core — flagged as "vulnerable" but maintained by WP team
        'Vulnerable JS Library',
        # Informational alerts that are not actionable
        'Cookie without SameSite Attribute',
        'Cookie Without Secure Flag',
        'X-Content-Type-Options Header Missing',  # checked in headers module
        'Strict-Transport-Security Header Not Set',  # checked in headers module
        'Missing Anti-clickjacking Header',  # checked via X-Frame-Options in headers module
        'Server Leaks Information via "X-Powered-By" HTTP Response Header Field(s)',
        'Information Disclosure - Suspicious Comments',
        'Timestamp Disclosure - Unix',
        'Modern Web Application',
    }

    alerts = []
    # API format: {"alerts": [{"alert": "...", "risk": "...", ...}]}
    alert_list = data.get("alerts", [])
    if isinstance(alert_list, list):
        # Deduplicate by alert name
        seen = {}
        for a in alert_list:
            name = a.get("name", a.get("alert", ""))
            if name in ZAP_SUPPRESSED:
                continue
            if name not in seen:
                seen[name] = {
                    "name": name,
                    "risk": a.get("riskdesc", a.get("risk", "")),
                    "description": a.get("description", a.get("desc", "")),
                    "count": 1,
                }
            else:
                seen[name]["count"] += 1
        alerts = sorted(seen.values(), key=lambda x: {"High": 0, "Medium": 1, "Low": 2}.get(x["risk"].split()[0] if x["risk"] else "", 3))
    # Fallback: site-based format (from file reports)
    if not alerts:
        site_list = data.get("site", [])
        if isinstance(site_list, list):
            for site in site_list:
                for alert in site.get("alerts", []):
                    name = alert.get("name", alert.get("alert", ""))
                    if name in ZAP_SUPPRESSED:
                        continue
                    alerts.append({
                        "name": name,
                        "risk": alert.get("riskdesc", alert.get("risk", "")),
                        "description": alert.get("desc", ""),
                        "count": len(alert.get("instances", [])),
                    })
    return alerts

def fetch_cwv_per_page(pages, max_pages=10):
    """Fetch Core Web Vitals for top pages via PageSpeed Insights API (free, no key)."""
    import requests as req
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Select top pages by traffic potential (200 status, most incoming links, shortest depth)
    ok_pages = [p for p in pages if p.get('status') == 200]
    # Sort by word count desc as a proxy for importance
    ok_pages.sort(key=lambda x: x.get('word_count', 0), reverse=True)
    urls_to_test = [p['url'] for p in ok_pages[:max_pages]]

    results = []
    PSI_API = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed'

    def _fetch_psi(page_url):
        try:
            import time as _time
            _time.sleep(12)  # Rate limit: ~5 requests/min for free API
            r = req.get(PSI_API, params={
                'url': page_url,
                'strategy': 'mobile',
                'category': 'performance',
            }, timeout=90)
            if r.status_code == 429:
                _time.sleep(30)  # Back off on rate limit
                r = req.get(PSI_API, params={
                    'url': page_url,
                    'strategy': 'mobile',
                    'category': 'performance',
                }, timeout=90)
            if r.status_code != 200:
                return {'url': page_url, 'error': f'HTTP {r.status_code}'}
            data = r.json()
            lhr = data.get('lighthouseResult', {})
            audits = lhr.get('audits', {})
            perf_score = lhr.get('categories', {}).get('performance', {}).get('score')
            perf_score = round(perf_score * 100) if perf_score is not None else None

            def _metric_val(key):
                a = audits.get(key, {})
                return {
                    'value': a.get('numericValue'),
                    'display': a.get('displayValue', 'N/A'),
                    'score': a.get('score'),
                }

            return {
                'url': page_url,
                'performance_score': perf_score,
                'lcp': _metric_val('largest-contentful-paint'),
                'fid': _metric_val('max-potential-fid'),
                'cls': _metric_val('cumulative-layout-shift'),
                'fcp': _metric_val('first-contentful-paint'),
                'tti': _metric_val('interactive'),
                'si': _metric_val('speed-index'),
            }
        except Exception as e:
            return {'url': page_url, 'error': str(e)[:200]}

    # Run sequentially to avoid rate limiting (PSI has strict limits)
    for page_url in urls_to_test:
        print(f"    [CWV] Testing {page_url[:80]}...")
        result = _fetch_psi(page_url)
        results.append(result)

    return results


def compute_maillage_score(crawl_results):
    """Compute an internal linking quality score (0-100) from crawl data."""
    maillage = crawl_results.get('maillage', {})
    if not maillage:
        return 0

    score = 100
    pages = maillage.get('pages', [])
    total = len(pages)
    if total == 0:
        return 0

    # Penalize orphan pages (-3 per orphan, max -30)
    orphan_count = maillage.get('orphan_count', 0)
    score -= min(30, orphan_count * 3)

    # Penalize deep pages (depth > 3), -2 per page, max -20
    deep_pages = sum(1 for p in pages if p.get('depth') is not None and p['depth'] > 3)
    score -= min(20, deep_pages * 2)

    # Penalize pages with 0 outgoing links, -2 per page, max -15
    no_outgoing = sum(1 for p in pages if p.get('outgoing', 0) == 0)
    score -= min(15, no_outgoing * 2)

    # Penalize low avg incoming links (< 2), -15
    avg_incoming = sum(p.get('incoming', 0) for p in pages) / max(total, 1)
    if avg_incoming < 2:
        score -= 15
    elif avg_incoming < 5:
        score -= 5

    # Bonus for good avg depth (<= 2)
    avg_depth = maillage.get('avg_depth', 99)
    if avg_depth <= 2:
        score = min(100, score + 10)
    elif avg_depth <= 3:
        score = min(100, score + 5)

    return max(0, score)


def run_deep_seo(url, lh_data, stack_data, lang='fr'):
    """BubbleStone deep SEO audit — goes beyond Lighthouse."""
    t = I18N.get(lang, I18N['fr'])
    import requests as req
    checks = []
    total = 0
    max_score = 0

    def check(name, passed, weight=10, detail=""):
        nonlocal total, max_score
        max_score += weight
        if passed:
            total += weight
        checks.append({"name": name, "passed": passed, "weight": weight, "detail": detail})

    try:
        r = req.get(url, timeout=15, headers={"User-Agent": "BubbleStone-Audit/1.0"})
        html = r.text.lower()
        from html.parser import HTMLParser

        # Parse basic tags
        title = ""
        h1s = []
        h2s = []
        imgs_no_alt = 0
        imgs_total = 0
        canonical = ""
        meta_desc = ""
        og_tags = {}
        schema_found = False
        word_count = 0

        class SEOParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self._tag = None
                self._data = []
            def handle_starttag(self, tag, attrs):
                self._tag = tag
                a = dict(attrs)
                if tag == 'img':
                    nonlocal imgs_total, imgs_no_alt
                    imgs_total += 1
                    if not a.get('alt', '').strip():
                        imgs_no_alt += 1
                if tag == 'link' and a.get('rel') == 'canonical':
                    nonlocal canonical
                    canonical = a.get('href', '')
                if tag == 'meta':
                    if a.get('name') == 'description':
                        nonlocal meta_desc
                        meta_desc = a.get('content', '')
                    if a.get('property', '').startswith('og:'):
                        og_tags[a['property']] = a.get('content', '')
            def handle_data(self, data):
                nonlocal title
                if self._tag == 'title' and not title:
                    title = data.strip()
            def handle_endtag(self, tag):
                self._tag = None

        # Count words in visible text (rough)
        import re
        text_only = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text_only = re.sub(r'<style[^>]*>.*?</style>', '', text_only, flags=re.DOTALL)
        text_only = re.sub(r'<[^>]+>', ' ', text_only)
        words = [w for w in text_only.split() if len(w) > 2]
        word_count = len(words)

        parser = SEOParser()
        parser.feed(r.text)

        # H1 count
        h1_count = r.text.lower().count('<h1')
        h2_count = r.text.lower().count('<h2')

        # Schema.org
        schema_found = 'application/ld+json' in html or 'itemtype=' in html

        # Checks
        check(t['title_present'], bool(title), 10, title[:60] if title else t['absent'])
        check(t['title_length'], len(title) <= 60 if title else False, 5,
              f"{len(title)} {t['characters']}" if title else "")
        check(t['meta_desc_present'], bool(meta_desc), 10,
              meta_desc[:155] if meta_desc else t['absent_f'])
        check(t['meta_desc_length'], len(meta_desc) <= 155 if meta_desc else False, 5,
              f"{len(meta_desc)} {t['chars_short']}" if meta_desc else "")
        check(t['h1_present'], h1_count > 0, 10, t['found_h1'].format(n=h1_count))
        check(t['h1_unique'], h1_count == 1, 5, f"{h1_count} H1" if h1_count != 1 else "OK")
        check(t['h2_present'], h2_count > 0, 5, t['found_h2'].format(n=h2_count))
        check(t['canonical_set'], bool(canonical), 10, canonical or t['absent_f'])
        check(t['og_complete'], all(k in og_tags for k in ['og:title', 'og:description', 'og:image']), 8,
              t['og_tags'].format(n=len(og_tags)))
        check(t['schema_org'], schema_found, 10,
              t['found'] if schema_found else t['absent'])
        check(t['images_alt'], imgs_no_alt == 0 if imgs_total > 0 else True, 8,
              t['without_alt'].format(a=imgs_no_alt, b=imgs_total) if imgs_total else t['no_image'])
        check(t['content_sufficient'], word_count >= 300, 8,
              t['words'].format(n=word_count))

        # Sitemap
        try:
            sm = req.get(url.rstrip('/') + '/sitemap.xml', timeout=10)
            has_xml = '<url' in sm.text.lower() or '<sitemap' in sm.text.lower()
            sitemap_ok = sm.status_code == 200 and has_xml
            if sm.status_code == 200 and not has_xml:
                detail = t['sitemap_soft404']
            elif sm.status_code != 200:
                detail = f'HTTP {sm.status_code}'
            else:
                detail = t['entries'].format(n=sm.text.lower().count("<url") + sm.text.lower().count("<sitemap"))
            check(t['sitemap_accessible'], sitemap_ok, 8, detail)
        except:
            check(t['sitemap_accessible'], False, 8, t['error'])

        # Robots.txt
        try:
            rb = req.get(url.rstrip('/') + '/robots.txt', timeout=10)
            robots_ok = rb.status_code == 200 and len(rb.text) > 10
            check(t['robots_configured'], robots_ok, 5,
                  f"HTTP {rb.status_code}")
        except:
            check(t['robots_configured'], False, 5, t['error'])

        # HTTPS
        check(t['https_active'], url.startswith('https'), 8, "")

    except Exception as e:
        checks.append({"name": t['analysis_error'], "passed": False, "weight": 0, "detail": str(e)})

    score = round(total / max_score * 100) if max_score > 0 else 0
    return {"score": score, "checks": checks, "word_count": word_count if 'word_count' in dir() else 0}


def build_recommendations(scores, headers_data, zap_alerts, a11y_issues, deep_seo=None, crawl=None, ssl_data=None, dns_data=None, wp_data=None, cwv_per_page=None, lang='fr'):
    t = I18N.get(lang, I18N['fr'])
    recs = []
    # SEO recommendations from deep audit
    if deep_seo:
        failed = [c for c in deep_seo.get('checks', []) if not c['passed']]
        for c in failed[:5]:
            recs.append({"text": f"SEO : {c['name']} — {c['detail']}", "priority": t['high'] if c['weight'] >= 8 else t['medium'], "category": "SEO"})
    elif scores.get("seo", 0) < 80:
        recs.append({"text": t['fix_seo_issues'], "priority": t['high'], "category": "SEO"})
    # Performance
    if scores.get("performance", 0) < 50:
        recs.append({"text": t['perf_optimize'], "priority": t['high'], "category": "Performance"})
    elif scores.get("performance", 0) < 80:
        recs.append({"text": t['perf_cwv'], "priority": t['medium'], "category": "Performance"})
    # Security
    h = headers_data.get("headers", {})
    missing = [k for k, v in h.items() if not v.get("present")]
    if missing:
        recs.append({"text": t['add_security_headers'].format(headers=', '.join(missing[:5])), "priority": t['high'], "category": t['cat_security']})
    high_alerts = [a for a in zap_alerts if "High" in a.get("risk", "")]
    med_alerts = [a for a in zap_alerts if "Medium" in a.get("risk", "")]
    if high_alerts:
        recs.append({"text": t['fix_high_vulns'].format(n=len(high_alerts)), "priority": t['high'], "category": t['cat_security']})
    if med_alerts:
        recs.append({"text": t['fix_med_vulns'].format(n=len(med_alerts)), "priority": t['high'], "category": t['cat_security']})
    # Accessibility
    if a11y_issues:
        recs.append({"text": t['fix_a11y'].format(n=len(a11y_issues)), "priority": t['medium'], "category": t['cat_accessibility']})
    # Crawl recommendations
    if crawl:
        bl = crawl.get('broken_links', [])
        if bl:
            recs.append({"text": t['fix_broken_links'].format(n=len(bl)), "priority": t['high'], "category": "SEO"})
        op = crawl.get('orphan_pages', [])
        if op:
            recs.append({"text": t['orphan_pages'].format(n=len(op)), "priority": t['medium'], "category": "SEO"})
        mc = crawl.get('missing_canonical', [])
        if len(mc) > 3:
            recs.append({"text": t['missing_canonical'].format(n=len(mc)), "priority": t['high'], "category": "SEO"})
    # Image recommendations
    if crawl:
        img_stats = crawl.get('image_stats', {})
        if img_stats.get('without_alt', 0) > 0:
            recs.append({"text": t['images_no_alt'].format(n=img_stats['without_alt']), "priority": t['high'], "category": "SEO"})
        if img_stats.get('oversized'):
            recs.append({"text": t['images_oversized'].format(n=len(img_stats['oversized'])), "priority": t['high'], "category": "Performance"})
        if img_stats.get('not_webp', 0) > 5:
            recs.append({"text": t['images_not_webp'].format(n=img_stats['not_webp']), "priority": t['medium'], "category": "Performance"})
        if img_stats.get('without_lazy', 0) > 5:
            recs.append({"text": t['images_no_lazy'].format(n=img_stats['without_lazy']), "priority": t['medium'], "category": "Performance"})
    # SSL recommendations
    if ssl_data:
        ssl_issues = [c for c in ssl_data.get('checks', []) if not c['passed']]
        for c in ssl_issues[:3]:
            recs.append({"text": f"SSL/TLS : {c['name']} — {c['detail']}", "priority": t['high'], "category": t['cat_security']})
    # DNS/Email recommendations
    if dns_data:
        dns_issues = [c for c in dns_data.get('checks', []) if not c['passed']]
        for c in dns_issues[:3]:
            recs.append({"text": f"Email/DNS : {c['name']} — {c['detail']}", "priority": t['high'] if 'DMARC' in c['name'] or 'SPF' in c['name'] else t['medium'], "category": t['cat_security']})
    # WordPress recommendations
    if wp_data:
        wp_issues = [c for c in wp_data.get('checks', []) if not c['passed']]
        for c in wp_issues[:3]:
            recs.append({"text": f"WordPress : {c['name']} — {c['detail']}", "priority": t['high'], "category": t['cat_security']})

    # V2: Maillage interne recommendations
    if crawl:
        maillage = crawl.get('maillage', {})
        if maillage:
            orphan_count = maillage.get('orphan_count', 0)
            if orphan_count > 0:
                recs.append({"text": t['maillage_orphans'].format(n=orphan_count), "priority": t['high'], "category": t.get('cat_maillage', 'SEO')})
            deep_pages = sum(1 for p in maillage.get('pages', []) if p.get('depth') is not None and p['depth'] > 3)
            if deep_pages > 3:
                recs.append({"text": t['maillage_deep'].format(n=deep_pages), "priority": t['medium'], "category": t.get('cat_maillage', 'SEO')})
            weak_pages = sum(1 for p in maillage.get('pages', []) if p.get('incoming', 0) < 2 and not p.get('is_orphan'))
            if weak_pages > 5:
                recs.append({"text": t['maillage_weak'].format(n=weak_pages), "priority": t['medium'], "category": t.get('cat_maillage', 'SEO')})

        # V2: Schema.org recommendations
        schema_inv = crawl.get('schema_inventory', {})
        if schema_inv:
            checklist = schema_inv.get('checklist', {})
            if not checklist.get('Organization', {}).get('present') and not checklist.get('LocalBusiness', {}).get('present'):
                recs.append({"text": t['schema_missing_org'], "priority": t['high'], "category": t.get('cat_schema', 'SEO')})
            if not checklist.get('BreadcrumbList', {}).get('present'):
                recs.append({"text": t['schema_missing_breadcrumb'], "priority": t['medium'], "category": t.get('cat_schema', 'SEO')})
            if not checklist.get('FAQPage', {}).get('present'):
                recs.append({"text": t['schema_missing_faq'], "priority": t['low'], "category": t.get('cat_schema', 'SEO')})
            total_pages = schema_inv.get('pages_with_schema', 0) + schema_inv.get('pages_without_schema', 0)
            if total_pages > 0:
                coverage_pct = round(schema_inv.get('pages_with_schema', 0) / total_pages * 100)
                if coverage_pct < 50:
                    recs.append({"text": t['schema_low_coverage'].format(n=coverage_pct), "priority": t['high'], "category": t.get('cat_schema', 'SEO')})

        # V2: Duplicate content recommendations
        duplicates = crawl.get('duplicates', {})
        if duplicates:
            dup_titles = duplicates.get('duplicate_titles', [])
            if dup_titles:
                recs.append({"text": t['duplicate_titles'].format(n=len(dup_titles)), "priority": t['high'], "category": t.get('cat_content', 'SEO')})
            dup_descs = duplicates.get('duplicate_descriptions', [])
            if dup_descs:
                recs.append({"text": t['duplicate_descs'].format(n=len(dup_descs)), "priority": t['medium'], "category": t.get('cat_content', 'SEO')})

        # V2: Thin content
        thin = crawl.get('thin_content', [])
        if len(thin) > 3:
            recs.append({"text": t['thin_content'].format(n=len(thin)), "priority": t['medium'], "category": t.get('cat_content', 'SEO')})

        # V2: Redirect chains
        redirect_analysis = crawl.get('redirect_analysis', [])
        long_chains = [r for r in redirect_analysis if r.get('is_long_chain')]
        if long_chains:
            recs.append({"text": t['redirect_long_chains'].format(n=len(long_chains)), "priority": t['high'], "category": "SEO"})

    # V2: CWV per page recommendations
    if cwv_per_page:
        poor_lcp = sum(1 for c in cwv_per_page if not c.get('error') and c.get('lcp', {}).get('value') is not None and c['lcp']['value'] > 4000)
        if poor_lcp > 0:
            recs.append({"text": t['cwv_poor_lcp'].format(n=poor_lcp), "priority": t['high'], "category": "Performance"})
        poor_cls = sum(1 for c in cwv_per_page if not c.get('error') and c.get('cls', {}).get('value') is not None and c['cls']['value'] > 0.25)
        if poor_cls > 0:
            recs.append({"text": t['cwv_poor_cls'].format(n=poor_cls), "priority": t['medium'], "category": "Performance"})

    if not recs:
        recs.append({"text": t['maintain_good'], "priority": t['low'], "category": t['cat_general']})
    return recs[:15]

def run_audit(audit_id, url, wp_admin_url="", wp_username="", wp_password="", htaccess_user="", htaccess_pass="", lang='fr'):
    update_status(audit_id, 'running')
    tmpdir = tempfile.mkdtemp(prefix=f'audit_{audit_id}_')

    # 1. Lighthouse (median of 3 runs for stable scores)
    print(f"[{audit_id}] Running Lighthouse (3 runs, taking median)...")
    lh_path = os.path.join(tmpdir, 'lighthouse.json')
    lh_scores = []
    lh_best_path = lh_path
    for lh_run in range(3):
        run_path = os.path.join(tmpdir, f'lighthouse_run{lh_run}.json')
        subprocess.run([
            'lighthouse', url,
            '--chrome-flags=--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage --js-flags=--max-old-space-size=512',
            '--output=json', f'--output-path={run_path}',
            '--only-categories=performance,seo,accessibility,best-practices',
            '--quiet'
        ], capture_output=True, timeout=300)
        try:
            with open(run_path) as _f:
                _d = json.load(_f)
                perf = _d.get('categories', {}).get('performance', {}).get('score', 0)
                lh_scores.append((perf, run_path))
                print(f"[{audit_id}]   Run {lh_run+1}: performance={round(perf*100)}")
        except Exception:
            pass
    # Pick the median run (or best of 2 if one failed)
    if lh_scores:
        lh_scores.sort(key=lambda x: x[0])
        median_idx = len(lh_scores) // 2
        lh_best_path = lh_scores[median_idx][1]
        print(f"[{audit_id}]   Median: performance={round(lh_scores[median_idx][0]*100)}")
    if os.path.exists(lh_best_path):
        shutil.copy2(lh_best_path, lh_path)

    # 2. ZAP (daemon mode via API)
    print(f"[{audit_id}] Running ZAP...")
    zap_path = os.path.join(tmpdir, 'zap.json')
    zap_port = 18080 + (audit_id % 100)
    xvfb = subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1024x768x24'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ['DISPLAY'] = ':99'
    zap_proc = None
    try:
        # Start ZAP daemon
        zap_env = os.environ.copy()
        zap_env['JAVA_OPTS'] = '-Xmx512m'
        zap_proc = subprocess.Popen([
            '/opt/zaproxy/zap.sh', '-daemon',
            '-port', str(zap_port),
            '-config', 'api.disablekey=true',
            '-config', 'api.addrs.addr.name=.*',
            '-config', 'api.addrs.addr.regex=true',
            '-config', 'spider.maxDuration=2',
            '-config', 'spider.thread=2'
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=zap_env)

        # Wait for ZAP to start
        import time, requests as req
        zap_api = f'http://127.0.0.1:{zap_port}'
        for _ in range(60):
            try:
                r = req.get(f'{zap_api}/JSON/core/view/version/', timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(2)

        # Spider the target
        req.get(f'{zap_api}/JSON/spider/action/scan/', params={'url': url, 'maxChildren': 10}, timeout=10)
        for _ in range(60):
            r = req.get(f'{zap_api}/JSON/spider/view/status/', timeout=5).json()
            if int(r.get('status', 100)) >= 100:
                break
            time.sleep(2)

        # Wait for passive scan
        time.sleep(10)
        for _ in range(30):
            r = req.get(f'{zap_api}/JSON/pscan/view/recordsToScan/', timeout=5).json()
            if int(r.get('recordsToScan', 0)) == 0:
                break
            time.sleep(2)

        # Get alerts
        alerts_resp = req.get(f'{zap_api}/JSON/core/view/alerts/', params={'baseurl': url}, timeout=10)
        with open(zap_path, 'w') as f:
            json.dump(alerts_resp.json(), f)

    except Exception as e:
        print(f"[{audit_id}] ZAP error: {e}")
    finally:
        if zap_proc:
            zap_proc.terminate()
            zap_proc.wait(timeout=10)
        xvfb.terminate()

    # 3. Headers
    print(f"[{audit_id}] Checking headers...")
    headers_path = os.path.join(tmpdir, 'headers.json')
    subprocess.run(['python3', '/app/check_headers.py', url],
                   stdout=open(headers_path, 'w'), stderr=subprocess.DEVNULL, timeout=60)

    # 4. Stack detection
    print(f"[{audit_id}] Detecting stack...")
    stack_path = os.path.join(tmpdir, 'stack.json')
    subprocess.run(['python3', '/app/detect_stack.py', url],
                   stdout=open(stack_path, 'w'), stderr=subprocess.DEVNULL, timeout=60)

    # 5. Aggregate results
    print(f"[{audit_id}] Aggregating results...")
    lh_data = load_json(lh_path)
    zap_data = load_json(zap_path)
    headers_data = load_json(headers_path)
    stack_data = load_json(stack_path)

    scores, cwv, opportunities, seo_checks, a11y_issues = extract_lighthouse(lh_data)
    zap_alerts = extract_zap(zap_data)

    # 5b. Deep SEO audit (BubbleStone)
    print(f"[{audit_id}] Running deep SEO analysis...")
    deep_seo = run_deep_seo(url, lh_data, stack_data, lang=lang)
    # 5c. Site crawl
    print(f"[{audit_id}] Crawling site...")
    from crawler import crawl_site
    crawl_results = crawl_site(url, tmpdir)

    # 5c-bis. Core Web Vitals per page (PageSpeed Insights API)
    print(f"[{audit_id}] Fetching Core Web Vitals per page (top 10)...")
    cwv_per_page = []
    try:
        cwv_per_page = fetch_cwv_per_page(crawl_results.get('pages', []), max_pages=10)
        ok_cwv = [c for c in cwv_per_page if not c.get('error')]
        print(f"[{audit_id}] CWV per page: {len(ok_cwv)} pages tested successfully")
    except Exception as e:
        print(f"[{audit_id}] CWV per page error: {e}")

    # 5c-ter. Internal linking score
    maillage_score = compute_maillage_score(crawl_results)
    print(f"[{audit_id}] Maillage interne score: {maillage_score}/100")

    # 5d. Migration analysis
    print(f"[{audit_id}] Analyzing migration effort...")
    from migration_analysis import analyze_migration
    migration = analyze_migration(url, crawl_results, stack_data, deep_seo, lh_data)

    # 5e. GEO Audit
    print(f"[{audit_id}] Auditing GEO readiness...")
    from geo_audit import audit_geo
    geo_results = audit_geo(url, crawl_results, stack_data, deep_seo)

    # 5f. Responsive check
    print(f"[{audit_id}] Checking responsive design...")
    from responsive_check import check_responsive
    responsive = check_responsive(url, lh_data)

    # 5g. SSL Deep Analysis
    print(f"[{audit_id}] Deep SSL/TLS analysis...")
    try:
        from ssl_deep import analyze_ssl
        ssl_results = analyze_ssl(url)
    except Exception as e:
        print(f"[{audit_id}] SSL analysis error: {e}")
        ssl_results = {"score": 0, "tls_versions": [], "certificate": {}, "ciphers": [], "issues": [str(e)], "checks": []}

    # 5h. DNS & Email Authentication
    print(f"[{audit_id}] DNS & Email audit...")
    try:
        from dns_email import audit_dns_email
        dns_results = audit_dns_email(url)
    except Exception as e:
        print(f"[{audit_id}] DNS/Email audit error: {e}")
        dns_results = {"score": 0, "spf": {"present": False, "record": ""}, "dmarc": {"present": False, "record": "", "policy": ""}, "dkim": {"found": False, "selector": ""}, "mx": [], "dnssec": False, "caa": [], "checks": []}

    # 5i. WordPress scan (if applicable)
    wp_results = None
    if stack_data.get('cms') == 'WordPress':
        print(f"[{audit_id}] WordPress vulnerability scan...")
        try:
            from wordpress_scan import scan_wordpress
            wp_results = scan_wordpress(url, stack_data)
        except Exception as e:
            print(f"[{audit_id}] WordPress scan error: {e}")

    # Security score = headers + ZAP + SSL + DNS/Email (+ WP if applicable)
    headers_score = headers_data.get('score', 0)
    # ZAP: start at 100, deduct per alert severity
    zap_score = 100
    for a in zap_alerts:
        risk = a.get('risk', '').split()[0] if a.get('risk') else ''
        if risk == 'High':
            zap_score -= 20
        elif risk == 'Medium':
            zap_score -= 10
        elif risk == 'Low':
            zap_score -= 3
    zap_score = max(0, zap_score)
    ssl_score = ssl_results.get('score', 0)
    dns_score = dns_results.get('score', 0)
    if wp_results:
        security_score = int(headers_score*0.25 + zap_score*0.25 + ssl_score*0.20 + dns_score*0.15 + wp_results['score']*0.15)
    else:
        security_score = int(headers_score*0.30 + zap_score*0.30 + ssl_score*0.25 + dns_score*0.15)
    # SEO score = BubbleStone deep audit (primary), Lighthouse shown separately
    deep_seo_score = deep_seo.get('score', scores.get('seo', 0))
    lighthouse_seo = scores.get('seo', 0)

    all_scores = {
        'performance': scores.get('performance', 0),
        'seo': deep_seo_score,
        'accessibility': scores.get('accessibility', 0),
        'security': security_score,
        'geo': geo_results['score'],
        'responsive': responsive.get('score', 0),
    }
    recommendations = build_recommendations(all_scores, headers_data, zap_alerts, a11y_issues, deep_seo, crawl_results, ssl_results, dns_results, wp_results, cwv_per_page=cwv_per_page, lang=lang)

    # Build summary
    t = I18N.get(lang, I18N['fr'])
    avg = sum(all_scores.values()) / max(len(all_scores), 1)
    domain = urlparse(url).netloc.replace('www.', '')
    if avg >= 75:
        summary = t['summary_good'].format(domain=domain, avg=f"{avg:.0f}")
    elif avg >= 50:
        summary = t['summary_avg'].format(domain=domain, avg=f"{avg:.0f}")
    else:
        summary = t['summary_poor'].format(domain=domain, avg=f"{avg:.0f}")

    results = {
        'scores': all_scores,
        'lighthouse_seo': lighthouse_seo,
        'deep_seo': deep_seo,
        'cwv': cwv,
        'opportunities': opportunities,
        'seo_checks': seo_checks,
        'a11y_issues': a11y_issues,
        'headers': headers_data,
        'zap_alerts': zap_alerts,
        'stack': stack_data,
        'crawl': crawl_results,
        'recommendations': recommendations,
        'summary': summary,
        'migration': migration,
        'geo': geo_results,
        'responsive': responsive,
        'image_stats': crawl_results.get('image_stats', {}),
        'images': crawl_results.get('images', []),
        'ssl_deep': ssl_results,
        'dns_email': dns_results,
        'cwv_per_page': cwv_per_page,
        'maillage_score': maillage_score,
    }
    # 5j. WordPress Internal Audit (authenticated)
    wp_internal = None
    if wp_username and wp_password:
        print(f"[{audit_id}] WordPress internal audit (authenticated)...")
        try:
            from wordpress_internal import scan_wordpress_internal
            wp_internal = scan_wordpress_internal(url, wp_admin_url, wp_username, wp_password, htaccess_user, htaccess_pass)
            if wp_internal.get('authenticated'):
                print(f"[{audit_id}] WP internal audit score: {wp_internal['score']}/100")
            else:
                print(f"[{audit_id}] WP internal: authentication failed")
        except Exception as e:
            print(f"[{audit_id}] WP internal audit error: {e}")

    if wp_results:
        results['wordpress'] = wp_results
    if wp_internal and wp_internal.get('authenticated'):
        results['wordpress_internal'] = wp_internal

    update_status(audit_id, 'done', results)
    print(f"[{audit_id}] Done!")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('audit_id', type=int)
    parser.add_argument('url')
    parser.add_argument('--wp-admin', default='')
    parser.add_argument('--wp-user', default='')
    parser.add_argument('--wp-pass', default='')
    parser.add_argument('--htaccess-user', default='')
    parser.add_argument('--htaccess-pass', default='')
    parser.add_argument('--lang', default='fr', choices=['fr', 'en'])
    args = parser.parse_args()
    try:
        run_audit(args.audit_id, args.url,
                  wp_admin_url=args.wp_admin, wp_username=args.wp_user, wp_password=args.wp_pass,
                  htaccess_user=args.htaccess_user, htaccess_pass=args.htaccess_pass,
                  lang=args.lang)
    except Exception as e:
        print(f"[{args.audit_id}] ERROR: {e}")
        update_status(args.audit_id, 'error')
