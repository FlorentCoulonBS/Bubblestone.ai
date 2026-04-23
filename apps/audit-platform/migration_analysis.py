#!/usr/bin/env python3
"""BubbleStone.ai — Migration analysis toward Astro."""
import re
from urllib.parse import urlparse


def _classify_pages(crawl_data):
    """Classify crawled pages as static or dynamic."""
    pages = crawl_data.get("pages", [])
    static_pages = []
    dynamic_pages = []
    thin_pages = []
    rich_pages = []
    total_words = 0
    images = set()
    pdfs = []

    dynamic_signals = [
        "<form", "ajax", "fetch(", "xmlhttprequest", "wp-admin",
        "add-to-cart", "woocommerce", "cart", "checkout",
        "login", "register", "account", "member",
    ]

    for page in pages:
        url = page.get("url", "")
        html = page.get("html", "").lower() if page.get("html") else ""
        word_count = page.get("word_count", 0)
        total_words += word_count

        if word_count < 100:
            thin_pages.append(url)
        elif word_count >= 300:
            rich_pages.append(url)

        # Collect assets
        for img in page.get("images", []):
            images.add(img)
        for link in page.get("links", []):
            if link.lower().endswith(".pdf"):
                pdfs.append(link)

        is_dynamic = any(sig in html for sig in dynamic_signals)
        if is_dynamic:
            dynamic_pages.append(url)
        else:
            static_pages.append(url)

    total = len(pages) if pages else crawl_data.get("total_pages", 0)
    if not pages:
        # Fallback: estimate from total_pages
        static_count = max(0, total - len(dynamic_pages))
        return {
            "total": total,
            "static": static_count,
            "dynamic": len(dynamic_pages),
            "thin": len(thin_pages),
            "rich": len(rich_pages),
        }, total_words, images, pdfs

    return {
        "total": total or len(static_pages) + len(dynamic_pages),
        "static": len(static_pages),
        "dynamic": len(dynamic_pages),
        "thin": len(thin_pages),
        "rich": len(rich_pages),
    }, total_words, images, pdfs


