#!/usr/bin/env python3
"""ZelfSync + browser-in-browser voor Newly (Raspberry Pi 5).

Taken:
1. Sync-server: accounts, bookmarks, geschiedenis (SQLite).
2. Browser-in-browser op http://pi-adres:8765/ :
   - Volledige modus: pagina's met JavaScript, veilig gezandbakt (iframe-sandbox)
   - Veilige modus: pagina's zonder JavaScript (tekstfirst, snel)
   - Zoeken: echte zoekresultaten via DuckDuckGo, opgehaald door jouw Pi
   - AI: vraagt een LLM (Mistral) met jouw eigen API-sleutel, opgeslagen op de Pi
3. Tegels op de startpagina verschijnen op basis van wat je vaak bezoekt.

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
KEY_PATH = DB_PATH.parent / "apikey.txt"
MAX_BODY = 1_000_000
MAX_PAGE = 6 * 1024 * 1024
PORT = int(os.environ.get("ZELFSYNC_PORT", "8765"))
LLM_MODEL = os.environ.get("LLM_MODEL", "mistral-small-latest")

INDEX_HTML = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Newly</title>
<style>
 :root { --bg:#0f141a; --tekst:#e8ecf2; --balk:rgba(15,20,26,.94); --rand:#232b36;
   --vlak:#161d27; --vlak2:#1c2430; --invoer:#1c2430; --subtekst:#aab6c5; --accent:#3b74ff;
   --schaduw:rgba(0,0,0,.45); }
 body.licht { --bg:#eef2f7; --tekst:#1c2430; --balk:rgba(255,255,255,.94); --rand:#dce3ec;
   --vlak:#ffffff; --vlak2:#f2f5f9; --invoer:#f2f5f9; --subtekst:#5a6a7e; --accent:#2f63e8;
   --schaduw:rgba(30,50,80,.18); }
 * { box-sizing: border-box; }
 body { margin: 0; font-family: -apple-system, 'Segoe UI', Roboto, system-ui, sans-serif;
   background: var(--bg); color: var(--tekst); }
 header { position: sticky; top: 0; z-index: 10; display: flex; gap: 6px; align-items: center;
   padding: 10px 12px; background: var(--balk); backdrop-filter: blur(12px);
   border-bottom: 1px solid var(--rand); }
 .iconbtn { width: 40px; height: 40px; border-radius: 50%; border: 0; background: transparent;
   color: var(--tekst); font-size: 18px; cursor: pointer; display: flex; align-items: center;
   justify-content: center; flex: none; }
 .iconbtn:hover { background: var(--vlak2); }
 .addr { flex: 1; display: flex; align-items: center; background: var(--invoer);
   border: 1px solid var(--rand); border-radius: 999px; padding: 0 14px; min-width: 0; }
 .addr input { flex: 1; background: transparent; border: 0; outline: none; color: var(--tekst);
   font-size: 15px; padding: 10px 0; min-width: 0; }
 .addr .lock { color: var(--subtekst); font-size: 11px; margin-right: 8px; flex: none; }
 #loader { height: 2px; background: var(--accent); width: 0%; transition: width .4s; }
 #content { position: relative; height: calc(100vh - 64px); }
 #start { position: absolute; inset: 0; overflow: auto; display: flex; flex-direction: column;
   align-items: center; padding: 56px 20px 30px; }
 .logo { font-size: 34px; font-weight: 800; letter-spacing: -.5px; }
 .logo b { color: var(--accent); font-weight: 800; }
 .zoek { display: flex; width: 100%; max-width: 580px; margin: 22px 0 34px; background: var(--vlak);
   border: 1px solid var(--rand); border-radius: 999px; padding: 4px;
   box-shadow: 0 2px 14px var(--schaduw); }
 .zoek input { flex: 1; background: transparent; border: 0; outline: none; color: var(--tekst);
   font-size: 16px; padding: 12px 20px; min-width: 0; }
 .zoek button { background: var(--accent); border: 0; border-radius: 999px; color: #fff;
   padding: 12px 24px; font-size: 15px; font-weight: 600; cursor: pointer; flex: none; }
 .zoek button:hover { filter: brightness(1.1); }
 #results { display: none; width: 100%; max-width: 640px; text-align: left; }
 #results h2 { font-size: 15px; font-weight: 600; color: var(--subtekst); margin: 0 0 10px; }
 .res { padding: 12px 4px; border-bottom: 1px solid var(--rand); }
 .res a { color: var(--tekst); font-size: 16px; font-weight: 500; text-decoration: none; }
 .res a:hover { color: var(--accent); }
 .res .url { color: var(--accent); font-size: 12px; margin: 2px 0; word-break: break-all; }
 .res .snip { color: var(--subtekst); font-size: 13px; line-height: 1.45; }
 .tegels { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
   gap: 14px; width: 100%; max-width: 560px; }
 .tegel { background: var(--vlak); border: 1px solid var(--rand); border-radius: 16px;
   padding: 16px 10px; text-align: center; cursor: pointer; transition: .15s; }
 .tegel:hover { transform: translateY(-2px); border-color: var(--accent); }
 .tegel img { width: 30px; height: 30px; border-radius: 8px; margin-bottom: 8px; }
 .tegel .nm { font-size: 13px; color: var(--subtekst); word-break: break-all; }
 iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0;
   background: #fff; display: none; }
 #panel, #ai { position: fixed; top: 64px; right: 12px; width: min(92vw, 350px);
   background: var(--vlak); border: 1px solid var(--rand); border-radius: 16px; padding: 18px;
   display: none; z-index: 20; box-shadow: 0 12px 34px var(--schaduw); }
 #panel h3, #ai h3 { margin: 0 0 12px; font-size: 15px; }
 #panel input, #ai input, #ai textarea { width: 100%; background: var(--invoer);
   border: 1px solid var(--rand); border-radius: 10px; color: var(--tekst); padding: 11px;
   margin-bottom: 8px; outline: none; font-size: 14px; font-family: inherit; }
 .sub { background: var(--vlak2); color: var(--tekst); border: 1px solid var(--rand);
   border-radius: 10px; padding: 10px 14px; cursor: pointer; font-size: 13px; margin: 4px 4px 8px 0; }
 .sub.blauw { background: var(--accent); color: #fff; border-color: transparent; }
 #panel a { color: var(--accent); display: block; padding: 7px 0; font-size: 14px;
   text-decoration: none; border-bottom: 1px solid var(--rand); word-break: break-all; }
 .keuze { font-size: 13px; color: var(--subtekst); margin: 10px 0 4px; }
 #antwoord { font-size: 14px; line-height: 1.5; white-space: pre-wrap; color: var(--tekst); }
 #toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
   background: var(--vlak); border:1px solid var(--rand); color: var(--tekst); padding: 11px 20px;
   border-radius: 999px; font-size: 13px; display: none; z-index: 30; box-shadow: 0 6px 20px var(--schaduw); }
 .hint { font-size: 12px; color: var(--subtekst); margin-top: 34px; text-align: center;
   max-width: 440px; }
</style>
</head>
<body>
<header>
  <button class="iconbtn" onclick="terug()" title="Terug">&#8592;</button>
  <button class="iconbtn" onclick="ververs()" title="Verversen">&#8635;</button>
  <form class="addr" onsubmit="return ga()">
    <span class="lock">&#128269;</span>
    <input id="url" placeholder="Zoek of typ een webadres" autocomplete="off" spellcheck="false">
  </form>
  <button class="iconbtn" onclick="sla()" title="Bladwijzer">&#9733;</button>
  <button class="iconbtn" onclick="aiPanel()" title="AI-assistent">&#129302;</button>
  <button class="iconbtn" onclick="thema()" title="Licht/donker">&#9788;</button>
  <button class="iconbtn" onclick="menu()" title="Menu">&#9776;</button>
</header>
<div id="loader"></div>

<div id="content">
  <div id="start">
    <div class="logo">New<b>l</b>y</div>
    <form class="zoek" onsubmit="return ga()">
      <input id="url2" placeholder="Zoek op het web of typ een adres" autocomplete="off" spellcheck="false">
      <button type="submit">Ga</button>
    </form>
    <div id="results"></div>
    <div class="tegels" id="tegels"></div>
    <div class="hint">Jouw eigen browser op de Pi. Tegels verschijnen op basis van wat je vaak bezoekt.</div>
  </div>
  <iframe id="frame"></iframe>
</div>

<div id="panel"></div>
<div id="ai"></div>
<div id="toast"></div>

<script>
var token = localStorage.getItem('zelfsync_token') || '';
var huidig = '';
var stack = [];
var mode = localStorage.getItem('nieuwly_mode') || 'volledig';
var themaStand = localStorage.getItem('nieuwly_thema') || (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'licht' : 'donker');

function zetThema() {
  document.body.className = (themaStand === 'licht') ? 'licht' : '';
  localStorage.setItem('nieuwly_thema', themaStand);
}
function thema() {
  themaStand = (themaStand === 'licht') ? 'donker' : 'licht';
  zetThema();
}
zetThema();

function isUrl(v) {
  if (/^https?:\\/\\//i.test(v)) return true;
  if (/^about:/i.test(v)) return true;
  if (/\\s/.test(v)) return false;
  return /^[a-z0-9-]+(\\.[a-z0-9-]+)+(:\\d+)?([\\/?#].*)?$/i.test(v);
}

function laadTegels() {
  var w = document.getElementById('tegels');
  w.innerHTML = '';
  if (!token) {
    var d1 = document.createElement('div');
    d1.className = 'hint';
    d1.textContent = 'Tegels met je favoriete sites verschijnen hier als je ingelogd bent en vaker surft.';
    w.appendChild(d1);
    return;
  }
  fetch('/history?limit=200', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var telling = {};
      (d.history || []).forEach(function (h) {
        try { var dom = new URL(h.url).hostname.replace(/^www\\./, ''); if (dom) telling[dom] = (telling[dom] || 0) + 1; } catch (e) {}
      });
      var top = Object.keys(telling).sort(function (a, b) { return telling[b] - telling[a]; }).slice(0, 6);
      if (!top.length) {
        var d2 = document.createElement('div');
        d2.className = 'hint';
        d2.textContent = 'Bezoek sites en de sites waar je vaak komt verschijnen hier vanzelf.';
        w.appendChild(d2);
        return;
      }
      top.forEach(function (dom) {
        var t = document.createElement('div');
        t.className = 'tegel';
        var img = document.createElement('img');
        img.src = 'https://icons.duckduckgo.com/ip3/' + dom + '.ico';
        var nm = document.createElement('div');
        nm.className = 'nm';
        nm.textContent = dom;
        t.appendChild(img); t.appendChild(nm);
        t.onclick = function () { openB('https://' + dom); };
        w.appendChild(t);
      });
    });
}

function toonResultaten(q) {
  var r = document.getElementById('results');
  document.getElementById('tegels').style.display = 'none';
  document.getElementById('start').style.display = 'flex';
  document.getElementById('frame').style.display = 'none';
  r.style.display = 'block';
  r.innerHTML = '';
  var h = document.createElement('h2');
  h.textContent = 'Zoekresultaten voor ' + q;
  r.appendChild(h);
  var l = document.getElementById('loader');
  l.style.width = '70%';
  fetch('/search?q=' + encodeURIComponent(q))
    .then(function (res) { return res.json(); })
    .then(function (d) {
      l.style.width = '100%';
      setTimeout(function () { l.style.width = '0%'; }, 350);
      var items = d.results || [];
      if (d.error || !items.length) {
        var e = document.createElement('div');
        e.className = 'hint';
        e.textContent = d.error || 'Geen resultaten gevonden.';
        r.appendChild(e);
        return;
      }
      items.forEach(function (it) {
        var box = document.createElement('div');
        box.className = 'res';
        var a = document.createElement('a');
        a.href = '#';
        a.textContent = it.title || it.url;
        a.onclick = function () { openB(it.url); return false; };
        var u = document.createElement('div');
        u.className = 'url';
        u.textContent = it.url;
        var s = document.createElement('div');
        s.className = 'snip';
        s.textContent = it.snippet || '';
        box.appendChild(a); box.appendChild(u);
        if (it.snippet) box.appendChild(s);
        r.appendChild(box);
      });
    })
    .catch(function () { l.style.width = '0%'; });
}

function laad(v) {
  if (v.indexOf('http') !== 0) v = 'https://' + v;
  huidig = v;
  document.getElementById('results').style.display = 'none';
  document.getElementById('tegels').style.display = 'grid';
  document.getElementById('url').value = v;
  document.getElementById('url2').value = v;
  document.getElementById('start').style.display = 'none';
  var f = document.getElementById('frame');
  if (mode === 'volledig') {
    f.setAttribute('sandbox', 'allow-scripts allow-forms allow-popups allow-downloads');
  } else {
    f.setAttribute('sandbox', 'allow-same-origin allow-forms');
  }
  f.style.display = 'block';
  f.src = '/browse?url=' + encodeURIComponent(v) + '&mode=' + encodeURIComponent(mode);
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
  if (!isUrl(v)) { toonResultaten(v); return false; }
  if (huidig && stack[stack.length - 1] !== huidig) stack.push(huidig);
  laad(v);
  return false;
}

function openB(u) {
  if (huidig) stack.push(huidig);
  laad(u);
}

function terug() {
  if (document.getElementById('results').style.display === 'block') { naarStart(); return; }
  if (!stack.length) { naarStart(); return; }
  laad(stack.pop());
}

function ververs() { if (huidig) laad(huidig); }

function naarStart() {
  document.getElementById('frame').style.display = 'none';
  document.getElementById('start').style.display = 'flex';
  document.getElementById('results').style.display = 'none';
  document.getElementById('tegels').style.display = 'grid';
  laadTegels();
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

function sluitPanelen() {
  document.getElementById('panel').style.display = 'none';
  document.getElementById('ai').style.display = 'none';
}

function menu() {
  var p = document.getElementById('panel');
  var ai = document.getElementById('ai');
  ai.style.display = 'none';
  if (p.style.display === 'block') { p.style.display = 'none'; return; }
  p.style.display = 'block';
  var kop = '<h3>Menu</h3>' +
    '<div class="keuze">Weergave</div>' +
    '<button class="sub' + (mode === 'volledig' ? ' blauw' : '') + '" onclick="setMode(&quot;volledig&quot;)">Volledig (JavaScript aan)</button>' +
    '<button class="sub' + (mode === 'veilig' ? ' blauw' : '') + '" onclick="setMode(&quot;veilig&quot;)">Veilig (tekst, geen JS)</button>';
  if (token) { laadBladwijzers(p, kop); } else { laadLogin(p, kop); }
}

function setMode(m) {
  mode = m;
  localStorage.setItem('nieuwly_mode', m);
  menu();
  toast(m === 'volledig' ? 'Volledige weergave aan' : 'Veilige weergave aan');
  if (huidig) laad(huidig);
}

function laadLogin(p, kop) {
  p.innerHTML = kop +
    '<div class="keuze">Account</div>' +
    '<input id="u" placeholder="Gebruikersnaam">' +
    '<input id="p" type="password" placeholder="Wachtwoord (min. 8 tekens)">' +
    '<button class="sub blauw" onclick="stuur(&quot;register&quot;)">Account maken</button>' +
    '<button class="sub" onclick="stuur(&quot;login&quot;)">Inloggen</button>';
}

function laadBladwijzers(p, kop) {
  p.innerHTML = kop + '<div class="keuze">Bladwijzers</div><div id="lijst">Laden...</div>' +
    '<div class="keuze">Geschiedenis</div><div id="hist"></div>' +
    '<button class="sub" onclick="uitloggen()" style="margin-top:12px">Uitloggen</button>';
  fetch('/bookmarks', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var lijst = document.getElementById('lijst');
      lijst.innerHTML = '';
      var items = d.bookmarks || [];
      if (!items.length) { lijst.innerHTML = '<div class="keuze">Nog geen bladwijzers. Gebruik de ster op een pagina.</div>'; }
      items.forEach(function (b) {
        var a = document.createElement('a');
        a.href = '#';
        a.textContent = b.title || b.url;
        a.onclick = function () { p.style.display = 'none'; openB(b.url); return false; };
        lijst.appendChild(a);
      });
    });
  fetch('/history?limit=15', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var h = document.getElementById('hist');
      h.innerHTML = '';
      (d.history || []).forEach(function (b) {
        var a = document.createElement('a');
        a.href = '#';
        a.textContent = b.url;
        a.onclick = function () { p.style.display = 'none'; openB(b.url); return false; };
        h.appendChild(a);
      });
    });
}

function uitloggen() {
  token = '';
  localStorage.removeItem('zelfsync_token');
  document.getElementById('panel').style.display = 'none';
  toast('Uitgelogd');
  laadTegels();
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
        menu();
        laadTegels();
      } else { toast(d.error || 'Mislukt'); }
    });
}

function aiPanel() {
  var ai = document.getElementById('ai');
  var p = document.getElementById('panel');
  p.style.display = 'none';
  if (ai.style.display === 'block') { ai.style.display = 'none'; return; }
  ai.style.display = 'block';
  fetch('/ai-status').then(function (r) { return r.json(); }).then(function (d) {
    if (d.key_set) {
      ai.innerHTML = '<h3>AI-assistent</h3>' +
        '<textarea id="prompt" rows="3" placeholder="Vraag iets over de huidige pagina of iets anders..."></textarea>' +
        '<button class="sub blauw" onclick="vraagAI()">Vraag</button>' +
        '<div id="antwoord"></div>';
    } else {
      ai.innerHTML = '<h3>AI instellen</h3>' +
        '<div class="keuze">Plak je Mistral API-sleutel (console.mistral.ai). De sleutel wordt opgeslagen op jouw Pi.</div>' +
        '<input id="sleutel" type="password" placeholder="API-sleutel">' +
        '<button class="sub blauw" onclick="slaSleutel()">Opslaan</button>';
    }
  });
}

function slaSleutel() {
  var k = document.getElementById('sleutel').value.trim();
  if (!k) return;
  fetch('/api-key', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: k }) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      toast(d.error || 'Sleutel opgeslagen');
      aiPanel();
    });
}

function vraagAI() {
  var pr = document.getElementById('prompt').value.trim();
  if (!pr) return;
  var uit = document.getElementById('antwoord');
  uit.textContent = 'Denkt na...';
  fetch('/ask', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: pr, url: huidig || '' }) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      uit.textContent = d.answer || d.error || 'Geen antwoord.';
    })
    .catch(function () { uit.textContent = 'Fout bij het vragen.'; });
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

laadTegels();
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


def haal_pagina(url, limiet=MAX_PAGE):
    """Pagina ophalen (gzip, tekencodering)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,text/plain,*/*;q=0.5",
        "Accept-Encoding": "gzip",
        "Accept-Language": "nl,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read(limiet)
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
    return text, final_url, ctype


LEEG_BANNER = (
    '<div style="font-family:system-ui,sans-serif;background:#fff7ed;color:#7c4a03;'
    'padding:16px;border-bottom:1px solid #fcd9a8;font-size:14px">'
    'Deze site draait vrijwel volledig op JavaScript. Zet de weergave op '
    '&quot;Volledig&quot; in het Newly-menu, dan werkt deze site meestal wél.</div>')


def proxy_page(target, mode="volledig"):
    """Pagina ophalen en toonbaar maken binnen onze browser.

    volledig: JavaScript laten staan; de iframe-sandbox van de UI isoleert de site.
    veilig:   JavaScript verwijderen; veilige tekstweergave.
    """
    text, final_url, ctype = haal_pagina(target)
    is_html = "html" in ctype.lower() or "<html" in text.lower()[:4000]
    if not is_html:
        return ("<html><head><title>" + html.escape(target) + "</title></head>"
                "<body style='font-family:system-ui,sans-serif'><pre>"
                + html.escape(text) + "</pre></body></html>")

    if mode == "veilig":
        text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", text)
        text = re.sub(r"(?is)<script\b[^>]*/>", "", text)
        text = re.sub(r"(?is)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text)
        text = re.sub(r"(?is)<meta[^>]+http-equiv=[\"']refresh[\"'][^>]*>", "", text)

    mb = re.search(r"(?is)<base[^>]+href=[\"']([^\"']+)[\"']", text)
    base = urllib.parse.urljoin(final_url, mb.group(1)) if mb else final_url
    if mb:
        text = text.replace(mb.group(0), "")

    def rewrite(m):
        v = m.group(1)
        if v.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            return m.group(0)
        absolute = urllib.parse.urljoin(base, v)
        if absolute.startswith(("http://", "https://")):
            return ('href="/browse?url=' + urllib.parse.quote(absolute, safe="")
                    + '&amp;mode=' + mode + '"')
        return m.group(0)
    text = re.sub(r"(?is)href=[\"']([^\"']+)[\"']", rewrite, text)

    inject = '<base href="' + html.escape(base) + '">'
    if re.search(r"(?is)<head[^>]*>", text):
        text = re.sub(r"(?is)(<head[^>]*>)", lambda m: m.group(1) + inject, text, count=1)
    else:
        text = inject + text

    if mode == "veilig":
        zonder_tags = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", text)
        zonder_tags = re.sub(r"(?is)<[^>]+>", " ", zonder_tags)
        if len(re.sub(r"\s+", "", zonder_tags)) < 200:
            text = LEEG_BANNER + text
    return text


def ddg_zoek(zoekterm):
    """Echte zoekresultaten via DuckDuckGo (HTML-versie, opgehaald door de Pi)."""
    results = []
    for endpoint in ("https://html.duckduckgo.com/html/?q=",
                     "https://lite.duckduckgo.com/lite/?q="):
        try:
            text, _, _ = haal_pagina(endpoint + urllib.parse.quote_plus(zoekterm))
        except Exception:
            continue
        titels = re.findall(
            r'(?is)<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text)
        for href, titel in titels:
            if "uddg=" in href:
                echte = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
            else:
                echte = href
            if not echte.startswith(("http://", "https://")):
                continue
            t = re.sub(r"(?is)<[^>]+>", "", titel).strip()
            if t and echte not in [r["url"] for r in results]:
                results.append({"title": t[:200], "url": echte, "snippet": ""})
        snippets = re.findall(
            r'(?is)<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', text)
        for i, snip in enumerate(snippets):
            if i < len(results) and not results[i]["snippet"]:
                results[i]["snippet"] = re.sub(r"(?is)<[^>]+>", "", snip).strip()[:300]
        if results:
            break
    return results[:15]


def pagina_tekst(url, limiet=8000):
    """Zichtbare tekst van een pagina, voor AI-context."""
    text, _, ctype = haal_pagina(url)
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limiet]


def lees_api_key():
    try:
        return KEY_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ai_vraag(prompt, page_url):
    key = lees_api_key()
    if not key:
        return {"error": "Nog geen API-sleutel ingesteld (menu > AI)"}
    messages = [{"role": "system",
                 "content": "Je bent de AI-assistent van de Newly-browser. "
                            "Antwoord kort en in de taal van de gebruiker."}]
    if page_url:
        try:
            context = pagina_tekst(page_url)
            if context:
                messages.append({"role": "system",
                                 "content": "Context van de huidige pagina:" + context})
        except Exception:
            pass
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"model": LLM_MODEL, "messages": messages}).encode()
    req = urllib.request.Request("https://api.mistral.ai/v1/chat/completions",
                                 data=body, method="POST", headers={
                                     "Content-Type": "application/json",
                                     "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return {"answer": data["choices"][0]["message"]["content"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "ZelfSync/0.5"

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
        data = body.encode("utf-8", "replace")
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
            self.send_html(200, INDEX_HTML)
            return
        if self.path.startswith("/browse"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            target = (params.get("url") or [""])[0]
            mode = (params.get("mode") or ["volledig"])[0]
            if mode not in ("volledig", "veilig"):
                mode = "volledig"
            if not target.startswith(("http://", "https://")):
                self.send_html(400,
                               "<h3 style='font-family:system-ui'>Ongeldig adres</h3>"
                               "<p><a href='/'>Terug naar Newly</a></p>")
                return
            try:
                if mode == "veilig":
                    self.send_html(200, proxy_page(target, "veilig"),
                                   csp="script-src 'none'; object-src 'none'; "
                                       "frame-src 'none'; frame-ancestors 'self'")
                else:
                    self.send_html(200, proxy_page(target, "volledig"),
                                   csp="frame-ancestors 'self'")
            except Exception as exc:
                self.send_html(502,
                    "<div style='font-family:system-ui;max-width:560px;margin:60px auto'>"
                    "<h2>Pagina kon niet worden geladen</h2><p style='color:#666'>"
                    + html.escape(str(exc)) + "</p>"
                    "<p><a href='/'>Terug naar Newly</a></p></div>",
                    csp="script-src 'none'")
            return
        if self.path.startswith("/search"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            q = (params.get("q") or [""])[0].strip()
            if not q:
                self.send_json(400, {"error": "lege zoekterm"})
                return
            try:
                self.send_json(200, {"results": ddg_zoek(q)})
            except Exception as exc:
                self.send_json(502, {"error": "Zoeken mislukt: " + str(exc)})
            return
        if self.path == "/ai-status":
            self.send_json(200, {"key_set": bool(lees_api_key())})
            return

        con = connect()
        try:
            if self.path == "/health":
                self.send_json(200, {"status": "ok", "server": "zelfsync", "version": "0.5"})
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
            if path == "/api-key":
                key = str(body.get("key", "")).strip()
                if len(key) < 10:
                    self.send_json(400, {"error": "dat lijkt geen geldige sleutel"})
                    return
                KEY_PATH.write_text(key, encoding="utf-8")
                try:
                    KEY_PATH.chmod(0o600)
                except OSError:
                    pass
                self.send_json(200, {"ok": True})
                return
            if path == "/ask":
                prompt = str(body.get("prompt", ""))[:4000]
                if not prompt:
                    self.send_json(400, {"error": "lege vraag"})
                    return
                try:
                    self.send_json(200, ai_vraag(prompt, str(body.get("url", ""))))
                except urllib.error.HTTPError as exc:
                    self.send_json(502, {"error": "LLM-api gaf fout " + str(exc.code)
                                               + " (controleer je API-sleutel)"})
                except Exception as exc:
                    self.send_json(502, {"error": str(exc)})
                return
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
