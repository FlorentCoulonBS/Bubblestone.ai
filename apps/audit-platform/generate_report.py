#!/usr/bin/env python3
"""Génération du rapport d'audit HTML → PDF."""
import json
import os
import subprocess
import sys
from datetime import datetime
from jinja2 import Template

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def score_color(score):
    if score is None:
        return "#9CA3AF"
    if score >= 80:
        return "#16A34A"
    if score >= 50:
        return "#F59E0B"
    return "#DC2626"

def score_label(score):
    if score is None:
        return "N/A"
    if score >= 80:
        return "Bon"
    if score >= 50:
        return "Moyen"
    return "Faible"

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
        "FCP": audit_val("first-contentful-paint"),
        "LCP": audit_val("largest-contentful-paint"),
        "TBT": audit_val("total-blocking-time"),
        "CLS": audit_val("cumulative-layout-shift"),
        "SI": audit_val("speed-index"),
        "TTI": audit_val("interactive"),
    }

    # Opportunities
    opportunities = []
    for key, audit in audits.items():
        if audit.get("details", {}).get("type") == "opportunity":
            savings = audit.get("details", {}).get("overallSavingsMs", 0)
            if savings > 0:
                opportunities.append({
                    "title": audit.get("title", key),
                    "savings_ms": round(savings),
                    "description": audit.get("description", "")[:200]
                })
    opportunities.sort(key=lambda x: x["savings_ms"], reverse=True)

    # SEO audits
    seo_checks = {}
    seo_keys = ["document-title", "meta-description", "hreflang", "canonical",
                 "robots-txt", "structured-data", "http-status-code"]
    for key in seo_keys:
        if key in audits:
            a = audits[key]
            seo_checks[a.get("title", key)] = {
                "score": a.get("score", 0),
                "value": a.get("displayValue", ""),
            }

    # A11y issues
    a11y_issues = []
    for key, audit in audits.items():
        if audit.get("score") == 0 and "accessibility" in str(cats.get("accessibility", {}).get("auditRefs", "")):
            # Check if this audit is in the accessibility category
            pass
    # Simpler: get all failing audits in a11y
    a11y_refs = [r["id"] for r in cats.get("accessibility", {}).get("auditRefs", []) if r.get("weight", 0) > 0]
    for ref in a11y_refs:
        if ref in audits and audits[ref].get("score", 1) == 0:
            a11y_issues.append({
                "title": audits[ref].get("title", ref),
                "description": audits[ref].get("description", "")[:200],
                "impact": audits[ref].get("details", {}).get("items", [{}])[0].get("node", {}).get("explanation", "") if audits[ref].get("details", {}).get("items") else ""
            })

    return scores, cwv, opportunities[:10], seo_checks, a11y_issues

def extract_zap(data):
    alerts = []
    site_data = data.get("site", [])
    if isinstance(site_data, list):
        for site in site_data:
            for alert in site.get("alerts", []):
                alerts.append({
                    "name": alert.get("name", alert.get("alert", "Unknown")),
                    "risk": alert.get("riskdesc", alert.get("risk", "Info")),
                    "confidence": alert.get("confidence", ""),
                    "description": alert.get("desc", "")[:200],
                    "solution": alert.get("solution", "")[:200],
                    "count": len(alert.get("instances", []))
                })
    elif isinstance(site_data, dict):
        for alert in site_data.get("alerts", []):
            alerts.append({
                "name": alert.get("name", "Unknown"),
                "risk": alert.get("riskdesc", alert.get("risk", "Info")),
                "description": alert.get("desc", "")[:200],
                "solution": alert.get("solution", "")[:200],
                "count": len(alert.get("instances", []))
            })
    # Also handle flat format
    if not alerts and isinstance(data, dict):
        for alert in data.get("alerts", []):
            alerts.append({
                "name": alert.get("name", alert.get("alert", "Unknown")),
                "risk": alert.get("riskdesc", alert.get("risk", "Info")),
                "description": alert.get("desc", alert.get("description", ""))[:200],
                "solution": alert.get("solution", "")[:200],
                "count": len(alert.get("instances", []))
            })

    risk_order = {"High": 0, "Medium": 1, "Low": 2, "Informational": 3, "Info": 3}
    alerts.sort(key=lambda a: risk_order.get(a["risk"].split(" ")[0] if a["risk"] else "Info", 4))
    return alerts

