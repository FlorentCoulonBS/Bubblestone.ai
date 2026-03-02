#!/usr/bin/env python3
"""Analyse des headers de sécurité HTTP."""
import json
import sys
import requests

HEADERS_CHECK = {
    "Strict-Transport-Security": {
        "weight": 20,
        "description": "HSTS — Force HTTPS",
        "recommended": "max-age=31536000; includeSubDomains; preload"
    },
    "Content-Security-Policy": {
        "weight": 20,
        "description": "CSP — Protection XSS et injection",
        "recommended": "default-src 'self'; script-src 'self'"
    },
    "X-Frame-Options": {
        "weight": 10,
        "description": "Protection clickjacking",
        "recommended": "DENY ou SAMEORIGIN"
    },
    "X-Content-Type-Options": {
        "weight": 10,
        "description": "Empêche le MIME sniffing",
        "recommended": "nosniff"
    },
    "Referrer-Policy": {
        "weight": 10,
        "description": "Contrôle les infos envoyées via Referer",
        "recommended": "strict-origin-when-cross-origin"
    },
    "Permissions-Policy": {
        "weight": 15,
        "description": "Contrôle l'accès aux APIs navigateur",
        "recommended": "camera=(), microphone=(), geolocation=()"
    },
    "X-XSS-Protection": {
        "weight": 5,
        "description": "Protection XSS legacy (navigateurs anciens)",
        "recommended": "1; mode=block"
    },
    "X-Permitted-Cross-Domain-Policies": {
        "weight": 5,
        "description": "Politique cross-domain Adobe/Flash",
        "recommended": "none"
    },
    "Cross-Origin-Opener-Policy": {
        "weight": 5,
        "description": "Isolation cross-origin",
        "recommended": "same-origin"
    }
}

def check(url):
    try:
        resp = requests.get(url, timeout=15, allow_redirects=True, headers={
            "User-Agent": "BubbleStone-Audit/1.0"
        })
    except Exception as e:
        return {"score": 0, "error": str(e), "headers": {}}

    resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    results = {}
    score = 0
    max_score = sum(h["weight"] for h in HEADERS_CHECK.values())

    for header, info in HEADERS_CHECK.items():
        key = header.lower()
        present = key in resp_headers
        value = resp_headers.get(key, None)
        if present:
            score += info["weight"]
        results[header] = {
            "present": present,
            "value": value,
            "description": info["description"],
            "recommended": info["recommended"],
            "weight": info["weight"]
        }

    final_score = round(score / max_score * 100)
    return {
        "score": final_score,
        "max_score": 100,
        "headers": results,
        "server": resp_headers.get("server", None),
        "status_code": resp.status_code
    }

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    print(json.dumps(check(url), indent=2, ensure_ascii=False))
