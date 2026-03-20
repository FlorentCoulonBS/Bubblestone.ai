#!/usr/bin/env python3
"""BubbleStone.ai — WordPress Internal Audit (authenticated wp-admin scan)."""
import re
import requests
from urllib.parse import urljoin
from datetime import datetime


# PHP EOL dates (major.minor → end of security support)
PHP_EOL = {
    (5, 6): '2018-12-31', (7, 0): '2019-01-10', (7, 1): '2019-12-01',
    (7, 2): '2020-11-30', (7, 3): '2021-12-06', (7, 4): '2022-11-28',
    (8, 0): '2023-11-26', (8, 1): '2025-12-31', (8, 2): '2026-12-08',
    (8, 3): '2027-11-23', (8, 4): '2028-11-24',
}

# Known vulnerable plugin versions (sample — extend as needed)
KNOWN_VULN_PLUGINS = {
    'elementor': {'below': '3.18.0', 'cve': 'CVE-2024-24934'},
    'contact-form-7': {'below': '5.8.4', 'cve': 'CVE-2023-6449'},
    'wordfence': {'below': '7.10.0', 'cve': 'CVE-2023-3968'},
    'all-in-one-wp-migration': {'below': '7.77', 'cve': 'CVE-2023-40004'},
    'wp-file-manager': {'below': '6.9', 'cve': 'CVE-2020-25213'},
}


def version_tuple(v):
    """Parse version string to tuple for comparison."""
    parts = re.findall(r'\d+', str(v))
    return tuple(int(p) for p in parts) if parts else (0,)