def generate_recommendations(lh_scores, headers_data, zap_alerts, opportunities):
    recs = []
    hs = headers_data.get("score", 100)
    if hs < 50:
        recs.append({"priority": "Haute", "category": "Sécurité", "text": "Configurer les headers de sécurité HTTP manquants (CSP, HSTS, X-Frame-Options)"})
    if lh_scores.get("performance", 100) < 50:
        recs.append({"priority": "Haute", "category": "Performance", "text": "Améliorer les performances — le site est lent (score < 50)"})
    if lh_scores.get("accessibility", 100) < 80:
        recs.append({"priority": "Haute", "category": "Accessibilité", "text": "Corriger les problèmes d'accessibilité détectés par Lighthouse"})
    if lh_scores.get("seo", 100) < 80:
        recs.append({"priority": "Moyenne", "category": "SEO", "text": "Optimiser le SEO on-page (meta tags, structure, etc.)"})

    for alert in zap_alerts[:3]:
        if "High" in str(alert.get("risk", "")):
            recs.append({"priority": "Haute", "category": "Sécurité", "text": f"Corriger : {alert['name']}"})
        elif "Medium" in str(alert.get("risk", "")):
            recs.append({"priority": "Moyenne", "category": "Sécurité", "text": f"Corriger : {alert['name']}"})

    for opp in opportunities[:3]:
        recs.append({"priority": "Moyenne", "category": "Performance", "text": f"{opp['title']} (gain potentiel : {opp['savings_ms']}ms)"})

    # Headers specifics
    for header, info in headers_data.get("headers", {}).items():
        if not info.get("present") and info.get("weight", 0) >= 15:
            recs.append({"priority": "Moyenne", "category": "Sécurité", "text": f"Ajouter le header {header}"})

    return recs[:10]

def generate_summary(url, scores, headers_score, zap_count):
    parts = []
    avg = sum(scores.values()) / len(scores) if scores else 0
    if avg >= 80:
        parts.append(f"Le site {url} présente un bon niveau de qualité global.")
    elif avg >= 50:
        parts.append(f"Le site {url} présente un niveau de qualité correct avec des axes d'amélioration.")
    else:
        parts.append(f"Le site {url} nécessite des améliorations significatives sur plusieurs axes.")

    if scores.get("performance", 0) < 50:
        parts.append("Les performances sont insuffisantes et impactent l'expérience utilisateur.")
    if headers_score < 50:
        parts.append("La sécurité des headers HTTP est faible et doit être renforcée en priorité.")
    if zap_count > 5:
        parts.append(f"{zap_count} alertes de sécurité ont été détectées par le scan OWASP ZAP.")
    if scores.get("accessibility", 0) >= 80:
        parts.append("L'accessibilité est à un bon niveau.")

    return " ".join(parts[:4])

def main():
    output_dir = sys.argv[1]
    url = sys.argv[2]
    domain = sys.argv[3]
    timestamp = sys.argv[4]

    lh = load_json(os.path.join(output_dir, "lighthouse.json"))
    zap = load_json(os.path.join(output_dir, "zap.json"))
    headers = load_json(os.path.join(output_dir, "headers.json"))
    stack = load_json(os.path.join(output_dir, "stack.json"))

    lh_scores, cwv, opportunities, seo_checks, a11y_issues = extract_lighthouse(lh)
    zap_alerts = extract_zap(zap)

    # Security score: combine headers + ZAP
    headers_score = headers.get("score", 0)
    zap_penalty = min(len(zap_alerts) * 5, 40)
    security_score = max(0, headers_score - zap_penalty)

    all_scores = {
        "performance": lh_scores.get("performance", 0),
        "seo": lh_scores.get("seo", 0),
        "security": security_score,
        "accessibility": lh_scores.get("accessibility", 0),
    }

    recommendations = generate_recommendations(lh_scores, headers, zap_alerts, opportunities)
    summary = generate_summary(url, all_scores, headers_score, len(zap_alerts))

    date_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    # Load template
    with open("/app/template.html") as f:
        template = Template(f.read())

    html = template.render(
        url=url,
        domain=domain,
        date=date_str,
        timestamp=timestamp,
        scores=all_scores,
        score_color=score_color,
        score_label=score_label,
        summary=summary,
        stack=stack,
        cwv=cwv,
        opportunities=opportunities,
        seo_checks=seo_checks,
        headers=headers,
        zap_alerts=zap_alerts,
        a11y_issues=a11y_issues,
        recommendations=recommendations,
    )

    html_path = os.path.join(output_dir, f"rapport_{domain}_{timestamp}.html")
    pdf_path = os.path.join(output_dir, f"rapport_{domain}_{timestamp}.pdf")

    with open(html_path, "w") as f:
        f.write(html)

    # HTML → PDF via wkhtmltopdf
    subprocess.run([
        "wkhtmltopdf",
        "--quiet",
        "--enable-local-file-access",
        "--page-size", "A4",
        "--margin-top", "15mm",
        "--margin-bottom", "15mm",
        "--margin-left", "12mm",
        "--margin-right", "12mm",
        "--encoding", "UTF-8",
        html_path,
        pdf_path
    ], check=False)

    print(f"✅ Rapport généré : {pdf_path}")

if __name__ == "__main__":
    main()
