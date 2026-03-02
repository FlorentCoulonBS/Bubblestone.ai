#!/usr/bin/env python3
"""DNS & Email Authentication audit module for BubbleStone Audit."""
import json
import sys
from urllib.parse import urlparse

import dns.resolver
import dns.rdatatype


def audit_dns_email(url):
    """Check SPF, DKIM, DMARC, MX, DNSSEC, CAA for a domain."""
    try:
        parsed = urlparse(url)
        domain = parsed.hostname or parsed.path
        domain = domain.replace('www.', '')

        score = 0
        checks = []
        result = {
            "score": 0,
            "spf": {"present": False, "record": ""},
            "dmarc": {"present": False, "record": "", "policy": ""},
            "dkim": {"found": False, "selector": ""},
            "mx": [],
            "dnssec": False,
            "caa": [],
            "checks": [],
        }

        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 10

        # --- SPF ---
        try:
            answers = resolver.resolve(domain, 'TXT')
            for rdata in answers:
                txt = rdata.to_text().strip('"')
                if txt.startswith('v=spf1'):
                    result["spf"] = {"present": True, "record": txt}
                    score += 25
                    checks.append({"name": "SPF record", "passed": True, "detail": txt[:80]})
                    break
            else:
                checks.append({"name": "SPF record", "passed": False, "detail": "No SPF record found"})
        except Exception:
            checks.append({"name": "SPF record", "passed": False, "detail": "DNS query failed"})

        # --- DMARC ---
        try:
            answers = resolver.resolve(f'_dmarc.{domain}', 'TXT')
            for rdata in answers:
                txt = rdata.to_text().strip('"')
                if 'v=DMARC1' in txt:
                    policy = ""
                    for part in txt.split(';'):
                        part = part.strip()
                        if part.startswith('p='):
                            policy = part[2:]
                    result["dmarc"] = {"present": True, "record": txt, "policy": policy}
                    score += 30
                    checks.append({"name": "DMARC record", "passed": True, "detail": f"Policy: {policy}"})
                    break
            else:
                checks.append({"name": "DMARC record", "passed": False, "detail": "No DMARC record found"})
        except Exception:
            checks.append({"name": "DMARC record", "passed": False, "detail": "No DMARC record found"})

        # --- DKIM ---
        selectors = ['google', 'default', 'selector1', 'selector2', 'k1', 'dkim', 'mail', 's1', 's2']
        dkim_found = False
        for sel in selectors:
            try:
                answers = resolver.resolve(f'{sel}._domainkey.{domain}', 'TXT')
                for rdata in answers:
                    txt = rdata.to_text().strip('"')
                    if 'v=DKIM1' in txt or 'p=' in txt:
                        result["dkim"] = {"found": True, "selector": sel}
                        score += 20
                        dkim_found = True
                        checks.append({"name": "DKIM record", "passed": True, "detail": f"Selector: {sel}"})
                        break
                if dkim_found:
                    break
            except Exception:
                continue
        if not dkim_found:
            checks.append({"name": "DKIM record", "passed": False, "detail": "No DKIM found (tried common selectors)"})

        # --- MX ---
        try:
            answers = resolver.resolve(domain, 'MX')
            mx_list = []
            for rdata in answers:
                mx_list.append({"priority": rdata.preference, "host": str(rdata.exchange).rstrip('.')})
            result["mx"] = mx_list
            if mx_list:
                score += 10
                checks.append({"name": "MX records", "passed": True, "detail": f"{len(mx_list)} MX record(s)"})
            else:
                checks.append({"name": "MX records", "passed": False, "detail": "No MX records"})
        except Exception:
            checks.append({"name": "MX records", "passed": False, "detail": "No MX records found"})

        # --- DNSSEC ---
        try:
            answers = resolver.resolve(domain, 'A')
            # Try to get DNSKEY
            try:
                resolver.resolve(domain, 'DNSKEY')
                result["dnssec"] = True
                score += 10
                checks.append({"name": "DNSSEC", "passed": True, "detail": "DNSKEY records present"})
            except Exception:
                checks.append({"name": "DNSSEC", "passed": False, "detail": "No DNSKEY records"})
        except Exception:
            checks.append({"name": "DNSSEC", "passed": False, "detail": "DNS resolution failed"})

        # --- CAA ---
        try:
            answers = resolver.resolve(domain, 'CAA')
            caa_list = []
            for rdata in answers:
                caa_list.append(str(rdata))
            result["caa"] = caa_list
            if caa_list:
                score += 5
                checks.append({"name": "CAA records", "passed": True, "detail": f"{len(caa_list)} CAA record(s)"})
            else:
                checks.append({"name": "CAA records", "passed": False, "detail": "No CAA records"})
        except Exception:
            checks.append({"name": "CAA records", "passed": False, "detail": "No CAA records found"})

        result["score"] = min(100, score)
        result["checks"] = checks
        return result

    except Exception as e:
        return {
            "score": 0,
            "spf": {"present": False, "record": ""},
            "dmarc": {"present": False, "record": "", "policy": ""},
            "dkim": {"found": False, "selector": ""},
            "mx": [],
            "dnssec": False,
            "caa": [],
            "checks": [{"name": "DNS Analysis", "passed": False, "detail": str(e)}],
        }


if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://example.com'
    result = audit_dns_email(url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