def scan_wordpress_internal(url, wp_admin_url, wp_username, wp_password, htaccess_user="", htaccess_pass=""):
    """Authenticate to WP admin and perform deep internal audit."""
    checks = []
    total = 0
    max_score = 0
    details = {
        'plugins': [],
        'themes': [],
        'users': [],
        'updates': {},
        'php_info': {},
        'settings': {},
    }

    def check(name, passed, weight=10, detail="", category="general"):
        nonlocal total, max_score
        max_score += weight
        if passed:
            total += weight
        checks.append({
            "name": name, "passed": passed, "weight": weight,
            "detail": detail, "category": category
        })

    sess = requests.Session()
    sess.headers['User-Agent'] = 'BubbleStone-Audit/1.0'
    sess.verify = False
    if htaccess_user and htaccess_pass:
        sess.auth = (htaccess_user, htaccess_pass)

    # ── 1. Login ──────────────────────────────────────────────
    if not wp_admin_url:
        wp_admin_url = url.rstrip('/') + '/wp-admin/'
    base_site = url.rstrip('/')
    real_wp_admin = base_site + '/wp-admin/'

    try:
        # Navigate to wp_admin_url which may redirect (e.g. iThemes Security hidden login)
        login_page = sess.get(wp_admin_url, timeout=15)
        actual_login_url = login_page.url
        if login_page.status_code != 200:
            return {"score": 0, "checks": [{"name": "Connexion", "passed": False, "weight": 0, "detail": f"Login page HTTP {login_page.status_code}", "category": "auth"}], "details": details, "authenticated": False}

        login_data = {
            'log': wp_username,
            'pwd': wp_password,
            'wp-submit': 'Se connecter',
            'redirect_to': real_wp_admin,
            'testcookie': '1',
        }
        sess.cookies.set('wordpress_test_cookie', 'WP Cookie check')
        r = sess.post(actual_login_url, data=login_data, timeout=15, allow_redirects=True)

        logged_in = 'wp-admin' in r.url and 'login' not in r.url.lower()
        if not logged_in:
            # Try English submit
            login_data['wp-submit'] = 'Log In'
            r = sess.post(actual_login_url, data=login_data, timeout=15, allow_redirects=True)
            logged_in = 'wp-admin' in r.url and 'login' not in r.url.lower()

        check("Connexion admin", logged_in, 0, "OK" if logged_in else "Échec d'authentification", "auth")
        if not logged_in:
            return {"score": 0, "checks": checks, "details": details, "authenticated": False}
    except Exception as e:
        return {"score": 0, "checks": [{"name": "Connexion", "passed": False, "weight": 0, "detail": str(e), "category": "auth"}], "details": details, "authenticated": False}

    base_admin = real_wp_admin.rstrip('/')

    # ── 2. Updates Page ───────────────────────────────────────
    try:
        updates_page = sess.get(base_admin + '/update-core.php', timeout=15).text

        # WordPress core update
        wp_up_to_date = 'Vous avez la dernière version' in updates_page or 'You have the latest version' in updates_page
        wp_version_match = re.search(r'Version\s+([\d.]+)', updates_page)
        wp_version = wp_version_match.group(1) if wp_version_match else '?'
        details['updates']['wordpress'] = {'version': wp_version, 'up_to_date': wp_up_to_date}
        check("WordPress à jour", wp_up_to_date, 15,
              f"Version {wp_version}" + ("" if wp_up_to_date else " — mise à jour disponible"), "updates")

        # Plugin updates
        plugin_updates = len(re.findall(r'plugin-update-tr|update-message', updates_page))
        check("Plugins à jour", plugin_updates == 0, 12,
              f"{plugin_updates} plugin(s) à mettre à jour" if plugin_updates else "Tous à jour", "updates")
        details['updates']['plugins_pending'] = plugin_updates

        # Theme updates
        theme_updates = len(re.findall(r'theme-update-tr', updates_page))
        check("Thèmes à jour", theme_updates == 0, 5,
              f"{theme_updates} thème(s) à mettre à jour" if theme_updates else "Tous à jour", "updates")
        details['updates']['themes_pending'] = theme_updates
    except Exception as e:
        check("Page mises à jour", False, 0, str(e), "updates")

    # ── 3. Plugins Page ───────────────────────────────────────
    try:
        plugins_page = sess.get(base_admin + '/plugins.php', timeout=15).text

        # Parse plugin rows
        plugin_rows = re.findall(
            r'data-slug="([^"]+)".*?<strong>([^<]+)</strong>.*?Version\s*([\d.]+)',
            plugins_page, re.DOTALL
        )
        active_plugins = re.findall(r'data-slug="([^"]+)"[^>]*class="[^"]*active[^"]*"', plugins_page)
        inactive_plugins = re.findall(r'data-slug="([^"]+)"[^>]*class="[^"]*inactive[^"]*"', plugins_page)

        for slug, name, version in plugin_rows:
            is_active = slug in ' '.join(active_plugins) if active_plugins else True
            details['plugins'].append({
                'slug': slug, 'name': name.strip(), 'version': version,
                'active': is_active,
                'vulnerable': False
            })

        # Check known vulnerabilities
        vuln_count = 0
        for p in details['plugins']:
            slug = p['slug']
            if slug in KNOWN_VULN_PLUGINS:
                threshold = KNOWN_VULN_PLUGINS[slug]['below']
                if version_tuple(p['version']) < version_tuple(threshold):
                    p['vulnerable'] = True
                    p['cve'] = KNOWN_VULN_PLUGINS[slug]['cve']
                    vuln_count += 1

        check("Plugins sans vulnérabilité connue", vuln_count == 0, 15,
              f"{vuln_count} plugin(s) vulnérable(s)" if vuln_count else "Aucune vulnérabilité détectée", "plugins")

        # Inactive plugins (attack surface)
        n_inactive = len(inactive_plugins)
        check("Pas de plugins inactifs", n_inactive == 0, 8,
              f"{n_inactive} plugin(s) inactif(s) — surface d'attaque inutile" if n_inactive else "OK", "plugins")

        total_plugins = len(plugin_rows)
        check("Nombre de plugins raisonnable", total_plugins <= 20, 5,
              f"{total_plugins} plugins installés" + (" — trop de plugins = lenteur + risques" if total_plugins > 20 else ""), "plugins")

    except Exception as e:
        check("Analyse des plugins", False, 0, str(e), "plugins")

    # ── 4. Users Page ─────────────────────────────────────────
    try:
        users_page = sess.get(base_admin + '/users.php', timeout=15).text

        admin_users = re.findall(r'role="row".*?>(.*?)</tr>', users_page, re.DOTALL)
        admins = users_page.lower().count('administrator') - 1  # minus header
        # Count from role column more accurately
        admin_count = len(re.findall(r'>Administrateur<|>Administrator<', users_page))
        total_users = len(re.findall(r'data-colname', users_page)) // 5 if 'data-colname' in users_page else 0

        # Parse user info
        user_rows = re.findall(r'class="username[^"]*"[^>]*>.*?<strong><a[^>]*>([^<]+)</a>.*?<td[^>]*class="[^"]*role[^"]*"[^>]*>([^<]+)', users_page, re.DOTALL)
        for uname, role in user_rows:
            details['users'].append({'username': uname.strip(), 'role': role.strip()})

        check("Nombre d'admins limité", admin_count <= 2, 10,
              f"{admin_count} administrateur(s)" + (" — réduire les privilèges" if admin_count > 2 else ""), "users")

        # Check for 'admin' username
        has_admin_user = any(u.get('username', '').lower() == 'admin' for u in details['users'])
        check("Pas de compte 'admin'", not has_admin_user, 8,
              "Compte 'admin' trouvé — nom prévisible, cible de brute force" if has_admin_user else "OK", "users")

    except Exception as e:
        check("Analyse des utilisateurs", False, 0, str(e), "users")

    # ── 5. Settings ───────────────────────────────────────────
    try:
        general_page = sess.get(base_admin + '/options-general.php', timeout=15).text

        # Registration open?
        anyone_can_register = 'users_can_register" checked' in general_page or "users_can_register' checked" in general_page
        check("Inscription fermée", not anyone_can_register, 10,
              "Les inscriptions sont ouvertes — risque de spam et d'accès non autorisé" if anyone_can_register else "Inscriptions fermées", "settings")

        # Timezone set?
        tz_match = re.search(r'timezone_string.*?value="([^"]*)".*?selected', general_page, re.DOTALL)

        # Discourage search engines?
        reading_page = sess.get(base_admin + '/options-reading.php', timeout=15).text
        discourage_se = 'blog_public" value="0" checked' in reading_page
        # Only flag if site should be public
        details['settings']['search_engine_discouraged'] = discourage_se

        # Discussion settings
        discussion_page = sess.get(base_admin + '/options-discussion.php', timeout=15).text
        pingbacks = 'default_pingback_flag" checked' in discussion_page or "default_pingback_flag' checked" in discussion_page
        check("Pingbacks désactivés", not pingbacks, 5,
              "Pingbacks activés — vecteur de DDoS et spam" if pingbacks else "Désactivés", "settings")

    except Exception as e:
        check("Analyse des réglages", False, 0, str(e), "settings")

    # ── 6. PHP Info (from Site Health) ────────────────────────
    try:
        # Try Site Health debug page
        health_page = sess.get(base_admin + '/site-health-info.php', timeout=15).text

        php_match = re.search(r'PHP[^<]*?(\d+\.\d+\.\d+)', health_page)
        if php_match:
            php_version = php_match.group(1)
            details['php_info']['version'] = php_version
            major_minor = tuple(int(x) for x in php_version.split('.')[:2])
            eol_date = PHP_EOL.get(major_minor)
            is_eol = False
            if eol_date:
                is_eol = datetime.strptime(eol_date, '%Y-%m-%d') < datetime.now()
            check("PHP supporté", not is_eol, 12,
                  f"PHP {php_version}" + (f" — EOL depuis {eol_date}" if is_eol else " — supporté"), "php")

        # MySQL version
        mysql_match = re.search(r'MySQL.*?(\d+\.\d+\.\d+)|MariaDB.*?(\d+\.\d+\.\d+)', health_page)
        if mysql_match:
            db_version = mysql_match.group(1) or mysql_match.group(2)
            details['php_info']['database'] = db_version

        # Memory limit
        mem_match = re.search(r'memory_limit.*?(\d+\s*[MG])', health_page, re.IGNORECASE)
        if mem_match:
            mem = mem_match.group(1)
            details['php_info']['memory_limit'] = mem
            mem_val = int(re.search(r'\d+', mem).group())
            if 'G' in mem.upper():
                mem_val *= 1024
            check("Mémoire PHP suffisante", mem_val >= 256, 5,
                  f"{mem} — {'OK' if mem_val >= 256 else 'insuffisant (<256M)'}", "php")

        # Max execution time
        exec_match = re.search(r'max_execution_time.*?(\d+)', health_page)
        if exec_match:
            exec_time = int(exec_match.group(1))
            details['php_info']['max_execution_time'] = exec_time

        # Upload size
        upload_match = re.search(r'upload_max_filesize.*?(\d+\s*[MG])', health_page, re.IGNORECASE)
        if upload_match:
            details['php_info']['upload_max'] = upload_match.group(1)

    except Exception as e:
        check("Info PHP/Serveur", False, 0, str(e), "php")

    # ── 7. Security plugins check ─────────────────────────────
    security_plugins = ['wordfence', 'sucuri-scanner', 'ithemes-security', 'all-in-one-wp-security-and-firewall',
                        'better-wp-security', 'wp-cerber', 'shield-security', 'defender-security']
    has_security = any(p['slug'] in security_plugins for p in details['plugins'])
    check("Plugin de sécurité installé", has_security, 8,
          "OK" if has_security else "Aucun plugin de sécurité détecté (Wordfence, Sucuri, etc.)", "plugins")

    # ── 8. Backup plugin check ────────────────────────────────
    backup_plugins = ['updraftplus', 'backwpup', 'duplicator', 'all-in-one-wp-migration',
                      'jetpack', 'blogvault-real-time-backup', 'backup-backup']
    has_backup = any(p['slug'] in backup_plugins for p in details['plugins'])
    check("Plugin de backup installé", has_backup, 8,
          "OK" if has_backup else "Aucun plugin de backup détecté", "plugins")

    # ── 9. SSL in site URL ────────────────────────────────────
    try:
        site_url_match = re.search(r'siteurl.*?value="(https?://[^"]+)"', general_page) if 'general_page' in dir() else None
        if site_url_match:
            site_url = site_url_match.group(1)
            check("URL du site en HTTPS", site_url.startswith('https'), 5,
                  site_url, "settings")
    except:
        pass

    score = round(total / max_score * 100) if max_score > 0 else 0

    return {
        "score": score,
        "checks": checks,
        "details": details,
        "authenticated": True,
    }


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 4:
        print("Usage: wordpress_internal.py <url> <wp_admin_url> <username> <password> [htaccess_user] [htaccess_pass]")
        sys.exit(1)
    import json
    result = scan_wordpress_internal(
        sys.argv[1], sys.argv[2], sys.argv[3],
        sys.argv[4] if len(sys.argv) > 4 else '',
        htaccess_user=sys.argv[5] if len(sys.argv) > 5 else '',
        htaccess_pass=sys.argv[6] if len(sys.argv) > 6 else '',
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
