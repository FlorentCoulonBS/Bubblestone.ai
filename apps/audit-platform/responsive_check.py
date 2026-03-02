#!/usr/bin/env python3
"""BubbleStone.ai — Responsive Design Checker. Uses existing Lighthouse data + HTML parsing."""
import re
import requests

USER_AGENT = 'BubbleStone-Audit/1.0'


def check_responsive(url, lh_data=None):
    """Check responsive design, return a dict with score and details."""
    result = {
        "score": 0,
        "viewport_ok": False,
        "media_queries": False,
        "responsive_images": False,
        "tap_targets_ok": True,
        "no_fixed_width": True,
        "tables_count": 0,
        "font_size_ok": True,
        "issues": [],
    }

    # --- Parse HTML ---
    html = ""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        html = r.text
    except Exception:
        result["issues"].append({"name": "Erreur de connexion", "detail": "Impossible de charger la page", "severity": "haute"})
        return result

    html_lower = html.lower()

    # 1. Viewport meta
    viewport_match = re.search(r'<meta[^>]*name=["\']viewport["\'][^>]*content=["\']([^"\']+)["\']', html_lower)
    if not viewport_match:
        viewport_match = re.search(r'<meta[^>]*content=["\']([^"\']*width=device-width[^"\']*)["\'][^>]*name=["\']viewport["\']', html_lower)
    if viewport_match:
        content = viewport_match.group(1)
        result["viewport_ok"] = "width=device-width" in content
    if not result["viewport_ok"]:
        result["issues"].append({"name": "Viewport manquant ou incorrect", "detail": "La balise <meta name=\"viewport\" content=\"width=device-width\"> est absente ou mal configurée", "severity": "haute"})

    # 2. Media queries in <style> tags and inline styles
    style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE)
    media_query_count = 0
    for block in style_blocks:
        media_query_count += len(re.findall(r'@media', block, re.IGNORECASE))
    # Also check linked CSS (just count, don't fetch)
    linked_css = re.findall(r'<link[^>]*rel=["\']stylesheet["\'][^>]*>', html_lower)
    result["media_queries"] = media_query_count > 0 or len(linked_css) > 0
    if not result["media_queries"]:
        result["issues"].append({"name": "Pas de media queries CSS", "detail": "Aucune media query détectée dans les styles inline", "severity": "haute"})

    # 3. Responsive images (srcset, <picture>, sizes)
    total_imgs = len(re.findall(r'<img\b', html_lower))
    srcset_count = len(re.findall(r'srcset\s*=', html_lower))
    picture_count = len(re.findall(r'<picture', html_lower))
    sizes_count = len(re.findall(r'\bsizes\s*=', html_lower))
    responsive_img_count = srcset_count + picture_count
    result["responsive_images"] = responsive_img_count > 0 and (responsive_img_count >= total_imgs * 0.3 if total_imgs > 0 else True)
    if total_imgs > 0 and not result["responsive_images"]:
        result["issues"].append({
            "name": "Images non responsive",
            "detail": f"{total_imgs - srcset_count}/{total_imgs} images sans srcset",
            "severity": "haute"
        })

    # 4. Fixed width detection on body, main, container
    fixed_width = False
    for tag in ['body', 'main', '.container', '#container', '.wrapper', '#wrapper', '.content', '#content']:
        # Check inline styles
        pattern = rf'(?:class|id)=["\'][^"\']*{re.escape(tag.lstrip(".#"))}[^"\']*["\'][^>]*style=["\'][^"\']*width\s*:\s*\d{{3,}}px'
        if re.search(pattern, html_lower):
            fixed_width = True
            break
    # Check in style blocks
    for block in style_blocks:
        for selector in ['body', 'main', '.container', '#container', '.wrapper', '#wrapper']:
            pattern = rf'{re.escape(selector)}\s*\{{[^}}]*width\s*:\s*\d{{3,}}px'
            if re.search(pattern, block, re.IGNORECASE):
                fixed_width = True
                break
    result["no_fixed_width"] = not fixed_width
    if fixed_width:
        result["issues"].append({"name": "Largeur fixe détectée", "detail": "Un conteneur principal utilise une largeur fixe en pixels", "severity": "moyenne"})

    # 5. HTML tables
    tables = re.findall(r'<table\b', html_lower)
    result["tables_count"] = len(tables)
    if len(tables) > 0:
        result["issues"].append({"name": f"{len(tables)} tableau(x) HTML", "detail": "Les tableaux HTML peuvent casser sur mobile", "severity": "moyenne"})

    # 6. Small font sizes in style blocks
    small_fonts = False
    for block in style_blocks:
        sizes = re.findall(r'font-size\s*:\s*(\d+(?:\.\d+)?)\s*px', block)
        for s in sizes:
            if float(s) < 12:
                small_fonts = True
                break
    result["font_size_ok"] = not small_fonts
    if small_fonts:
        result["issues"].append({"name": "Polices trop petites", "detail": "Des font-size < 12px détectées", "severity": "moyenne"})

    # --- Extract from Lighthouse data ---
    if lh_data:
        audits = lh_data.get("audits", {})

        # Tap targets
        tap = audits.get("tap-targets", {})
        if tap.get("score") is not None and tap["score"] < 1:
            result["tap_targets_ok"] = False
            detail = tap.get("displayValue", "Certains éléments sont trop petits")
            result["issues"].append({"name": "Cibles tactiles trop petites", "detail": detail, "severity": "haute"})

        # Font size
        fs = audits.get("font-size", {})
        if fs.get("score") is not None and fs["score"] < 1:
            result["font_size_ok"] = False
            detail = fs.get("displayValue", "Texte trop petit pour mobile")
            # Don't duplicate if already found via CSS
            if not small_fonts:
                result["issues"].append({"name": "Texte trop petit (Lighthouse)", "detail": detail, "severity": "moyenne"})

        # Content width (overflow)
        cw = audits.get("content-width", {})
        if cw.get("score") is not None and cw["score"] < 1:
            result["issues"].append({"name": "Débordement horizontal", "detail": "Le contenu déborde de la largeur du viewport", "severity": "haute"})

        # Viewport from Lighthouse
        vp = audits.get("viewport", {})
        if vp.get("score") is not None and vp["score"] < 1:
            result["viewport_ok"] = False

    # --- Calculate score ---
    score = 0
    weights = {
        "viewport_ok": 20,
        "media_queries": 15,
        "responsive_images": 15,
        "tap_targets_ok": 15,
        "no_fixed_width": 10,
        "font_size_ok": 10,
    }
    # Tables: deduct up to 5 points
    table_penalty = min(result["tables_count"] * 2.5, 5)
    # No high-severity issues bonus
    high_issues = [i for i in result["issues"] if i["severity"] == "haute"]

    for key, weight in weights.items():
        if result.get(key):
            score += weight

    # Remaining 15 points: no issues bonus
    no_issue_bonus = max(0, 15 - len(high_issues) * 5)
    score += no_issue_bonus
    score -= table_penalty
    score = max(0, min(100, round(score)))
    result["score"] = score

    return result


if __name__ == '__main__':
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: responsive_check.py <url> [lighthouse.json]")
        sys.exit(1)
    url = sys.argv[1]
    lh = None
    if len(sys.argv) > 2:
        with open(sys.argv[2]) as f:
            lh = json.load(f)
    print(json.dumps(check_responsive(url, lh), indent=2, ensure_ascii=False))
