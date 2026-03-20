#!/usr/bin/env python3
"""BubbleStone.ai — Flask Web Application for Audit Management."""
import json
import os
import sqlite3
import subprocess
import secrets
from datetime import datetime
from functools import wraps

import bcrypt
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, send_file, abort, g)

app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))
app.secret_key = os.environ.get('SECRET_KEY', 'bsai-audit-2026-f7k9x3m1')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24h

DB_PATH = os.environ.get('DB_PATH', '/data/audits.db')

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db:
        db.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_plain TEXT DEFAULT '',
            role TEXT NOT NULL DEFAULT 'client',
            name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            domain TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            user_id INTEGER,
            results_json TEXT DEFAULT '{}',
            proposal_sent INTEGER DEFAULT 0,
            proposal_json TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    ''')
    # Migrate: add proposal columns if missing
    try:
        db.execute("ALTER TABLE audits ADD COLUMN proposal_sent INTEGER DEFAULT 0")
    except:
        pass
    try:
        db.execute("ALTER TABLE audits ADD COLUMN proposal_json TEXT DEFAULT ''")
    except:
        pass
    try:
        db.execute("ALTER TABLE audits ADD COLUMN lang TEXT DEFAULT 'fr'")
    except:
        pass
    try:
        db.execute("ALTER TABLE audits ADD COLUMN htaccess_user TEXT DEFAULT ''")
    except:
        pass
    try:
        db.execute("ALTER TABLE audits ADD COLUMN htaccess_pass TEXT DEFAULT ''")
    except:
        pass
    # Create default admin
    cur = db.execute("SELECT id FROM users WHERE username='admin'")
    if not cur.fetchone():
        pw = 'BubbleStone2026!'
        h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
        db.execute("INSERT INTO users (username, password_hash, password_plain, role, name) VALUES (?,?,?,?,?)",
                   ('admin', h, pw, 'admin', 'Administrateur'))
    db.commit()
    db.close()

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin'))
        return redirect(url_for('client_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role'] == 'admin':
                return redirect(url_for('admin'))
            return redirect(url_for('client_dashboard'))
        error = "Identifiants incorrects"
    return render_template('tpl_login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route('/admin')
@admin_required
def admin():
    db = get_db()
    audits = db.execute("SELECT a.*, u.name as client_name, u.username as client_username FROM audits a LEFT JOIN users u ON a.user_id=u.id ORDER BY a.created_at DESC").fetchall()
    clients = db.execute("SELECT * FROM users WHERE role='client' ORDER BY created_at DESC").fetchall()
    return render_template('tpl_admin.html', audits=audits, clients=clients)

@app.route('/admin/audit/new', methods=['POST'])
@admin_required
def new_audit():
    url = request.form.get('url', '').strip()
    if not url:
        return redirect(url_for('admin'))
    if not url.startswith('http'):
        url = 'https://' + url
    domain = url.replace('https://', '').replace('http://', '').split('/')[0].replace('www.', '')
    lang = request.form.get('lang', 'fr').strip()
    if lang not in ('fr', 'en'):
        lang = 'fr'
    wp_admin_url = request.form.get('wp_admin_url', '').strip()
    wp_username = request.form.get('wp_username', '').strip()
    wp_password = request.form.get('wp_password', '').strip()
    htaccess_user = request.form.get('htaccess_user', '').strip()
    htaccess_pass = request.form.get('htaccess_pass', '').strip()
    db = get_db()
    cur = db.execute("INSERT INTO audits (url, domain, status, wp_admin_url, wp_username, wp_password, htaccess_user, htaccess_pass, lang) VALUES (?,?,?,?,?,?,?,?,?)",
                     (url, domain, 'pending', wp_admin_url, wp_username, wp_password, htaccess_user, htaccess_pass, lang))
    db.commit()
    audit_id = cur.lastrowid
    # Launch audit in background
    cmd = ['python3', '/app/run_audit.py', str(audit_id), url, '--lang', lang]
    if wp_username and wp_password:
        cmd += ['--wp-admin', wp_admin_url or (url.rstrip('/') + '/wp-admin/'),
                '--wp-user', wp_username, '--wp-pass', wp_password]
    if htaccess_user and htaccess_pass:
        cmd += ['--htaccess-user', htaccess_user, '--htaccess-pass', htaccess_pass]
    subprocess.Popen(cmd, cwd='/app', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return redirect(url_for('admin'))

@app.route('/admin/audit/<int:audit_id>/delete', methods=['POST'])
@admin_required
def delete_audit(audit_id):
    db = get_db()
    db.execute("DELETE FROM audits WHERE id=?", (audit_id,))
    db.commit()
    return redirect(url_for('admin'))

@app.route('/admin/audit/<int:audit_id>/proposal', methods=['GET', 'POST'])
@admin_required
def audit_proposal(audit_id):
    db = get_db()
    audit = db.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
    if not audit:
        abort(404)
    results = json.loads(audit['results_json']) if audit['results_json'] else {}
    migration = results.get('migration', {})

    if request.method == 'POST':
        proposal = {
            'tjm': float(request.form.get('tjm', 600)),
            'days': float(request.form.get('days', migration.get('total_days', 10))),
            'description': request.form.get('description', ''),
            'includes': request.form.get('includes', ''),
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }
        proposal['total_eur'] = proposal['tjm'] * proposal['days']
        db.execute("UPDATE audits SET proposal_sent=1, proposal_json=? WHERE id=?",
                   (json.dumps(proposal), audit_id))
        db.commit()
        return redirect(url_for('admin'))

    # GET — show proposal form prefilled with migration data
    return render_template('tpl_proposal.html', audit=audit, migration=migration, results=results)

@app.route('/admin/audit/<int:audit_id>/assign', methods=['POST'])
@admin_required
def assign_audit(audit_id):
    user_id = request.form.get('user_id')
    db = get_db()
    db.execute("UPDATE audits SET user_id=? WHERE id=?", (user_id or None, audit_id))
    db.commit()
    return redirect(url_for('admin'))

@app.route('/admin/client/new', methods=['POST'])
@admin_required
def new_client():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if not username or not password:
        return redirect(url_for('admin'))
    h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db = get_db()
    try:
        db.execute("INSERT INTO users (username, password_hash, password_plain, role, name, email) VALUES (?,?,?,?,?,?)",
                   (username, h, password, 'client', name, email))
        db.commit()
    except sqlite3.IntegrityError:
        pass  # username already exists
    return redirect(url_for('admin'))

@app.route('/admin/client/<int:client_id>/delete', methods=['POST'])
@admin_required
def delete_client(client_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id=? AND role='client'", (client_id,))
    db.commit()
    return redirect(url_for('admin'))

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route('/api/audit', methods=['POST'])
def api_audit():
    data = request.get_json(force=True) if request.is_json else {}
    url = data.get('url', request.form.get('url', '')).strip()
    if not url:
        return jsonify({'error': 'URL required'}), 400
    if not url.startswith('http'):
        url = 'https://' + url
    domain = url.replace('https://', '').replace('http://', '').split('/')[0].replace('www.', '')
    lang = data.get('lang', request.form.get('lang', 'fr')).strip()
    if lang not in ('fr', 'en'):
        lang = 'fr'
    db = get_db()
    cur = db.execute("INSERT INTO audits (url, domain, status, lang) VALUES (?,?,?,?)", (url, domain, 'pending', lang))
    db.commit()
    audit_id = cur.lastrowid
    wp_admin = data.get('wp_admin_url', '')
    wp_user = data.get('wp_username', '')
    wp_pass = data.get('wp_password', '')
    ht_user = data.get('htaccess_user', '')
    ht_pass = data.get('htaccess_pass', '')
    if wp_user:
        db.execute("UPDATE audits SET wp_admin_url=?, wp_username=?, wp_password=? WHERE id=?",
                   (wp_admin, wp_user, wp_pass, audit_id))
        db.commit()
    if ht_user:
        db.execute("UPDATE audits SET htaccess_user=?, htaccess_pass=? WHERE id=?",
                   (ht_user, ht_pass, audit_id))
        db.commit()
    cmd = ['python3', '/app/run_audit.py', str(audit_id), url, '--lang', lang]
    if wp_user and wp_pass:
        cmd += ['--wp-admin', wp_admin or (url.rstrip('/') + '/wp-admin/'),
                '--wp-user', wp_user, '--wp-pass', wp_pass]
    if ht_user and ht_pass:
        cmd += ['--htaccess-user', ht_user, '--htaccess-pass', ht_pass]
    subprocess.Popen(cmd, cwd='/app', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return jsonify({'id': audit_id, 'status': 'pending'}), 201

@app.route('/api/audit/<int:audit_id>/status')
def api_audit_status(audit_id):
    db = get_db()
    audit = db.execute("SELECT id, status, completed_at FROM audits WHERE id=?", (audit_id,)).fetchone()
    if not audit:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(audit))

@app.route('/api/audits/status')
def api_audits_status():
    db = get_db()
    audits = db.execute("SELECT id, status FROM audits WHERE status IN ('pending','running')").fetchall()
    return jsonify([dict(a) for a in audits])

# ---------------------------------------------------------------------------
# Client dashboard
# ---------------------------------------------------------------------------

@app.route('/dashboard')
@login_required
def client_dashboard():
    db = get_db()
    audits = db.execute("SELECT * FROM audits WHERE user_id=? ORDER BY created_at DESC",
                        (session['user_id'],)).fetchall()
    return render_template('tpl_client.html', audits=audits)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@app.route('/report/<int:audit_id>')
@login_required
def report(audit_id):
    db = get_db()
    audit = db.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
    if not audit:
        abort(404)
    # Access control: admin can see all, client only their own
    if session.get('role') != 'admin' and audit['user_id'] != session['user_id']:
        abort(403)
    if audit['status'] != 'done':
        return render_template('tpl_pending.html', audit=audit)
    results = json.loads(audit['results_json'] or '{}')
    lang = audit['lang'] if 'lang' in audit.keys() else 'fr'
    tpl = 'tpl_report_en.html' if lang == 'en' else 'tpl_report.html'
    return render_template(tpl, audit=audit, r=results)

@app.route('/report/<int:audit_id>/pdf')
@login_required
def report_pdf(audit_id):
    db = get_db()
    audit = db.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
    if not audit:
        abort(404)
    if session.get('role') != 'admin' and audit['user_id'] != session['user_id']:
        abort(403)
    results = json.loads(audit['results_json'] or '{}')
    # Generate PDF using same Flask render
    lang = audit['lang'] if 'lang' in audit.keys() else 'fr'
    tpl = 'tpl_report_en.html' if lang == 'en' else 'tpl_report.html'
    html = render_template(tpl, audit=audit, r=results)
    # Remove topbar (not needed in PDF)
    html = html.replace('<div class="topbar">', '<div class="topbar" style="display:none">')
    tmp_html = f'/tmp/report_{audit_id}.html'
    tmp_pdf = f'/tmp/report_{audit_id}.pdf'
    with open(tmp_html, 'w') as f:
        f.write(html)
    subprocess.run([
        'google-chrome-stable', '--headless', '--disable-gpu', '--no-sandbox',
        '--disable-dev-shm-usage', '--run-all-compositor-stages-before-draw', '--virtual-time-budget=5000',
        '--print-to-pdf=' + tmp_pdf,
        '--no-pdf-header-footer',
        tmp_html
    ], capture_output=True, timeout=120)
    if os.path.exists(tmp_pdf):
        return send_file(tmp_pdf, as_attachment=True,
                         download_name=f"audit_{audit['domain']}_{audit_id}.pdf")
    abort(500)

# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

@app.route('/report/<int:audit_id>/csv')
@login_required
def report_csv(audit_id):
    db = get_db()
    audit = db.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
    if not audit:
        abort(404)
    if session.get('role') != 'admin' and audit['user_id'] != session['user_id']:
        abort(403)
    results = json.loads(audit['results_json'] or '{}')
    crawl = results.get('crawl', {})
    pages = crawl.get('pages', [])

    import csv
    import io
    output = io.StringIO()
    # UTF-8 BOM
    output.write('\ufeff')
    lang = audit['lang'] if 'lang' in audit.keys() else 'fr'
    writer = csv.writer(output, delimiter=';')
    if lang == 'en':
        writer.writerow(['current_url', 'http_status', 'title', 'meta_description', 'canonical', 'h1', 'schema', 'words', 'new_url'])
    else:
        writer.writerow(['url_actuelle', 'status_http', 'title', 'meta_description', 'canonical', 'h1', 'schema', 'mots', 'nouvelle_url'])
    for p in sorted(pages, key=lambda x: x.get('url', '')):
        writer.writerow([
            p.get('url', ''),
            p.get('status', ''),
            p.get('title', ''),
            p.get('meta_description', ''),
            p.get('canonical', ''),
            p.get('h1', ''),
            ('Yes' if lang == 'en' else 'Oui') if p.get('schema') else ('No' if lang == 'en' else 'Non'),
            p.get('word_count', 0),
            '',
        ])

    from flask import Response
    resp = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
    resp.headers['Content-Disposition'] = f'attachment; filename=mapping_{audit["domain"]}.csv'
    return resp

# ---------------------------------------------------------------------------
# Init & Run
# ---------------------------------------------------------------------------

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
