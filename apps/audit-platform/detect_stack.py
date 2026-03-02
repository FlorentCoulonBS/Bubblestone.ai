#!/usr/bin/env python3
"""Détection de la stack technique d'un site web."""
import json
import re
import sys
import ssl
import socket
from datetime import datetime
from urllib.parse import urlparse
import requests

def detect(url):
    result = {
        "cms": None,
        "cms_version": None,
        "plugins": [],
        "server": None,
        "php_version": None,
        "cdn": None,
        "analytics": [],
        "ssl": {},
        "technologies": []
    }

    try:
        resp = requests.get(url, timeout=15, allow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BubbleStone-Audit/1.0)"
        })
    except Exception as e:
        result["error"] = str(e)
        return result

    headers = {k.lower(): v for k, v in resp.headers.items()}
    body = resp.text[:200000]

    # Server
    result["server"] = headers.get("server", None)

    # PHP version
    php = headers.get("x-powered-by", "")
    if "php" in php.lower():
        result["php_version"] = php

    # WordPress detection
    if any(x in body for x in ["wp-content", "wp-includes", "wp-json"]):
        result["cms"] = "WordPress"
        m = re.search(r'<meta name="generator" content="WordPress ([0-9.]+)"', body)
        if m:
            result["cms_version"] = m.group(1)
        # Plugins
        plugins = set(re.findall(r'/wp-content/plugins/([^/\'"]+)', body))
        result["plugins"] = sorted(plugins)[:20]
        # Theme
        themes = set(re.findall(r'/wp-content/themes/([^/\'"]+)', body))
        if themes:
            result["technologies"].append(f"Thème WP: {', '.join(sorted(themes)[:3])}")

    # Drupal
    elif "Drupal" in body or "drupal.js" in body:
        result["cms"] = "Drupal"
        m = re.search(r'Drupal ([0-9.]+)', body)
        if m:
            result["cms_version"] = m.group(1)

    # Joomla
    elif "/media/jui/" in body or "Joomla" in body:
        result["cms"] = "Joomla"

    # Frameworks JS
    for fw, pattern in [
        ("React", r'react[.-]'),
        ("Vue.js", r'vue[.-]|__vue'),
        ("Angular", r'ng-version|angular'),
        ("Next.js", r'_next/'),
        ("Nuxt", r'__nuxt|nuxt'),
        ("Astro", r'astro'),
        ("Svelte", r'svelte'),
    ]:
        if re.search(pattern, body, re.I):
            result["technologies"].append(fw)

    # jQuery
    if "jquery" in body.lower():
        m = re.search(r'jquery[.-]?(\d+\.\d+\.\d+)', body, re.I)
        result["technologies"].append(f"jQuery {m.group(1)}" if m else "jQuery")

    # CDN detection
    cdn_checks = {
        "Cloudflare": ["cf-ray", "cf-cache-status"],
        "Fastly": ["x-fastly-request-id"],
        "AWS CloudFront": ["x-amz-cf-id"],
        "Akamai": ["x-akamai-transformed"],
        "KeyCDN": ["x-edge-location"],
        "Sucuri": ["x-sucuri-id"],
    }
    for cdn_name, cdn_headers in cdn_checks.items():
        if any(h in headers for h in cdn_headers):
            result["cdn"] = cdn_name
            break

    # Analytics
    if re.search(r'gtag|GA4|G-[A-Z0-9]+', body):
        ga_ids = re.findall(r'G-[A-Z0-9]+', body)
        result["analytics"].append({"type": "GA4", "ids": list(set(ga_ids))[:5]})
    if re.search(r'UA-\d+-\d+', body):
        ua_ids = re.findall(r'UA-\d+-\d+', body)
        result["analytics"].append({"type": "Universal Analytics", "ids": list(set(ua_ids))[:5]})
    if "matomo" in body.lower() or "piwik" in body.lower():
        result["analytics"].append({"type": "Matomo"})
    if "plausible" in body.lower():
        result["analytics"].append({"type": "Plausible"})
    if "_hj" in body or "hotjar" in body.lower():
        result["analytics"].append({"type": "Hotjar"})

    # SSL info
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
            s.settimeout(10)
            s.connect((hostname, 443))
            cert = s.getpeercert()
            result["ssl"] = {
                "issuer": dict(x[0] for x in cert.get("issuer", [])).get("organizationName", "Unknown"),
                "expires": cert.get("notAfter", ""),
                "subject": dict(x[0] for x in cert.get("subject", [])).get("commonName", ""),
                "version": s.version()
            }
    except Exception:
        result["ssl"] = {"error": "Impossible de vérifier le SSL"}

    return result

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    print(json.dumps(detect(url), indent=2, ensure_ascii=False))
