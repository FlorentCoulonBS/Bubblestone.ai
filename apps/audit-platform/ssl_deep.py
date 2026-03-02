#!/usr/bin/env python3
"""Deep SSL/TLS Analysis module for BubbleStone Audit."""
import json
import socket
import ssl
import sys
from datetime import datetime
from urllib.parse import urlparse


def analyze_ssl(url):
    """Analyze SSL/TLS configuration of a website."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or parsed.path
        port = parsed.port or 443

        checks = []
        issues = []
        tls_versions_supported = []
        score = 100
        certificate_info = {}
        ciphers_used = []

        # --- Test TLS versions ---
        tls_map = {
            "TLS 1.0": ssl.TLSVersion.TLSv1 if hasattr(ssl.TLSVersion, 'TLSv1') else None,
            "TLS 1.1": ssl.TLSVersion.TLSv1_1 if hasattr(ssl.TLSVersion, 'TLSv1_1') else None,
            "TLS 1.2": ssl.TLSVersion.TLSv1_2,
            "TLS 1.3": ssl.TLSVersion.TLSv1_3 if hasattr(ssl.TLSVersion, 'TLSv1_3') else None,
        }

        for ver_name, ver_const in tls_map.items():
            if ver_const is None:
                continue
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.minimum_version = ver_const
                ctx.maximum_version = ver_const
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with socket.create_connection((hostname, port), timeout=5) as sock:
                    with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                        tls_versions_supported.append(ver_name)
            except Exception:
                pass

        # Score TLS versions
        has_old = any(v in tls_versions_supported for v in ["TLS 1.0", "TLS 1.1"])
        has_12 = "TLS 1.2" in tls_versions_supported
        has_13 = "TLS 1.3" in tls_versions_supported

        if has_old:
            score -= 25
            issues.append("TLS 1.0/1.1 still accepted (insecure)")
            checks.append({"name": "Legacy TLS disabled", "passed": False, "detail": "TLS 1.0/1.1 still accepted"})
        else:
            checks.append({"name": "Legacy TLS disabled", "passed": True, "detail": "TLS 1.0/1.1 not accepted"})

        if has_13:
            score += 5  # bonus
            checks.append({"name": "TLS 1.3 supported", "passed": True, "detail": "Modern TLS 1.3 available"})
        else:
            score -= 5
            checks.append({"name": "TLS 1.3 supported", "passed": False, "detail": "TLS 1.3 not available"})

        if not has_12 and not has_13:
            score -= 20
            issues.append("Neither TLS 1.2 nor 1.3 supported")

        # --- Certificate info ---
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    cipher_info = ssock.cipher()
                    if cipher_info:
                        ciphers_used.append({"name": cipher_info[0], "version": cipher_info[1], "bits": cipher_info[2]})

                    # Expiry
                    not_after = cert.get('notAfter', '')
                    not_before = cert.get('notBefore', '')
                    subject = dict(x[0] for x in cert.get('subject', []))
                    issuer = dict(x[0] for x in cert.get('issuer', []))
                    san = [v for _, v in cert.get('subjectAltName', [])]

                    expiry_date = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
                    days_remaining = (expiry_date - datetime.utcnow()).days

                    certificate_info = {
                        "subject": subject.get('commonName', ''),
                        "issuer": issuer.get('organizationName', issuer.get('commonName', '')),
                        "not_before": not_before,
                        "not_after": not_after,
                        "days_remaining": days_remaining,
                        "san": san[:10],
                    }

                    if days_remaining < 7:
                        score -= 30
                        issues.append(f"Certificate expires in {days_remaining} days!")
                        checks.append({"name": "Certificate expiry", "passed": False, "detail": f"Expires in {days_remaining} days"})
                    elif days_remaining < 30:
                        score -= 15
                        issues.append(f"Certificate expires soon ({days_remaining} days)")
                        checks.append({"name": "Certificate expiry", "passed": False, "detail": f"Expires in {days_remaining} days"})
                    else:
                        checks.append({"name": "Certificate expiry", "passed": True, "detail": f"{days_remaining} days remaining"})

                    # Cipher strength
                    if cipher_info and cipher_info[2] >= 256:
                        checks.append({"name": "Strong cipher", "passed": True, "detail": f"{cipher_info[0]} ({cipher_info[2]} bits)"})
                    elif cipher_info and cipher_info[2] >= 128:
                        checks.append({"name": "Strong cipher", "passed": True, "detail": f"{cipher_info[0]} ({cipher_info[2]} bits)"})
                    elif cipher_info:
                        score -= 15
                        checks.append({"name": "Strong cipher", "passed": False, "detail": f"Weak: {cipher_info[0]} ({cipher_info[2]} bits)"})

                    # Chain validation passed (if we got here with default context)
                    checks.append({"name": "Certificate chain valid", "passed": True, "detail": f"Issued by {certificate_info['issuer']}"})

        except ssl.SSLCertVerificationError as e:
            score -= 30
            issues.append(f"Certificate validation failed: {e}")
            checks.append({"name": "Certificate chain valid", "passed": False, "detail": str(e)})
        except Exception as e:
            issues.append(f"Certificate check error: {e}")

        # --- HSTS check ---
        try:
            import urllib.request
            req = urllib.request.Request(url, method='HEAD')
            req.add_header('User-Agent', 'BubbleStone-Audit/1.0')
            resp = urllib.request.urlopen(req, timeout=10)
            hsts = resp.headers.get('Strict-Transport-Security', '')
            if hsts:
                checks.append({"name": "HSTS enabled", "passed": True, "detail": hsts})
                if 'preload' in hsts.lower():
                    checks.append({"name": "HSTS preload", "passed": True, "detail": "Preload directive present"})
                else:
                    score -= 5
                    checks.append({"name": "HSTS preload", "passed": False, "detail": "No preload directive"})
            else:
                score -= 15
                issues.append("No HSTS header")
                checks.append({"name": "HSTS enabled", "passed": False, "detail": "Header absent"})
                checks.append({"name": "HSTS preload", "passed": False, "detail": "No HSTS at all"})
        except Exception as e:
            checks.append({"name": "HSTS enabled", "passed": False, "detail": f"Error: {e}"})

        score = max(0, min(100, score))

        return {
            "score": score,
            "tls_versions": tls_versions_supported,
            "certificate": certificate_info,
            "ciphers": ciphers_used,
            "issues": issues,
            "checks": checks,
        }

    except Exception as e:
        return {
            "score": 0,
            "tls_versions": [],
            "certificate": {},
            "ciphers": [],
            "issues": [f"Analysis failed: {e}"],
            "checks": [{"name": "SSL Analysis", "passed": False, "detail": str(e)}],
        }


if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://example.com'
    result = analyze_ssl(url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
