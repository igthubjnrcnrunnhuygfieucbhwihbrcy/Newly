#!/usr/bin/env python3
"""ZelfSync + browser-in-browser voor Newly (Raspberry Pi 5).

EEN dienst, twee taken:
1. Sync-server: multi-user accounts, bookmarks, geschiedenis (SQLite).
2. Browser-in-browser: open http://pi-adres:8765/ in een gewone browser
   en je krijgt een adresbalk die pagina's via deze Pi ophaalt en toont.

Start:      python3 server.py      (poort 8765, of ZELFSYNC_PORT=...)
Service:    zie install-pi.sh (systemd)
"""
import gzip
import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "zelfsync.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
MAX_BODY = 1_000_000
MAX_PAGE = 6 * 1024 * 1024
PORT = int(os.environ.get("ZELFSYNC_PORT", "8765"))

INDEX_HTML = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Newly — browser in browser</title>
<style>
 body { margin:0; font:14px system-ui, sans-serif; background:#1e2227; color:#e8eaed; }
 #bar { display:flex; gap:8px; padding:10px; position:sticky; top:0; background:#1e2227; z-index:5; }
 input { background:#2a3038; border:0; border-radius:8px; padding:9px 12px; color:#e8eaed; outline:none; }
 #url { flex:1; }
 button { background:#1a56db; color:#fff; border:0; border-radius:8px; padding:9px 14px; cursor:pointer; }
 #side { padding:10px; max-height:45vh; overflow:auto; background:#232830; display:none; }
 #side a { color:#9ec1ff; display:block; padding:4px 0; }
 iframe { width:100%; height:calc(100vh - 120px); border:0; background:#fff; }
 .hint { font-size:12px; color:#9aa0a6; padding:0 10px 6px; }
</style>
</head>
<body>
 <div id="bar">
   <input id="url" placeholder="Website-adres, bijv. nl.wikipedia.org">
   <button onclick="ga()">Ga</button>
   <button onclick="blad()">Bladwijzers</button>
   <button onclick="sla()">+ Opslaan</button>
 </div>
 <div class="hint">Browser-in-browser via je eigen Pi. JavaScript-pagina's kunnen beperkt tonen.</div>
 <div id="side"></div>
 <iframe id="frame"></iframe>
<script>
var token = localStorage.getItem('zelfsync_token') || '';
var huidig = '';

function ga() {
  var v = document.getElementById('url').value.trim();
  if (!v) return;
  if (v.indexOf('http') !== 0) v = 'https://' + v;
  huidig = v;
  document.getElementById('frame').src = '/browse?url=' + encodeURIComponent(v);
  if (token) {
    fetch('/history', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ url: v, title: v }) });
  }
}

function sla() {
  if (!huidig) { meld('Ga eerst naar een pagina.'); return; }
  if (!token) { login(); return; }
  fetch('/bookmarks', { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
    body: JSON.stringify({ url: huidig, title: huidig }) })
    .then(function (r) { return r.json(); })
    .then(function (d) { meld(d.error || 'Opgeslagen in je bladwijzers!'); });
}

function blad() {
  var s = document.getElementById('side');
  if (s.style.display === 'block') { s.style.display = 'none'; return; }
  s.style.display = 'block';
  if (!token) { login(); return; }
  fetch('/bookmarks', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      s.innerHTML = '';
      var lijst = d.bookmarks || [];
      if (!lijst.length) { s.innerHTML = 'Nog geen bladwijzers.'; return; }
      lijst.forEach(function (b) {
        var a = document.createElement('a');
        a.href = '#';
        a.textContent = b.title || b.url;
        a.onclick = function () { openB(b.url); return false; };
        s.appendChild(a);
      });
    });
}

function openB(u) {
  document.getElementById('url').value = u;
  document.getElementById('side').style.display = 'none';
  ga();
}

function meld(t) {
  var s = document.getElementById('side');
  s.style.display = 'block';
  s.innerHTML = t;
}

function login() {
  var s = document.getElementById('side');
  s.style.display = 'block';
  s.innerHTML = '<h3>Inloggen of registreren</h3>' +
    '<input id="u" placeholder="Gebruikersnaam"> ' +
    '<input id="p" type="password" placeholder="Wachtwoord (min. 8 tekens)"><br><br>' +
    '<button onclick="reg()">Registreren</button> <button onclick="log()">Inloggen</button>';
}

function reg() { stuur('register'); }
function log() { stuur('login'); }

function stuur(route) {
  var body = JSON.stringify({
    username: document.getElementById('u').value,
    password: document.getElementById('p').value
  });
  fetch('/' + route, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: body })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.token) {
        token = d.token;
        localStorage.setItem('zelfsync_token', token);
        meld('Ingelogd! Opslaan werkt nu.');
      } else { meld(d.error || 'Mislukt'); }
    });
}
</script>
</body>
</html>
"""

def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        "CREATE TABLE IF NOT EXISTS users ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  username TEXT UNIQUE NOT NULL,"
        "  pwhash TEXT NOT NULL,"
        "  salt TEXT NOT NULL,"
        "  token TEXT UNIQUE"
        ");"
        "CREATE TABLE IF NOT EXISTS bookmarks ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  user_id INTEGER NOT NULL,"
        "  title TEXT NOT NULL DEFAULT '',"
        "  url TEXT NOT NULL,"
        "  created TEXT DEFAULT (datetime('now'))"
        ");"
        "CREATE TABLE IF NOT EXISTS history ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  user_id INTEGER NOT NULL,"
        "  title TEXT NOT NULL DEFAULT '',"
        "  url TEXT NOT NULL,"
        "  visited TEXT DEFAULT (datetime('now'))"
        ");")
    return con


def hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               bytes.fromhex(salt_hex), 120_000).hex()


def proxy_page(target):
    """Haal een pagina op en maak hem veilig toonbaar binnen onze browser."""
    req = urllib.request.Request(target, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux) NewlyBrowser/0.1",
        "Accept": "text/html,application/xhtml+xml,text/plain,*/*;q=0.5",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read(MAX_PAGE)
        final_url = resp.geturl()
        ctype = resp.headers.get("Content-Type", "text/html; charset=utf-8")
        if resp.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
    m = re.search(r"charset\s*=\s*['\"]?([\w.-]+)", ctype)
    enc = m.group(1) if m else "utf-8"
    try:
        text = raw.decode(enc, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")

    is_html = "html" in ctype.lower() or "<html" in text.lower()[:4000]
    if not is_html:
        return "<html><head><title>" + html.escape(target) + "</title></head>" \
               "<body style='font-family:sans-serif'><pre>" + html.escape(text) + "</pre></body></html>"

    # 1. Scripts en event-attributen verwijderen (JavaScript wordt niet uitgevoerd).
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", text)
    text = re.sub(r"(?is)<script\b[^>]*/>", "", text)
    text = re.sub(r"(?is)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text)

    # 2. Bestaande <base> vinden en verwijderen.
    mb = re.search(r"(?is)<base[^>]+href=[\"']([^\"']+)[\"']", text)
    base = urllib.parse.urljoin(final_url, mb.group(1)) if mb else final_url
    if mb:
        text = text.replace(mb.group(0), "")

    # 3. Links herschrijven zodat ze binnen deze browser-in-browser blijven.
    def rewrite(m):
        v = m.group(1)
        if v.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            return m.group(0)
        absolute = urllib.parse.urljoin(base, v)
        if absolute.startswith(("http://", "https://")):
            return 'href="/browse?url=' + urllib.parse.quote(absolute, safe="") + '"'
        return m.group(0)
    text = re.sub(r"(?is)href=[\"']([^\"']+)[\"']", rewrite, text)

    # 4. Originele base injecteren zodat css/afbeeldingen goed laden.
    inject = '<base href="' + html.escape(base) + '">'
    if re.search(r"(?is)<head[^>]*>", text):
        text = re.sub(r"(?is)(<head[^>]*>)", lambda m: m.group(1) + inject, text, count=1)
    else:
        text = inject + text
    return text


class Handler(BaseHTTPRequestHandler):
    server_version = "ZelfSync/0.2"

    # ---------- helpers ----------
    def send_json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, code, body, extra_headers=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy",
                         "script-src 'none'; object-src 'none'; frame-ancestors 'self'")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return None

    def auth_user(self, con):
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        if not token:
            return None
        return con.execute("SELECT id, username FROM users WHERE token = ?",
                           (token,)).fetchone()

    # ---------- routing ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_html(200, INDEX_HTML)
            return
        if self.path.startswith("/browse"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            target = (params.get("url") or [""])[0]
            if not target.startswith(("http://", "https://")):
                self.send_html(400, "<h3>Ongeldig adres</h3><p><a href='/'>Terug</a></p>")
                return
            try:
                self.send_html(200, proxy_page(target))
            except Exception as exc:
                self.send_html(502,
                    "<h3>Pagina kon niet worden geladen</h3><p>" + html.escape(str(exc)) +
                    "</p><p><a href='/'>Terug naar Newly</a></p>")
            return

        con = connect()
        try:
            if self.path == "/health":
                self.send_json(200, {"status": "ok", "server": "zelfsync", "version": "0.2"})
                return
            user = self.auth_user(con)
            if not user:
                self.send_json(401, {"error": "ongeldige of ontbrekende token"})
                return
            if self.path == "/bookmarks":
                rows = con.execute(
                    "SELECT id, title, url, created FROM bookmarks WHERE user_id = ? ORDER BY id DESC",
                    (user[0],)).fetchall()
                self.send_json(200, {"bookmarks": [
                    {"id": r[0], "title": r[1], "url": r[2], "created": r[3]} for r in rows]})
                return
            if self.path.startswith("/history"):
                limit = 500
                if "limit=" in self.path:
                    try:
                        limit = min(2000, max(1, int(self.path.split("limit=")[1].split("&")[0])))
                    except ValueError:
                        pass
                rows = con.execute(
                    "SELECT id, title, url, visited FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                    (user[0], limit)).fetchall()
                self.send_json(200, {"history": [
                    {"id": r[0], "title": r[1], "url": r[2], "visited": r[3]} for r in rows]})
                return
            if self.path == "/export":
                bm = con.execute("SELECT title, url, created FROM bookmarks WHERE user_id = ?",
                                 (user[0],)).fetchall()
                hi = con.execute("SELECT title, url, visited FROM history WHERE user_id = ?",
                                 (user[0],)).fetchall()
                self.send_json(200, {"bookmarks": bm, "history": hi})
                return
            self.send_json(404, {"error": "onbekend endpoint"})
        finally:
            con.close()

    def do_POST(self):
        con = connect()
        try:
            path = self.path.rstrip("/")
            body = self.read_json() or {}
            if path == "/register":
                username = str(body.get("username", "")).strip()
                password = str(body.get("password", ""))
                if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
                    self.send_json(400, {"error": "gebruikersnaam: 3-40 tekens (a-z, 0-9, _ . -)"})
                    return
                if len(password) < 8:
                    self.send_json(400, {"error": "wachtwoord: minimaal 8 tekens"})
                    return
                salt = secrets.token_hex(16)
                token = secrets.token_hex(32)
                try:
                    con.execute(
                        "INSERT INTO users (username, pwhash, salt, token) VALUES (?, ?, ?, ?)",
                        (username, hash_password(password, salt), salt, token))
                    con.commit()
                except sqlite3.IntegrityError:
                    self.send_json(409, {"error": "gebruikersnaam bestaat al"})
                    return
                self.send_json(201, {"ok": True, "token": token})
                return
            if path == "/login":
                row = con.execute("SELECT id, pwhash, salt, token FROM users WHERE username = ?",
                                  (str(body.get("username", "")),)).fetchone()
                if not row or hash_password(str(body.get("password", "")), row[2]) != row[1]:
                    self.send_json(401, {"error": "verkeerde inloggegevens"})
                    return
                self.send_json(200, {"ok": True, "token": row[3]})
                return
            user = self.auth_user(con)
            if not user:
                self.send_json(401, {"error": "ongeldige of ontbrekende token"})
                return
            if path == "/bookmarks":
                url = str(body.get("url", "")).strip()
                title = str(body.get("title", "")).strip()[:200]
                if not url.startswith(("http://", "https://", "about:")):
                    self.send_json(400, {"error": "url moet met http(s):// beginnen"})
                    return
                exists = con.execute("SELECT id FROM bookmarks WHERE user_id = ? AND url = ?",
                                     (user[0], url)).fetchone()
                if not exists:
                    con.execute("INSERT INTO bookmarks (user_id, title, url) VALUES (?, ?, ?)",
                                (user[0], title, url))
                    con.commit()
                self.send_json(201, {"ok": True})
                return
            if path == "/history":
                url = str(body.get("url", "")).strip()
                if not url:
                    self.send_json(400, {"error": "url ontbreekt"})
                    return
                con.execute("INSERT INTO history (user_id, title, url) VALUES (?, ?, ?)",
                            (user[0], str(body.get("title", ""))[:200], url))
                con.commit()
                self.send_json(201, {"ok": True})
                return
            self.send_json(404, {"error": "onbekend endpoint"})
        finally:
            con.close()


def main():
    print("ZelfSync + browser-in-browser draait op poort %d" % PORT)
    print("Open in een browser op hetzelfde netwerk: http://<pi-adres>:%d/" % PORT)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("ZelfSync gestopt.")


if __name__ == "__main__":
    main()
