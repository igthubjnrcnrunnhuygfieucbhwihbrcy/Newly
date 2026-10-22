#!/usr/bin/env python3
"""ZelfSync + browser-in-browser voor Newly (Raspberry Pi 5).

EEN dienst, twee taken:
1. Sync-server: multi-user accounts, bookmarks, geschiedenis (SQLite).
2. Browser-in-browser: open http://pi-adres:8765/ in een gewone browser
   en je krijgt een moderne startpagina met adresbalk; pagina's worden
   door de Pi opgehaald en veilig (zonder JavaScript) getoond.

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
<meta name="theme-color" content="#0f141a">
<title>Newly</title>
<style>
 * { box-sizing: border-box; }
 body { margin: 0; font-family: -apple-system, 'Segoe UI', Roboto, system-ui, sans-serif;
        background: #0f141a; color: #e8ecf2; }
 header { position: sticky; top: 0; z-index: 10; display: flex; gap: 6px; align-items: center;
   padding: 10px 12px; background: rgba(15,20,26,.94); backdrop-filter: blur(12px);
   border-bottom: 1px solid #232b36; }
 .iconbtn { width: 40px; height: 40px; border-radius: 50%; border: 0; background: transparent;
   color: #c6cfdb; font-size: 18px; cursor: pointer; display: flex; align-items: center;
   justify-content: center; flex: none; }
 .iconbtn:hover { background: #202834; }
 .addr { flex: 1; display: flex; align-items: center; background: #1c2430;
   border: 1px solid #2a3442; border-radius: 999px; padding: 0 14px; min-width: 0; }
 .addr input { flex: 1; background: transparent; border: 0; outline: none; color: #e8ecf2;
   font-size: 15px; padding: 10px 0; min-width: 0; }
 .addr .lock { color: #5f7a9d; font-size: 11px; margin-right: 8px; flex: none; }
 #loader { height: 2px; background: #3b74ff; width: 0%; transition: width .4s; }
 #content { position: relative; height: calc(100vh - 64px); }
 #start { position: absolute; inset: 0; overflow: auto; display: flex; flex-direction: column;
   align-items: center; padding: 64px 20px 30px; }
 .logo { font-size: 34px; font-weight: 800; letter-spacing: -.5px; }
 .logo b { color: #3b74ff; font-weight: 800; }
 .zoek { display: flex; width: 100%; max-width: 560px; margin: 24px 0 42px; background: #1c2430;
   border: 1px solid #2a3442; border-radius: 999px; padding: 4px; }
 .zoek input { flex: 1; background: transparent; border: 0; outline: none; color: #e8ecf2;
   font-size: 16px; padding: 12px 20px; min-width: 0; }
 .zoek button { background: #3b74ff; border: 0; border-radius: 999px; color: #fff;
   padding: 12px 22px; font-size: 15px; font-weight: 600; cursor: pointer; flex: none; }
 .zoek button:hover { background: #2f63e8; }
 .tegels { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
   gap: 14px; width: 100%; max-width: 560px; }
 .tegel { background: #161d27; border: 1px solid #232b36; border-radius: 16px;
   padding: 18px 10px; text-align: center; cursor: pointer; transition: .15s; }
 .tegel:hover { background: #1d2530; transform: translateY(-2px); border-color: #2f3b4c; }
 .tegel .em { font-size: 26px; display: block; margin-bottom: 8px; }
 .tegel .nm { font-size: 13px; color: #aab6c5; }
 iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0;
   background: #fff; display: none; }
 #panel { position: fixed; top: 64px; right: 12px; width: min(92vw, 340px);
   background: #161d27; border: 1px solid #2a3442; border-radius: 16px; padding: 18px;
   display: none; z-index: 20; box-shadow: 0 12px 34px rgba(0,0,0,.45); }
 #panel h3 { margin: 0 0 12px; font-size: 15px; }
 #panel input { width: 100%; background: #1c2430; border: 1px solid #2a3442;
   border-radius: 10px; color: #e8ecf2; padding: 11px; margin-bottom: 8px; outline: none;
   font-size: 14px; }
 .sub { background: #202834; color: #dbe4ef; border: 0; border-radius: 10px;
   padding: 11px 16px; cursor: pointer; font-size: 14px; margin-right: 6px; }
 .sub.blauw { background: #3b74ff; color: #fff; }
 #panel a { color: #9ec1ff; display: block; padding: 7px 0; font-size: 14px;
   text-decoration: none; border-bottom: 1px solid #232b36; }
 #panel a:hover { color: #c2d8ff; }
 #toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
   background: #233043; color: #dbe4ef; padding: 11px 20px; border-radius: 999px;
   font-size: 13px; display: none; z-index: 30; box-shadow: 0 6px 20px rgba(0,0,0,.35); }
 .hint { font-size: 12px; color: #5c6875; margin-top: 46px; text-align: center; max-width: 420px; }
</style>
</head>
<body>
<header>
  <button class="iconbtn" onclick="terug()" title="Terug">&#8592;</button>
  <button class="iconbtn" onclick="ververs()" title="Verversen">&#8635;</button>
  <form class="addr" onsubmit="return ga()">
    <span class="lock">&#128274;</span>
    <input id="url" placeholder="Zoek of typ een webadres" autocomplete="off" spellcheck="false">
  </form>
  <button class="iconbtn" onclick="sla()" title="Bladwijzer maken">&#9733;</button>
  <button class="iconbtn" onclick="menu()" title="Account en bladwijzers">&#9787;</button>
</header>
<div id="loader"></div>

<div id="content">
  <div id="start">
    <div class="logo">New<b>l</b>y</div>
    <form class="zoek" onsubmit="return ga()">
      <input id="url2" placeholder="Zoek of typ een webadres" autocomplete="off" spellcheck="false">
      <button type="submit">Ga</button>
    </form>
    <div class="tegels" id="tegels"></div>
    <div class="hint">Jouw eigen browser-in-browser op de Pi. Pagina's worden veilig opgehaald;
      JavaScript wordt niet uitgevoerd.</div>
  </div>
  <iframe id="frame"></iframe>
</div>

<div id="panel"></div>
<div id="toast"></div>

<script>
var token = localStorage.getItem('zelfsync_token') || '';
var huidig = '';
var stack = [];

var TEGELS = [
  ['Wikipedia', '\uD83D\uDCDA', 'https://nl.wikipedia.org'],
  ['NU.nl', '\uD83D\uDCF0', 'https://www.nu.nl'],
  ['NOS', '\uD83D\uDCF1', 'https://nos.nl'],
  ['Bright', '\uD83D\uDCA1', 'https://www.bright.nl'],
  ['Startpagina', '\uD83D\uDD0D', 'https://www.startpagina.nl'],
  ['Tweakers', '\uD83D\uDCBB', 'https://tweakers.net']
];

(function bouwTegels() {
  var w = document.getElementById('tegels');
  TEGELS.forEach(function (t) {
    var d = document.createElement('div');
    d.className = 'tegel';
    var em = document.createElement('span');
    em.className = 'em';
    em.textContent = t[1];
    var nm = document.createElement('span');
    nm.className = 'nm';
    nm.textContent = t[0];
    d.appendChild(em); d.appendChild(nm);
    d.onclick = function () { openB(t[2]); };
    w.appendChild(d);
  });
})();

function laad(v) {
  if (v.indexOf('http') !== 0) v = 'https://' + v;
  huidig = v;
  document.getElementById('url').value = v;
  document.getElementById('url2').value = v;
  document.getElementById('start').style.display = 'none';
  var f = document.getElementById('frame');
  f.style.display = 'block';
  f.src = '/browse?url=' + encodeURIComponent(v);
  var l = document.getElementById('loader');
  l.style.width = '70%';
  if (token) {
    fetch('/history', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ url: v, title: v }) }).catch(function () {});
  }
}

function ga() {
  var v = (document.activeElement && document.activeElement.id === 'url2')
    ? document.getElementById('url2').value.trim()
    : document.getElementById('url').value.trim();
  if (!v) return false;
  if (huidig && stack[stack.length - 1] !== huidig) stack.push(huidig);
  laad(v);
  return false;
}

function openB(u) {
  if (huidig) stack.push(huidig);
  laad(u);
}

function terug() {
  if (!stack.length) { naarStart(); return; }
  laad(stack.pop());
}

function ververs() { if (huidig) laad(huidig); }

function naarStart() {
  document.getElementById('frame').style.display = 'none';
  document.getElementById('start').style.display = 'flex';
  document.getElementById('url').value = '';
  document.getElementById('url2').value = '';
  huidig = '';
  document.title = 'Newly';
}

function sla() {
  if (!huidig) { toast('Ga eerst naar een pagina.'); return; }
  if (!token) { menu(); return; }
  fetch('/bookmarks', { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
    body: JSON.stringify({ url: huidig, title: huidig }) })
    .then(function (r) { return r.json(); })
    .then(function (d) { toast(d.error || 'Bladwijzer opgeslagen'); });
}

function toast(t) {
  var el = document.getElementById('toast');
  el.textContent = t;
  el.style.display = 'block';
  clearTimeout(el._t);
  el._t = setTimeout(function () { el.style.display = 'none'; }, 2600);
}

function menu() {
  var p = document.getElementById('panel');
  if (p.style.display === 'block') { p.style.display = 'none'; return; }
  p.style.display = 'block';
  if (token) { laadBladwijzers(p); } else { laadLogin(p); }
}

function laadLogin(p) {
  p.innerHTML = '<h3>Inloggen of registreren</h3>' +
    '<input id="u" placeholder="Gebruikersnaam">' +
    '<input id="p" type="password" placeholder="Wachtwoord (min. 8 tekens)">' +
    '<button class="sub blauw" onclick="stuur(\'register\')">Account maken</button>' +
    '<button class="sub" onclick="stuur(\'login\')">Inloggen</button>';
}

function laadBladwijzers(p) {
  p.innerHTML = '<h3>Bladwijzers</h3><div id="lijst">Laden...</div>' +
    '<button class="sub" onclick="uitloggen()" style="margin-top:10px">Uitloggen</button>';
  fetch('/bookmarks', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var lijst = document.getElementById('lijst');
      lijst.innerHTML = '';
      var items = d.bookmarks || [];
      if (!items.length) { lijst.innerHTML = '<div style="color:#8b97a6;font-size:13px">Nog geen bladwijzers. Gebruik de &#9733; op een pagina.</div>'; return; }
      items.forEach(function (b) {
        var a = document.createElement('a');
        a.href = '#';
        a.textContent = b.title || b.url;
        a.onclick = function () { p.style.display = 'none'; openB(b.url); return false; };
        lijst.appendChild(a);
      });
    });
}

function uitloggen() {
  token = '';
  localStorage.removeItem('zelfsync_token');
  document.getElementById('panel').style.display = 'none';
  toast('Uitgelogd');
}

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
        toast('Ingelogd');
        laadBladwijzers(document.getElementById('panel'));
      } else { toast(d.error || 'Mislukt'); }
    });
}

document.getElementById('frame').addEventListener('load', function () {
  var l = document.getElementById('loader');
  l.style.width = '100%';
  setTimeout(function () { l.style.width = '0%'; }, 350);
  try {
    var t = document.getElementById('frame').contentWindow.document.title;
    if (t) document.title = t;
  } catch (e) {}
});
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


LEEG_BANNER = (
    '<div style="font-family:system-ui,sans-serif;background:#fff7ed;color:#7c4a03;'
    'padding:16px;border-bottom:1px solid #fcd9a8;font-size:14px">'
    'Deze site draait vrijwel volledig op JavaScript. Newly voert JavaScript niet '
    'uit, daarom is de weergave (bijna) leeg. Veel nieuws-, wiki- en '
    'informatiesites tonen wel volledig.</div>')


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
        return ("<html><head><title>" + html.escape(target) + "</title></head>"
                "<body style='font-family:system-ui,sans-serif'><pre>"
                + html.escape(text) + "</pre></body></html>")

    # 1. Scripts, event-attributen en meta-refresh verwijderen (geen JavaScript).
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", text)
    text = re.sub(r"(?is)<script\b[^>]*/>", "", text)
    text = re.sub(r"(?is)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text)
    text = re.sub(r"(?is)<meta[^>]+http-equiv=[\"']refresh[\"'][^>]*>", "", text)

    # 2. Bestaande <base> vinden en verwijderen.
    mb = re.search(r"(?is)<base[^>]+href=[\"']([^\"']+)[\"']", text)
    base = urllib.parse.urljoin(final_url, mb.group(1)) if mb else final_url
    if mb:
        text = text.replace(mb.group(0), "")

    # 3. Links herschrijven zodat ze binnen deze browser blijven.
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

    # 5. Bijna lege (JavaScript-only) pagina's herkennen en aankondigen.
    zonder_tags = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", text)
    zonder_tags = re.sub(r"(?is)<[^>]+>", " ", zonder_tags)
    if len(re.sub(r"\s+", "", zonder_tags)) < 200:
        text = LEEG_BANNER + text
    return text


class Handler(BaseHTTPRequestHandler):
    server_version = "ZelfSync/0.3"

    # ---------- helpers ----------
    def send_json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, code, body, csp=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if csp:
            self.send_header("Content-Security-Policy", csp)
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
            # Geen strikte CSP hier: de UI heeft eigen (inline) script nodig.
            self.send_html(200, INDEX_HTML)
            return
        if self.path.startswith("/browse"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            target = (params.get("url") or [""])[0]
            if not target.startswith(("http://", "https://")):
                self.send_html(400,
                               "<h3 style='font-family:system-ui'>Ongeldig adres</h3>"
                               "<p><a href='/'>Terug naar Newly</a></p>")
                return
            try:
                self.send_html(200, proxy_page(target),
                               csp="script-src 'none'; object-src 'none'; "
                                   "frame-src 'none'; frame-ancestors 'self'")
            except Exception as exc:
                self.send_html(502,
                    "<div style='font-family:system-ui;max-width:560px;margin:60px auto'>"
                    "<h2>Pagina kon niet worden geladen</h2><p style='color:#666'>"
                    + html.escape(str(exc)) + "</p>"
                    "<p><a href='/'>Terug naar Newly</a></p></div>",
                    csp="script-src 'none'")
            return

        con = connect()
        try:
            if self.path == "/health":
                self.send_json(200, {"status": "ok", "server": "zelfsync", "version": "0.3"})
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