def _detect_features(crawl_data, stack_data):
    """Detect features from crawl and stack data."""
    features = []
    all_html = ""
    all_urls = []

    for page in crawl_data.get("pages", []):
        all_html += (page.get("html", "") or "").lower() + " "
        all_urls.append((page.get("url", "") or "").lower())

    techs = [t.lower() for t in stack_data.get("technologies", [])]
    cms = (stack_data.get("cms") or "").lower()
    all_text = all_html + " ".join(techs) + " " + cms

    def has(*keywords):
        return any(k in all_text for k in keywords)

    def has_url(*patterns):
        return any(any(p in u for p in patterns) for u in all_urls)

    # Contact forms
    if has("<form", "contact-form-7", "cf7", "wpcf7", "wpforms", "gravity-form", "forminator"):
        source = "Contact Form 7" if has("contact-form-7", "cf7", "wpcf7") else \
                 "WPForms" if has("wpforms") else \
                 "Gravity Forms" if has("gravity-form") else \
                 "Formulaire HTML"
        features.append({
            "name": "Formulaire de contact", "detected": True, "source_plugin": source,
            "effort": "faible", "effort_days": 0.5,
            "solution_astro": "Formspree ou Resend API + composant Astro", "icon": "📝"
        })

    # Search
    if has("?s=", "search-form", "role=\"search\"", "type=\"search\""):
        features.append({
            "name": "Recherche interne", "detected": True, "source_plugin": "WordPress Search",
            "effort": "moyen", "effort_days": 1.5,
            "solution_astro": "Pagefind (statique) ou Algolia (avancé)", "icon": "🔍"
        })

    # Job listings
    if has("wp-job-manager", "job_listing", "offres-emploi", "careers"):
        features.append({
            "name": "Offres d'emploi", "detected": True, "source_plugin": "WP Job Manager",
            "effort": "élevé", "effort_days": 5,
            "solution_astro": "API headless + SSR Astro ou intégration ATS", "icon": "💼"
        })

    # Blog
    if has_url("/blog", "/actualites", "/actualite", "/news", "/articles"):
        features.append({
            "name": "Blog / Actualités", "detected": True, "source_plugin": "WordPress Posts",
            "effort": "faible", "effort_days": 2,
            "solution_astro": "Astro Content Collections + MDX", "icon": "📰"
        })

    # Multilingual
    if has("hreflang", "polylang", "wpml", "translatepress") or has_url("/en/", "/fr/", "/de/", "/es/"):
        source = "WPML" if has("wpml") else "Polylang" if has("polylang") else "hreflang tags"
        features.append({
            "name": "Multilingue", "detected": True, "source_plugin": source,
            "effort": "moyen", "effort_days": 3,
            "solution_astro": "Astro i18n routing + collections par langue", "icon": "🌐"
        })

    # E-commerce
    if has("woocommerce", "wc-cart", "add-to-cart", "shopify", "snipcart", "panier"):
        source = "WooCommerce" if has("woocommerce") else "Shopify" if has("shopify") else "E-commerce"
        features.append({
            "name": "E-commerce", "detected": True, "source_plugin": source,
            "effort": "élevé", "effort_days": 10,
            "solution_astro": "Shopify Headless / Snipcart / Stripe", "icon": "🛒"
        })

    # Member area
    if has("wp-login", "membre", "account", "my-account", "espace-client", "login"):
        features.append({
            "name": "Espace membre / Login", "detected": True, "source_plugin": "WordPress Auth",
            "effort": "élevé", "effort_days": 5,
            "solution_astro": "Auth.js / Clerk / Supabase Auth", "icon": "🔐"
        })

    # Newsletter
    if has("mailchimp", "mailjet", "newsletter", "sendinblue", "brevo", "mc4wp"):
        source = "Mailchimp" if has("mailchimp") else "Brevo" if has("sendinblue", "brevo") else "Mailjet" if has("mailjet") else "Newsletter"
        features.append({
            "name": "Newsletter", "detected": True, "source_plugin": source,
            "effort": "faible", "effort_days": 0.5,
            "solution_astro": "API directe (Mailchimp/Brevo) + composant formulaire", "icon": "📧"
        })

    # Chat
    if has("crisp", "intercom", "tawk", "tidio", "hubspot-messages", "drift", "zendesk"):
        source = "Crisp" if has("crisp") else "Intercom" if has("intercom") else "Tawk.to" if has("tawk") else "Chat widget"
        features.append({
            "name": "Chat / Chatbot", "detected": True, "source_plugin": source,
            "effort": "faible", "effort_days": 0.25,
            "solution_astro": "Script embed dans le layout Astro", "icon": "💬"
        })

    # Analytics
    if has("google-analytics", "gtag", "ga4", "matomo", "plausible", "analytics"):
        source = "Google Analytics 4" if has("gtag", "ga4", "google-analytics") else "Matomo" if has("matomo") else "Analytics"
        features.append({
            "name": "Analytics", "detected": True, "source_plugin": source,
            "effort": "trivial", "effort_days": 0.1,
            "solution_astro": "Script dans <head> du layout Astro", "icon": "📊"
        })

    # Cookie consent
    if has("cookieyes", "cookie-notice", "gdpr", "tarteaucitron", "axeptio", "onetrust", "cookiebot"):
        source = "CookieYes" if has("cookieyes") else "Tarteaucitron" if has("tarteaucitron") else "GDPR plugin"
        features.append({
            "name": "Bandeau cookies / RGPD", "detected": True, "source_plugin": source,
            "effort": "faible", "effort_days": 0.5,
            "solution_astro": "Tarteaucitron.js ou CookieYes (script embed)", "icon": "🍪"
        })

    # Gallery / Portfolio
    if has("lightbox", "fancybox", "swiper", "slick", "glightbox", "photoswipe", "gallery"):
        features.append({
            "name": "Galerie / Portfolio", "detected": True, "source_plugin": "Lightbox / Slider",
            "effort": "faible", "effort_days": 1,
            "solution_astro": "Composant Astro + Swiper ou Photoswipe", "icon": "🖼️"
        })

    # Google Maps
    if has("maps.googleapis.com", "google.com/maps", "gmap", "google-maps"):
        features.append({
            "name": "Google Maps", "detected": True, "source_plugin": "Google Maps Embed",
            "effort": "trivial", "effort_days": 0.1,
            "solution_astro": "Iframe embed ou composant Maps", "icon": "🗺️"
        })

    # Social
    if has("facebook.com/plugins", "twitter.com/widgets", "addtoany", "share-buttons", "social-share"):
        features.append({
            "name": "Réseaux sociaux", "detected": True, "source_plugin": "Social widgets",
            "effort": "trivial", "effort_days": 0.25,
            "solution_astro": "Composant Astro avec liens sociaux", "icon": "📱"
        })

    return features


def _estimate_seo(crawl_data, deep_seo_data):
    """SEO migration requirements."""
    redirects_needed = len(crawl_data.get("redirect_chains", []))
    total_pages = crawl_data.get("total_pages", 0)
    missing_canonical = len(crawl_data.get("missing_canonical", []))

    schema_types = []
    for check in deep_seo_data.get("checks", []):
        if "schema" in check.get("name", "").lower() and check.get("passed"):
            schema_types.append(check.get("detail", "JSON-LD"))

    return {
        "redirects_needed": redirects_needed,
        "indexed_pages": total_pages,
        "missing_canonical": missing_canonical,
        "schema_types": schema_types or ["Aucun détecté"],
        "meta_tags_to_migrate": total_pages,
        "backlinks_warning": "Les backlinks existants doivent être préservés via redirections 301",
    }


