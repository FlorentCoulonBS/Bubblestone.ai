#!/usr/bin/env python3
"""WordPress Vulnerability Scanner for BubbleStone Audit."""
import json
import re
import sys
from urllib.parse import urlparse

import requests


# PHP EOL dates (major.minor → EOL date)
PHP_EOL = {
    "5.6": True, "7.0": True, "7.1": True, "7.2": True, "7.3": True, "7.4": True,
    "8.0": True, "8.1": True,  # EOL Nov 2025
    "8.2": False, "8.3": False, "8.4": False,
}

# Known WordPress vulnerabilities by version range
WP_KNOWN_VULNS = {
    "6.0": ["CVE-2022-43504 (stored XSS)"],
    "6.1": ["CVE-2023-22622 (unauthenticated blind SSRF)"],
    "6.2": ["CVE-2023-38000 (stored XSS in block themes)"],
    "6.3": ["CVE-2023-39999 (comment disclosure)"],
    "6.4": ["CVE-2024-31210 (remote code execution via plugin upload)"],
}


def scan_wordpress(url, stack_data=None):
    """Scan a WordPress site for common vulnerabilities."""
    try:
        stack_data = stack_data or {}
        headers = {"User-Agent": "BubbleStone-Audit/1.0"}
        timeout = 10
        base = url.rstrip('/')

        checks = []
        score = 100
        exposed_endpoints = []
        directory_listing = []
        wp_version = stack_data.get('wordpress_version', '')
        php_version = stack_data.get('php_version', '')
        user_enumeration = False

        # --- Detect WP version from readme.html ---
        try:
            r = requests.get(f"{base}/readme.html", headers=headers, timeout=timeout)
            if r.status_code == 200 and 'wordpress' in r.text.lower():
                exposed_endpoints.append("readme.html")
                score -= 5
                checks.append({"name": "readme.html exposed", "passed": False, "detail": "Version info potentially leaked"})
                # Try to extract version
                m = re.search(r'Version\s+([\d.]+)', r.text)
                if m and not wp_version:
                    wp_version = m.group(1)
            else:
                checks.append({"name": "readme.html exposed", "passed": True, "detail": "Not accessible"})
        except Exception:
            checks.append({"name": "readme.html exposed", "passed": True, "detail": "Not accessible"})

        # --- Check exposed endpoints ---
        endpoint_checks = {
            "wp-login.php": "Login page exposed",
            "xmlrpc.php": "XML-RPC enabled (brute force / DDoS risk)",
        }
        for ep, desc in endpoint_checks.items():
            try:
                r = requests.get(f"{base}/{ep}", headers=headers, timeout=timeout, allow_redirects=False)
                if r.status_code == 200 or (r.status_code == 405 and ep == 'xmlrpc.php'):
                    exposed_endpoints.append(ep)
                    score -= 5
                    checks.append({"name": f"{ep} accessible", "passed": False, "detail": desc})
                else:
                    checks.append({"name": f"{ep} accessible", "passed": True, "detail": "Not exposed"})
            except Exception:
                checks.append({"name": f"{ep} accessible", "passed": True, "detail": "Not accessible"})

        # --- User enumeration via REST API ---
        try:
            r = requests.get(f"{base}/wp-json/wp/v2/users", headers=headers, timeout=timeout)
            if r.status_code == 200:
                try:
                    users = r.json()
                    if isinstance(users, list) and len(users) > 0:
                        user_enumeration = True
                        exposed_endpoints.append("wp-json/wp/v2/users")
                        score -= 15
                        names = [u.get('slug', '') for u in users[:3]]
                        checks.append({"name": "User enumeration", "passed": False, "detail": f"Users exposed: {', '.join(names)}"})
                    else:
                        checks.append({"name": "User enumeration", "passed": True, "detail": "API returns empty"})
                except Exception:
                    checks.append({"name": "User enumeration", "passed": True, "detail": "API not returning user data"})
            else:
                checks.append({"name": "User enumeration", "passed": True, "detail": "REST API users endpoint protected"})
        except Exception:
            checks.append({"name": "User enumeration", "passed": True, "detail": "Not accessible"})

        # --- Directory listing ---
        dirs_to_check = ["wp-content/plugins/", "wp-content/uploads/", "wp-content/themes/"]
        for d in dirs_to_check:
            try:
                r = requests.get(f"{base}/{d}", headers=headers, timeout=timeout)
                if r.status_code == 200 and ('index of' in r.text.lower() or '<li><a href=' in r.text.lower()):
                    directory_listing.append(d)
                    score -= 10
                    checks.append({"name": f"Directory listing: {d}", "passed": False, "detail": "Directory listing enabled"})
                else:
                    checks.append({"name": f"Directory listing: {d}", "passed": True, "detail": "Protected"})
            except Exception:
                checks.append({"name": f"Directory listing: {d}", "passed": True, "detail": "Not accessible"})

        # --- PHP EOL check ---
        php_eol = False
        if php_version:
            # Strip "PHP/" prefix if present (e.g. "PHP/7.4" → "7.4")
            php_clean = re.sub(r'^PHP/?', '', php_version).strip()
            major_minor = '.'.join(php_clean.split('.')[:2])
            php_eol = PHP_EOL.get(major_minor, False)
            if php_eol:
                score -= 10
                checks.append({"name": "PHP version EOL", "passed": False, "detail": f"PHP {php_clean} is end-of-life (security patches stopped)"})
            else:
                checks.append({"name": "PHP version EOL", "passed": True, "detail": f"PHP {php_clean} is supported"})

        # --- WP version CVE check ---
        if wp_version:
            major_minor = '.'.join(wp_version.split('.')[:2])
            known = WP_KNOWN_VULNS.get(major_minor, [])
            if known:
                score -= 10
                checks.append({"name": "Known CVEs", "passed": False, "detail": f"WP {wp_version}: {'; '.join(known[:2])}"})
            else:
                checks.append({"name": "Known CVEs", "passed": True, "detail": f"WP {wp_version}: no known CVEs in database"})

        # --- Debug mode check ---
        try:
            r = requests.get(base, headers=headers, timeout=timeout)
            debug_indicators = ['WP_DEBUG', 'Notice:', 'Warning:', 'Fatal error:', 'wp-content/debug.log']
            found_debug = [ind for ind in debug_indicators if ind in r.text]
            if found_debug:
                score -= 10
                checks.append({"name": "Debug mode", "passed": False, "detail": f"Debug indicators: {', '.join(found_debug)}"})
            else:
                checks.append({"name": "Debug mode", "passed": True, "detail": "No debug indicators found"})
        except Exception:
            checks.append({"name": "Debug mode", "passed": True, "detail": "Could not check"})

        score = max(0, min(100, score))

        return {
            "score": score,
            "wordpress_version": wp_version,
            "php_version": php_version,
            "php_eol": php_eol,
            "exposed_endpoints": exposed_endpoints,
            "user_enumeration": user_enumeration,
            "directory_listing": directory_listing,
            "checks": checks,
        }

    except Exception as e:
        return {
            "score": 50,
            "wordpress_version": "",
            "php_version": "",
            "php_eol": False,
            "exposed_endpoints": [],
            "user_enumeration": False,
            "directory_listing": [],
            "checks": [{"name": "WordPress scan", "passed": False, "detail": str(e)}],
        }


if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://example.com'
    stack = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    result = scan_wordpress(url, stack)
    print(json.dumps(result, indent=2, ensure_ascii=False))