def _estimate_infra(stack_data, lh_data):
    """Infrastructure analysis."""
    server = stack_data.get("server", "")
    cdn = stack_data.get("cdn", "")
    ssl_info = stack_data.get("ssl", {})

    # Detect hosting
    server_lower = (server or "").lower()
    if "nginx" in server_lower:
        current = f"Nginx ({server})"
    elif "apache" in server_lower:
        current = f"Apache ({server})"
    elif "litespeed" in server_lower:
        current = f"LiteSpeed ({server})"
    else:
        current = server or "Non détecté"

    if cdn:
        current += f" + CDN {cdn}"

    # Recommended based on complexity
    recommended = "Vercel (Edge, CDN global, déploiement Git automatique)"

    return {
        "current": current,
        "recommended": recommended,
        "cdn_current": cdn or "Aucun",
        "cdn_recommended": "Vercel Edge Network (inclus)",
        "ssl_current": ssl_info.get("issuer", "N/A") if ssl_info else "N/A",
        "ssl_recommended": "Let's Encrypt (auto via Vercel/Netlify)",
    }


def _performance_gain(lh_data):
    """Estimate performance gain with Astro."""
    cats = lh_data.get("categories", {}) if lh_data else {}
    raw = cats.get("performance", {}).get("score") if cats else None
    current = round(raw * 100) if isinstance(raw, (int, float)) else 0
    if current == 0:
        current = 50  # fallback

    # Astro typically scores 90-100 on static sites
    estimated = min(99, max(current + 25, 92))
    return {"current_score": current, "estimated_astro": estimated}


def _build_timeline(total_days, features):
    """Build project timeline phases."""
    phases = [
        {"phase": "Audit & Spécifications", "days": 1, "icon": "📋",
         "description": "Analyse détaillée, mapping des contenus, cahier des charges technique"},
    ]

    setup_days = max(1, round(total_days * 0.2, 1))
    phases.append({
        "phase": "Setup Astro + Design", "days": setup_days, "icon": "🎨",
        "description": "Installation Astro, configuration, intégration de la charte graphique"
    })

    content_days = max(1, round(total_days * 0.3, 1))
    phases.append({
        "phase": "Migration contenu", "days": content_days, "icon": "📄",
        "description": "Migration des pages, images, documents, SEO (meta, canonical, redirections)"
    })

    feat_days = sum(f["effort_days"] for f in features if f.get("effort") in ("moyen", "élevé", "critique"))
    if feat_days > 0:
        phases.append({
            "phase": "Fonctionnalités", "days": round(feat_days, 1), "icon": "⚙️",
            "description": "Intégration des fonctionnalités dynamiques (formulaires, recherche, etc.)"
        })

    test_days = max(0.5, round(total_days * 0.15, 1))
    phases.append({
        "phase": "Tests & Recette", "days": test_days, "icon": "✅",
        "description": "Tests cross-browser, vérification SEO, performance, accessibilité"
    })

    phases.append({
        "phase": "Mise en production", "days": 0.5, "icon": "🚀",
        "description": "Déploiement, configuration DNS, redirections 301, monitoring"
    })

    return phases


def analyze_migration(url, crawl_data, stack_data, deep_seo_data, lh_data):
    """Analyse complète de migration vers Astro.

    Returns a dict with effort score, features, timeline, etc.
    """
    crawl_data = crawl_data or {}
    stack_data = stack_data or {}
    deep_seo_data = deep_seo_data or {}
    lh_data = lh_data or {}

    # 1. Page classification
    page_stats, total_words, images, pdfs = _classify_pages(crawl_data)

    # 2. Feature detection
    features = _detect_features(crawl_data, stack_data)

    # 3. Content stats
    content_stats = {
        "images": len(images),
        "pdfs": len(pdfs),
        "words_total": total_words,
    }

    # 4. SEO migration
    seo_migration = _estimate_seo(crawl_data, deep_seo_data)

    # 5. Infrastructure
    infrastructure = _estimate_infra(stack_data, lh_data)

    # 6. Performance gain
    performance_gain = _performance_gain(lh_data)

    # 7. Calculate total effort
    # Base: 2 days for any migration (setup + deploy)
    base_days = 2
    # Content migration: ~0.1 day per 5 pages
    content_days = max(1, page_stats["total"] * 0.02)
    # Features
    feature_days = sum(f["effort_days"] for f in features)
    # SEO
    seo_days = 0.5 if seo_migration["redirects_needed"] > 0 else 0.25
    # Testing
    test_days = 1

    total_days = round(base_days + content_days + feature_days + seo_days + test_days, 1)

    # Categorize
    if total_days < 5:
        score_effort = "legere"
        score_label = "Migration légère"
    elif total_days < 15:
        score_effort = "standard"
        score_label = "Migration standard"
    elif total_days < 30:
        score_effort = "complexe"
        score_label = "Migration complexe"
    else:
        score_effort = "refonte"
        score_label = "Refonte majeure"

    tjm = 600
    budget = round(total_days * tjm)

    # Timeline
    timeline = _build_timeline(total_days, features)

    return {
        "score_effort": score_effort,
        "score_label": score_label,
        "total_days": total_days,
        "estimated_budget_eur": budget,
        "page_stats": page_stats,
        "features": features,
        "seo_migration": seo_migration,
        "content_stats": content_stats,
        "infrastructure": infrastructure,
        "performance_gain": performance_gain,
        "timeline": timeline,
    }
