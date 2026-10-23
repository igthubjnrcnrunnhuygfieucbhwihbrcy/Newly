#!/usr/bin/env python3
"""ZelfSync + Newly browser-in-browser (Raspberry Pi 5). Versie 0.9.

Taken:
1. Sync-server: accounts, bladwijzers, geschiedenis (SQLite).
2. Browser-in-browser op http://pi-adres:8765/ :
   - Tabbladen, terug/vooruit, volledige en veilige weergave
   - Nieuwsearch: de eigen zoekmachine van Newly (eigen index op de Pi,
     bladwijzers/geschiedenis, Wikipedia nl, webadres-radiging)
   - AI-assistent via je eigen Mistral API-sleutel, opgeslagen op de Pi
3. Volledige proxy-engine: ALLE bronnen lopen via de Pi, met ABSOLUUT
   herschreven adressen (http://pi:8765/browse?...). Relatieve paden
   werden door de <base>-tag van de site verkeerd opgelost - dat was de
   oorzaak van dode links, kapotte css en formulieren.
4. Ingebouwde advertentieblokkering op de Pi zelf.
5. Knop "Echte browser": echte Chromium op de Pi via schermdeling
   (poort 6080, zie install-pi.sh). Daar werkt alles.

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
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "zelfsync.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
KEY_PATH = DB_PATH.parent / "data" / "apikey.txt"
MAX_BODY = 1_000_000
MAX_PAGE = 6 * 1024 * 1024
PORT = int(os.environ.get("ZELFSYNC_PORT", "8765"))
LLM_MODEL = os.environ.get("LLM_MODEL", "mistral-small-latest")
UA_STR = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 NewlyBrowser/0.9")

INDEX_HTML = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Newly</title>
<link rel="icon" href="data:,">
<style>
 :root { --bg:#f4f7fb; --tekst:#182430; --balk:rgba(255,255,255,.93); --rand:#e2e9f1;
   --vlak:#ffffff; --vlak2:#eef2f8; --invoer:#eef2f8; --subtekst:#5c6c81; --accent:#2f63e8;
   --schaduw:rgba(20,40,80,.13); --fout:#b91c1c; }
 body.donker { --bg:#0e131a; --tekst:#e8edf4; --balk:rgba(14,19,26,.94); --rand:#232d3a;
   --vlak:#151d28; --vlak2:#1c2532; --invoer:#1c2532; --subtekst:#a6b4c6; --accent:#5b8dff;
   --schaduw:rgba(0,0,0,.5); --fout:#f87171; }
 * { box-sizing: border-box; }
 body { margin: 0; font-family: -apple-system, 'Segoe UI', Roboto, system-ui, sans-serif;
   background: var(--bg); color: var(--tekst); font-size: 15px; }
 header { display: flex; gap: 4px; align-items: center; height: 54px; padding: 0 10px;
   background: var(--balk); backdrop-filter: blur(12px); border-bottom: 1px solid var(--rand); }
 .iconbtn { width: 38px; height: 38px; border-radius: 10px; border: 0; background: transparent;
   color: var(--tekst); font-size: 17px; cursor: pointer; display: flex; align-items: center;
   justify-content: center; flex: none; transition: background .15s; }
 .iconbtn:hover { background: var(--vlak2); }
 .addr { flex: 1; display: flex; align-items: center; background: var(--invoer);
   border: 1px solid var(--rand); border-radius: 999px; padding: 0 14px; min-width: 0;
   transition: border-color .15s; }
 .addr:focus-within { border-color: var(--accent); }
 .addr input { flex: 1; background: transparent; border: 0; outline: none; color: var(--tekst);
   font-size: 15px; padding: 10px 0; min-width: 0; }
 .addr .z { color: var(--subtekst); font-size: 12px; margin-right: 8px; flex: none; }
 .tabbar { display: flex; align-items: flex-end; gap: 4px; height: 42px; padding: 6px 10px 0;
   background: var(--balk); border-bottom: 1px solid var(--rand); }
 #tablijst { display: flex; align-items: flex-end; gap: 4px; overflow-x: auto; flex: 1; }
 .tab { display: flex; align-items: center; gap: 8px; padding: 8px 10px; cursor: pointer;
   max-width: 220px; min-width: 130px; border-radius: 10px 10px 0 0; border: 1px solid transparent;
   border-bottom: 0; background: transparent; }
 .tab.actief { background: var(--bg); border-color: var(--rand); }
 .tab .tnm { font-size: 13px; color: var(--subtekst); overflow: hidden; text-overflow: ellipsis;
   white-space: nowrap; flex: 1; }
 .tab.actief .tnm { color: var(--tekst); font-weight: 600; }
 .tab .tx { font-size: 13px; color: var(--subtekst); width: 20px; height: 20px; flex: none;
   border-radius: 50%; display: flex; align-items: center; justify-content: center; }
 .tab .tx:hover { background: var(--vlak2); color: var(--fout); }
 .plus { width: 30px; height: 30px; margin: 0 4px 6px; border-radius: 8px; border: 0;
   background: transparent; color: var(--subtekst); font-size: 18px; cursor: pointer; flex: none; }
 .plus:hover { background: var(--vlak2); color: var(--tekst); }
 #loader { height: 2px; background: var(--accent); width: 0%; transition: width .4s; }
 #content { position: relative; height: calc(100vh - 100px); }
 #content iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0;
   background: #fff; }
 #start { position: absolute; inset: 0; overflow: auto; display: flex; flex-direction: column;
   align-items: center; padding: 48px 20px 30px; }
 .logo { font-size: 38px; font-weight: 800; letter-spacing: -.5px; }
 .logo b { color: var(--accent); font-weight: 800; }
 .zoek { display: flex; width: 100%; max-width: 600px; margin: 24px 0 10px; background: var(--vlak);
   border: 1px solid var(--rand); border-radius: 999px; padding: 5px;
   box-shadow: 0 2px 16px var(--schaduw); }
 .zoek input { flex: 1; background: transparent; border: 0; outline: none; color: var(--tekst);
   font-size: 16px; padding: 11px 20px; min-width: 0; }
 .zoek button { background: var(--accent); border: 0; border-radius: 999px; color: #fff;
   padding: 11px 26px; font-size: 15px; font-weight: 600; cursor: pointer; flex: none; }
 .zoek button:hover { filter: brightness(1.08); }
 #results { display: none; width: 100%; max-width: 660px; text-align: left; margin-top: 14px; }
 #results h2 { font-size: 14px; font-weight: 600; color: var(--subtekst); margin: 0 0 6px; }
 .res { padding: 13px 4px; border-bottom: 1px solid var(--rand); }
 .res a { color: var(--tekst); font-size: 16px; font-weight: 500; text-decoration: none; }
 .res a:hover { color: var(--accent); }
 .res .url { color: #1a7f37; font-size: 12.5px; margin: 3px 0; word-break: break-all; }
 body.donker .res .url { color: #6ecf8e; }
 .res .snip { color: var(--subtekst); font-size: 13.5px; line-height: 1.5; }
 .chip { display: inline-block; font-size: 11px; color: var(--accent); background: var(--vlak2);
   border-radius: 999px; padding: 2px 9px; margin-left: 8px; vertical-align: middle; }
 .tegels { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
   gap: 14px; width: 100%; max-width: 560px; margin-top: 26px; }
 .tegel { background: var(--vlak); border: 1px solid var(--rand); border-radius: 16px;
   padding: 18px 10px; text-align: center; cursor: pointer; transition: .15s; }
 .tegel:hover { transform: translateY(-2px); border-color: var(--accent); }
 .tegel img { width: 30px; height: 30px; border-radius: 8px; margin-bottom: 8px; }
 .tegel .nm { font-size: 13px; color: var(--subtekst); word-break: break-all; }
 #panel, #ai { position: fixed; top: 106px; right: 12px; width: min(92vw, 360px);
   background: var(--vlak); border: 1px solid var(--rand); border-radius: 16px; padding: 18px;
   display: none; z-index: 20; box-shadow: 0 14px 40px var(--schaduw); }
 #panel h3, #ai h3 { margin: 0 0 12px; font-size: 15px; }
 #panel input, #ai input, #ai textarea { width: 100%; background: var(--invoer);
   border: 1px solid var(--rand); border-radius: 10px; color: var(--tekst); padding: 11px;
   margin-bottom: 8px; outline: none; font-size: 14px; font-family: inherit; }
 .sub { background: var(--vlak2); color: var(--tekst); border: 1px solid var(--rand);
   border-radius: 10px; padding: 10px 14px; cursor: pointer; font-size: 13px; margin: 4px 4px 8px 0; }
 .sub.blauw { background: var(--accent); color: #fff; border-color: transparent; }
 #panel a { color: var(--accent); display: block; padding: 7px 0; font-size: 14px;
   text-decoration: none; border-bottom: 1px solid var(--rand); word-break: break-all; }
 .keuze { font-size: 13px; color: var(--subtekst); margin: 10px 0 6px; }
 #antwoord { font-size: 14px; line-height: 1.55; white-space: pre-wrap; color: var(--tekst);
   margin-top: 8px; }
 #toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
   background: var(--vlak); border: 1px solid var(--rand); color: var(--tekst); padding: 11px 22px;
   border-radius: 999px; font-size: 13px; display: none; z-index: 30;
   box-shadow: 0 6px 22px var(--schaduw); }
 .hint { font-size: 12.5px; color: var(--subtekst); margin-top: 30px; text-align: center;
   max-width: 460px; line-height: 1.5; }
 @media (max-width: 700px) {
   .iconbtn { width: 33px; height: 33px; font-size: 15px; }
   .iconbtn.vw, .iconbtn.th { display: none; }
   .tab { min-width: 92px; max-width: 150px; }
   .tab .tnm { font-size: 12px; }
   .plus { margin-bottom: 4px; }
   #start { padding: 26px 14px 20px; }
   .logo { font-size: 30px; }
   #panel, #ai { left: 8px; right: 8px; width: auto; top: 100px; }
   .hint { margin-top: 20px; }
 }
</style>
</head>
<body>
<header>
  <button class="iconbtn" onclick="terug()" title="Terug">&#8592;</button>
  <button class="iconbtn vw" onclick="vooruit()" title="Vooruit">&#8594;</button>
  <button class="iconbtn" onclick="ververs()" title="Verversen">&#8635;</button>
  <button class="iconbtn" onclick="naarStart()" title="Startpagina">&#8962;</button>
  <form class="addr" onsubmit="return ga()">
    <span class="z">&#128269;</span>
    <input id="url" placeholder="Zoek of typ een webadres" autocomplete="off" spellcheck="false">
  </form>
  <button class="iconbtn" onclick="sla()" title="Bladwijzer (Ctrl+D)">&#9733;</button>
  <button class="iconbtn" onclick="openDirect()" title="Openen buiten Newly">&#8599;</button>
  <button class="iconbtn" onclick="echteModus()" title="Echte browser op de Pi: video, inloggen, alles werkt daar">&#128250;</button>
  <button class="iconbtn" onclick="aiPanel()" title="AI-assistent">&#129302;</button>
  <button class="iconbtn th" onclick="thema()" title="Licht/donker">&#9788;</button>
  <button class="iconbtn" onclick="menu()" title="Menu">&#9776;</button>
</header>
<div class="tabbar">
  <div id="tablijst"></div>
  <button class="plus" onclick="nieuwTab()" title="Nieuw tabblad (Ctrl+T)">&#65291;</button>
</div>
<div id="loader"></div>

<div id="content">
  <div id="start">
    <div class="logo">New<b>l</b>y</div>
    <form class="zoek" onsubmit="return ga2()">
      <input id="url2" placeholder="Zoek op het web of typ een adres" autocomplete="off" spellcheck="false">
      <button type="submit">Ga</button>
    </form>
    <div id="results"></div>
    <div class="tegels" id="tegels"></div>
    <div class="hint">Jouw eigen browser, op jouw eigen Pi.<br>Nieuwsearch zoekt in je eigen index en in Wikipedia. De Tv-knop hierboven opent de echte Chromium op de Pi: daar werkt alles, ook video.</div>
  </div>
</div>

<div id="panel"></div>
<div id="ai"></div>
<div id="toast"></div>

<script>
var token = localStorage.getItem('zelfsync_token') || '';
var mode = localStorage.getItem('nieuwly_mode') || 'volledig';
var themaStand = localStorage.getItem('nieuwly_thema') || 'licht';
var tabs = [];
var actief = 0;

function tab() { return tabs[actief]; }

function zetThema() {
  document.body.className = (themaStand === 'donker') ? 'donker' : '';
  localStorage.setItem('nieuwly_thema', themaStand);
}
function thema() { themaStand = (themaStand === 'donker') ? 'licht' : 'donker'; zetThema(); }
zetThema();

function isUrl(v) {
  if (/^https?:\\/\\//i.test(v)) return true;
  if (/^about:/i.test(v)) return true;
  if (/\\s/.test(v)) return false;
  return /^[a-z0-9-]+(\\.[a-z0-9-]+)+(:\\d+)?([\\/?#].*)?$/i.test(v);
}

function hostnaam(u) {
  try { return new URL(u).hostname.replace(/^www\\./, ''); } catch (e) { return u; }
}

function zandbak(f) {
  f.setAttribute('sandbox', mode === 'volledig'
    ? 'allow-scripts allow-forms allow-popups allow-downloads'
    : 'allow-same-origin allow-forms allow-popups');
}

function maakFrame() {
  var f = document.createElement('iframe');
  f.style.display = 'none';
  zandbak(f);
  f.addEventListener('load', function () {
    klaar();
    for (var j = 0; j < tabs.length; j++) {
      if (tabs[j].frame === f) {
        try {
          var t = f.contentWindow.document.title;
          if (t) { tabs[j].titel = t; renderTabs(); }
        } catch (e) {}
        break;
      }
    }
  });
  document.getElementById('content').appendChild(f);
  return f;
}

function nieuwTab(url) {
  var t = { url: '', titel: 'Nieuw tabblad', stack: [], sidx: -1, frame: maakFrame() };
  tabs.push(t);
  zetTab(tabs.length - 1);
  if (url) gaNaar(url, true);
}

function sluitTab(i) {
  if (tabs.length === 1) { naarStart(); return; }
  var f = tabs[i].frame;
  if (f.parentNode) f.parentNode.removeChild(f);
  tabs.splice(i, 1);
  if (actief >= i && actief > 0) actief--;
  zetTab(Math.min(actief, tabs.length - 1));
}

function zetTab(i) {
  actief = i;
  sluitPanelen();
  for (var j = 0; j < tabs.length; j++) tabs[j].frame.style.display = 'none';
  var t = tab();
  if (t.url) { t.frame.style.display = 'block'; }
  else { document.getElementById('start').style.display = 'flex'; }
  document.getElementById('url').value = t.url || '';
  renderTabs();
}

function renderTabs() {
  var lijst = document.getElementById('tablijst');
  lijst.innerHTML = '';
  tabs.forEach(function (t, i) {
    var d = document.createElement('div');
    d.className = 'tab' + (i === actief ? ' actief' : '');
    d.title = t.url || 'Nieuw tabblad';
    var nm = document.createElement('span');
    nm.className = 'tnm';
    nm.textContent = t.titel || 'Nieuw tabblad';
    var x = document.createElement('span');
    x.className = 'tx';
    x.innerHTML = '&#10005;';
    x.title = 'Tabblad sluiten';
    x.onclick = function (ev) { ev.stopPropagation(); sluitTab(i); };
    d.appendChild(nm); d.appendChild(x);
    d.onclick = function () { zetTab(i); };
    lijst.appendChild(d);
  });
}

function gaNaar(v, nieuw) {
  var t = tab();
  if (v.indexOf('http') !== 0) v = 'https://' + v;
  if (nieuw !== false) {
    t.stack = t.stack.slice(0, t.sidx + 1);
    t.stack.push(v);
    t.sidx = t.stack.length - 1;
  }
  t.url = v;
  t.titel = hostnaam(v);
  laadPagina();
}

function laadPagina() {
  var t = tab();
  document.getElementById('results').style.display = 'none';
  document.getElementById('tegels').style.display = 'grid';
  document.getElementById('start').style.display = 'none';
  document.getElementById('url').value = t.url;
  t.frame.style.display = 'block';
  t.frame.src = '/browse?url=' + encodeURIComponent(t.url) + '&mode=' + encodeURIComponent(mode);
  document.title = t.titel;
  renderTabs();
  laadbalk();
  if (token) {
    fetch('/history', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ url: t.url, title: t.titel }) }).catch(function () {});
  }
}

function ga() {
  var v = document.getElementById('url').value.trim();
  if (!v) return false;
  if (!isUrl(v)) { toonResultaten(v); return false; }
  gaNaar(v, true);
  document.getElementById('url').blur();
  return false;
}

function ga2() {
  var v = document.getElementById('url2').value.trim();
  if (!v) return false;
  if (!isUrl(v)) { toonResultaten(v); return false; }
  gaNaar(v, true);
  return false;
}

function naarStart() {
  var t = tab();
  t.url = '';
  t.titel = 'Nieuw tabblad';
  t.frame.style.display = 'none';
  document.getElementById('start').style.display = 'flex';
  document.getElementById('results').style.display = 'none';
  document.getElementById('tegels').style.display = 'grid';
  document.getElementById('url').value = '';
  document.title = 'Newly';
  laadTegels();
  renderTabs();
}

function resultsZichtbaar() { return document.getElementById('results').style.display === 'block'; }

function terug() {
  var t = tab();
  if (!t.url && t.sidx >= 0) { gaNaar(t.stack[t.sidx], false); return; }
  if (t.sidx > 0) { t.sidx--; gaNaar(t.stack[t.sidx], false); return; }
  if (t.url) { naarStart(); return; }
  if (resultsZichtbaar()) { naarStart(); }
}

function vooruit() {
  var t = tab();
  if (t.sidx < t.stack.length - 1) { t.sidx++; gaNaar(t.stack[t.sidx], false); }
}

function ververs() {
  var t = tab();
  if (t.url) { laadbalk(); t.frame.src = t.frame.src; }
}

function openDirect() {
  var u = tab().url;
  if (u) window.open(u, '_blank');
  else toast('Open eerst een pagina.');
}

function echteModus() {
  var u = 'http://' + location.hostname + ':6080/vnc.html?autoconnect=true&resize=scale';
  window.open(u, '_blank');
}

function laadbalk() { document.getElementById('loader').style.width = '70%'; }
function klaar() {
  var l = document.getElementById('loader');
  l.style.width = '100%';
  setTimeout(function () { l.style.width = '0%'; }, 350);
}

function laadTegels() {
  var w = document.getElementById('tegels');
  w.innerHTML = '';
  if (!token) {
    var d1 = document.createElement('div');
    d1.className = 'hint';
    d1.textContent = 'Snelkoppelingen van sites waar je vaak komt, verschijnen hier als je een account maakt en vaker surft.';
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
      var top = Object.keys(telling).filter(function (k) { return telling[k] >= 3; })
        .sort(function (a, b) { return telling[b] - telling[a]; }).slice(0, 8);
      if (!top.length) {
        var d2 = document.createElement('div');
        d2.className = 'hint';
        d2.textContent = 'Kom vaker op een site en hij verschijnt hier vanzelf.';
        w.appendChild(d2);
        return;
      }
      top.forEach(function (dom) {
        var t = document.createElement('div');
        t.className = 'tegel';
        var img = document.createElement('img');
        img.src = '/favicon?u=' + encodeURIComponent(dom);
        img.onerror = function () { if (img.parentNode) img.parentNode.removeChild(img); };
        var nm = document.createElement('div');
        nm.className = 'nm';
        nm.textContent = dom;
        t.appendChild(img); t.appendChild(nm);
        t.onclick = function () { gaNaar('https://' + dom, true); };
        w.appendChild(t);
      });
    });
}

function toonResultaten(q) {
  var t = tab();
  if (t.url) t.url = '';
  t.frame.style.display = 'none';
  document.getElementById('start').style.display = 'flex';
  document.getElementById('tegels').style.display = 'none';
  var r = document.getElementById('results');
  r.style.display = 'block';
  r.innerHTML = '';
  var h = document.createElement('h2');
  h.textContent = 'Nieuwsearch-resultaten voor "' + q + '"';
  r.appendChild(h);
  laadbalk();
  var kop = token ? { 'Authorization': 'Bearer ' + token } : {};
  fetch('/search?q=' + encodeURIComponent(q), { headers: kop })
    .then(function (res) { return res.json(); })
    .then(function (d) {
      klaar();
      var items = d.results || [];
      if (d.error || !items.length) {
        var e = document.createElement('div');
        e.className = 'hint';
        e.textContent = d.error || 'Niets gevonden. Probeer een andere zoekterm of typ een volledig webadres.';
        r.appendChild(e);
        return;
      }
      items.forEach(function (it) {
        var box = document.createElement('div');
        box.className = 'res';
        var a = document.createElement('a');
        a.href = '#';
        a.textContent = it.title || it.url;
        if (it.bron) {
          var chip = document.createElement('span');
          chip.className = 'chip';
          chip.textContent = it.bron;
          a.appendChild(document.createTextNode(' '));
          a.appendChild(chip);
        }
        a.onclick = function () { gaNaar(it.url, true); return false; };
        var u = document.createElement('div');
        u.className = 'url';
        u.textContent = it.url;
        box.appendChild(a); box.appendChild(u);
        if (it.snippet) {
          var s = document.createElement('div');
          s.className = 'snip';
          s.textContent = it.snippet;
          box.appendChild(s);
        }
        r.appendChild(box);
      });
    })
    .catch(function () { klaar(); });
}

function sla() {
  var t = tab();
  if (!t.url) { toast('Ga eerst naar een pagina.'); return; }
  if (!token) { menu(); return; }
  fetch('/bookmarks', { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
    body: JSON.stringify({ url: t.url, title: t.titel || t.url }) })
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
    '<button class="sub' + (mode === 'veilig' ? ' blauw' : '') + '" onclick="setMode(&quot;veilig&quot;)">Veilig (zonder JavaScript)</button>' +
    '<div class="keuze">Advertentieblokkering: aan (ingebouwd)</div>' +
    '<div class="keuze">Tv-knop = echte Chromium op de Pi: voor video, inloggen en lastige sites</div>' +
    '<div class="keuze">Sneltoetsen: Ctrl+L adres, Ctrl+T nieuw tabblad, Ctrl+W sluiten, Ctrl+D bladwijzer</div>';
  if (token) { laadBladwijzers(p, kop); } else { laadLogin(p, kop); }
}

function setMode(m) {
  mode = m;
  localStorage.setItem('nieuwly_mode', m);
  tabs.forEach(function (t) { zandbak(t.frame); });
  menu();
  toast(m === 'volledig' ? 'Volledige weergave aan (JavaScript)' : 'Veilige weergave aan (zonder JavaScript)');
  if (tab().url) laadPagina();
}

function laadLogin(p, kop) {
  p.innerHTML = kop +
    '<div class="keuze">Account (voor bladwijzers, geschiedenis en snelkoppelingen)</div>' +
    '<input id="u" placeholder="Gebruikersnaam">' +
    '<input id="p" type="password" placeholder="Wachtwoord (min. 8 tekens)">' +
    '<button class="sub blauw" onclick="stuur(&quot;register&quot;)">Account maken</button>' +
    '<button class="sub" onclick="stuur(&quot;login&quot;)">Inloggen</button>';
}

function laadBladwijzers(p, kop) {
  p.innerHTML = kop + '<div class="keuze">Bladwijzers</div><div id="lijst">Laden...</div>' +
    '<div class="keuze">Recente geschiedenis</div><div id="hist"></div>' +
    '<button class="sub" onclick="uitloggen()" style="margin-top:12px">Uitloggen</button>';
  fetch('/bookmarks', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var lijst = document.getElementById('lijst');
      if (!lijst) return;
      lijst.innerHTML = '';
      var items = d.bookmarks || [];
      if (!items.length) { lijst.innerHTML = '<div class="keuze">Nog geen bladwijzers. Gebruik de ster op een pagina.</div>'; }
      items.forEach(function (b) {
        var a = document.createElement('a');
        a.href = '#';
        a.textContent = b.title || b.url;
        a.onclick = function () { p.style.display = 'none'; gaNaar(b.url, true); return false; };
        lijst.appendChild(a);
      });
    });
  fetch('/history?limit=15', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var h = document.getElementById('hist');
      if (!h) return;
      h.innerHTML = '';
      (d.history || []).forEach(function (b) {
        var a = document.createElement('a');
        a.href = '#';
        a.textContent = b.url;
        a.onclick = function () { p.style.display = 'none'; gaNaar(b.url, true); return false; };
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
        '<div class="keuze">Plak je Mistral API-sleutel (te halen op console.mistral.ai). De sleutel wordt alleen op jouw eigen Pi opgeslagen.</div>' +
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
    body: JSON.stringify({ prompt: pr, url: tab().url || '' }) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      uit.textContent = d.answer || d.error || 'Geen antwoord.';
    })
    .catch(function () { uit.textContent = 'Fout bij het vragen.'; });
}

document.addEventListener('keydown', function (e) {
  if (!(e.ctrlKey || e.metaKey)) return;
  var k = e.key.toLowerCase();
  if (k === 'l') { e.preventDefault(); var u = document.getElementById('url'); u.focus(); u.select(); }
  else if (k === 't') { e.preventDefault(); nieuwTab(); }
  else if (k === 'w') { e.preventDefault(); sluitTab(actief); }
  else if (k === 'd') { e.preventDefault(); sla(); }
});

nieuwTab();
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
        ");"
        "CREATE TABLE IF NOT EXISTS pages ("
        "  url TEXT PRIMARY KEY,"
        "  title TEXT NOT NULL DEFAULT '',"
        "  tekst TEXT NOT NULL DEFAULT '',"
        "  updated TEXT DEFAULT (datetime('now'))"
        ");")
    return con


def hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               bytes.fromhex(salt_hex), 120_000).hex()


# ---------- cookies (simpel, per domein, alleen in het geheugen) ----------
KOEKJES = {}
KOEK_LOCK = threading.Lock()

def koekjes_voor(host):
    if not host:
        return ""
    with KOEK_LOCK:
        items = KOEKJES.get(host, {})
    return "; ".join(k + "=" + v for k, v in items.items())

def koekjes_opslaan(host, headers):
    if not host or headers is None:
        return
    try:
        regels = headers.get_all("Set-Cookie") or []
    except AttributeError:
        regels = []
    for regel in regels:
        paar = regel.split(";")[0]
        if "=" not in paar:
            continue
        k, v = paar.split("=", 1)
        with KOEK_LOCK:
            KOEKJES.setdefault(host, {})[k.strip()] = v.strip()


def haal_bron(url, method="GET", body=None, content_type=None,
              limiet=MAX_PAGE, timeout=25, extra_headers=None):
    """Ruwe bytes van een bron ophalen (gzip, cookies, ook foutpagina's)."""
    host = urllib.parse.urlsplit(url).hostname or ""
    headers = {
        "User-Agent": UA_STR,
        "Accept": "*/*",
        "Accept-Encoding": "gzip",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    }
    koek = koekjes_voor(host)
    if koek:
        headers["Cookie"] = koek
    if body is not None:
        headers["Content-Type"] = content_type or "application/x-www-form-urlencoded"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        status = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as fout:
        # Een echte browser toont ook de inhoud van een 404/500-pagina.
        resp = fout
        status = fout.code
    try:
        raw = resp.read(limiet)
        final_url = resp.geturl()
        ctype = resp.headers.get("Content-Type", "application/octet-stream")
        if resp.headers.get("Content-Encoding", "").lower() == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        rheaders = {}
        try:
            for k, v in resp.headers.items():
                rheaders[k] = v
        except Exception:
            pass
        koekjes_opslaan(urllib.parse.urlsplit(final_url).hostname or host, resp.headers)
    finally:
        resp.close()
    return raw, final_url, ctype, int(status), rheaders


def als_tekst(raw, ctype):
    m = re.search(r"charset\s*=\s*['\"]?([\w.-]+)", ctype or "")
    enc = m.group(1) if m else "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def haal_pagina(url, limiet=MAX_PAGE, timeout=20):
    """Tekstversie van een bron (voor zoeken en AI-context)."""
    raw, final_url, ctype, status, _ = haal_bron(url, limiet=limiet, timeout=timeout)
    return als_tekst(raw, ctype), final_url, ctype, status


def zichtbare_tekst(text):
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text


def indexeer(url, pagina, status):
    """Bezochte pagina's opslaan in de eigen Nieuwsearch-index op de Pi."""
    if status >= 400 or not url.startswith(("http://", "https://")):
        return
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", pagina)
    titel = zichtbare_tekst(m.group(1))[:200] if m else ""
    tekst = zichtbare_tekst(pagina)
    if len(tekst) < 150:
        return
    con = connect()
    try:
        con.execute(
            "INSERT INTO pages (url, title, tekst, updated) VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(url) DO UPDATE SET title=excluded.title, tekst=excluded.tekst, "
            "updated=excluded.updated",
            (url, titel, tekst[:6000]))
        con.commit()
    finally:
        con.close()


LEEG_BANNER_TEMPLATE = (
    '<div style="font-family:system-ui,sans-serif;background:#fff7ed;color:#7c4a03;'
    'padding:16px;border-bottom:1px solid #fcd9a8;font-size:14px">'
    'Deze site draait vrijwel volledig op JavaScript. '
    '<a style="color:#b45309;font-weight:600" href="{basis}/browse?url={url}&amp;mode=volledig">'
    'Openen in volledige modus</a> werkt meestal wel, '
    'of gebruik de Tv-knop voor de echte browser.</div>')

FOUT_BANNER_TEMPLATE = (
    '<div style="font-family:system-ui,sans-serif;background:#fef2f2;color:#991b1b;'
    'padding:16px;border-bottom:1px solid #fecaca;font-size:14px">'
    'De site gaf een HTTP-{status}-foutmelding; hieronder zie je de foutpagina van de site zelf. '
    '<a style="color:#b91c1c;font-weight:600" href="{basis}/browse?url={url}&amp;mode=volledig">'
    'Opnieuw in volledige modus</a> of gebruik de Tv-knop voor de echte browser.</div>')

FOUT_PAGINA = (
    "<div style='font-family:system-ui,sans-serif;max-width:620px;margin:60px auto;padding:0 20px'>"
    "<h2 style='margin-bottom:4px'>Deze pagina kon niet worden geladen</h2>"
    "<p style='color:#777;font-size:14px'>__MELDING__</p>"
    "<p style='font-size:14px'>Sommige sites blokkeren weergave in een omlijst kader of "
    "beschermen zich tegen servers die pagina's ophalen. "
    "Gebruik de Tv-knop hierboven: de echte browser op de Pi kan vrijwel alles.</p>"
    "<p><a href='__URL__' target='_blank' rel='noopener'>Openen buiten Newly</a> &nbsp;|&nbsp; "
    "<a href='/browse?url=__URL_Q__&amp;mode=veilig'>Opnieuw in veilige modus</a></p>"
    "<p style='margin-top:40px'><a href='/'>Terug naar Newly</a></p></div>")


# ---------- advertentieblokkering op de Pi zelf ----------
GEBLOKKEERDE_HOSTS = (
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "google-analytics.com", "googletagmanager.com", "adservice.google.com",
    "adnxs.com", "adform.net", "advertising.com", "adsystem.com",
    "amazon-adsystem.com", "criteo.com", "criteo.net", "taboola.com",
    "outbrain.com", "pubmatic.com", "rubiconproject.com", "openx.net",
    "casalemedia.com", "bidswitch.net", "33across.com", "sharethrough.com",
    "scorecardresearch.com", "quantserve.com", "hotjar.com", "moatads.com",
    "ads-twitter.com", "analytics.tiktok.com", "facebook.net",
    "mc.yandex.ru", "lijit.com", "spotxchange.com",
)

def is_ad_host(host):
    host = (host or "").lower().strip(".")
    return any(host == h or host.endswith("." + h) for h in GEBLOKKEERDE_HOSTS)


# ---------- volledige proxy-engine ----------
# Belangrijk: alle herschreven adressen zijn ABSOLUUT (http://pi:8765/...),
# zodat de <base>-tag van de site ze niet kan verpesten.
def proxificeer(v, base, mode, oorsprong, route="/browse"):
    absolute = urllib.parse.urljoin(base, v)
    if not absolute.startswith(("http://", "https://")):
        return None
    return oorsprong + route + "?url=" + urllib.parse.quote(absolute, safe="") + "&amp;mode=" + mode


def bewerk_urls(text, base, mode, oorsprong):
    """src-, href-, poster- en data-src-kenmerken via de Pi laten lopen."""
    def vervang(m):
        attr, quote, v = m.group(1), m.group(2), m.group(3).strip()
        if not v:
            return m.group(0)
        if v.startswith("#"):
            if attr != "href":
                return m.group(0)
            if len(v) > 1:
                return ("href=" + quote + oorsprong + "/browse?url="
                        + urllib.parse.quote(base, safe="") + v + quote)
            return "href=" + quote + "javascript:void(0)" + quote
        if v.startswith(("mailto:", "tel:", "javascript:", "data:",
                         "blob:", "about:", "sms:")):
            return m.group(0)
        prox = proxificeer(v, base, mode, oorsprong)
        if prox:
            return attr + "=" + quote + prox + quote
        return m.group(0)
    return re.sub(r"(?is)\b(src|href|poster|data-src)\s*=\s*([\"'])(.*?)\2", vervang, text)


def bewerk_srcset(text, base, mode, oorsprong):
    def vervang(m):
        quote, waarde = m.group(1), m.group(2)
        delen = []
        for stuk in waarde.split(","):
            onderdelen = stuk.strip().split()
            if not onderdelen:
                continue
            absolute = urllib.parse.urljoin(base, onderdelen[0])
            if absolute.startswith(("http://", "https://")):
                onderdelen[0] = (oorsprong + "/browse?url="
                                 + urllib.parse.quote(absolute, safe=""))
            delen.append(" ".join(onderdelen))
        return "srcset=" + quote + ",".join(delen) + quote
    return re.sub(r"(?is)\bsrcset\s*=\s*([\"'])(.*?)\1", vervang, text)


def bewerk_forms(text, base, mode, oorsprong):
    """Formulieren via de Pi laten indienen (GET en POST)."""
    def vervang(m):
        quote, v = m.group(1), m.group(2).strip()
        if not v or v.startswith(("javascript:", "data:", "blob:")):
            return m.group(0)
        prox = proxificeer(v, base, mode, oorsprong, route="/form")
        if prox:
            return "action=" + quote + prox + quote
        return m.group(0)
    text = re.sub(r"(?is)\baction\s*=\s*([\"'])(.*?)\1", vervang, text)
    standaard = (oorsprong + "/form?url="
                 + urllib.parse.quote(base, safe="") + "&amp;mode=" + mode)

    def injecteer(m):
        return m.group(0)[:-1] + ' action="' + standaard + '">'

    text = re.sub(r"(?is)<form(?![^>]*\baction\b)[^>]*>", injecteer, text)
    return text


def herschrijf_css(text, css_url):
    """url(...) en @import in stylesheets via de Pi laten lopen."""
    def prox(v):
        if not v or v.startswith(("data:", "#", "blob:", "about:")):
            return None
        absolute = urllib.parse.urljoin(css_url, v)
        if not absolute.startswith(("http://", "https://")):
            return None
        return "url('/browse?url=" + urllib.parse.quote(absolute, safe="") + "')"

    def vervang_q(m):
        return prox(m.group(2)) or m.group(0)

    def vervang_zonder_quotes(m):
        return prox(m.group(1)) or m.group(0)

    def import_vervang(m):
        absolute = urllib.parse.urljoin(css_url, m.group(2))
        if absolute.startswith(("http://", "https://")):
            return ("@import '/browse?url="
                    + urllib.parse.quote(absolute, safe="") + "'")
        return m.group(0)

    text = re.sub(r"(?i)url\(\s*(['\"])([^'\"]+)\1\s*\)", vervang_q, text)
    text = re.sub(r"(?i)url\(\s*([^)'\"\s]+)\s*\)", vervang_zonder_quotes, text)
    text = re.sub(r"(?i)@import\s+(['\"])([^'\"]+)\1", import_vervang, text)
    return text


# Scriptje dat in elke pagina wordt gezet: fetch/XHR van de site gaan ook
# via de Pi (geen CORS- of oorsprongblokkades) en de paginageschiedenis van
# JavaScript-sites (pushState) wordt opgevangen zodat links gewoon werken.
SHIM_TEMPLATE = (
    "<script>"
    "(function(){"
    "var BASE=__BASE__;"
    "var O=location.protocol+'//'+location.host;"
    "function p(u){"
    "try{"
    "if(!u||typeof u!=='string')return u;"
    "if(u.indexOf(O+'/browse')===0||u.indexOf(O+'/form')===0)return u;"
    "if(u.indexOf('data:')===0||u.indexOf('blob:')===0)return u;"
    "var a=new URL(u,BASE);"
    "if(a.protocol!=='http:'&&a.protocol!=='https:')return u;"
    "return O+'/browse?url='+encodeURIComponent(a.href);"
    "}catch(e){return u;}"
    "}"
    "var of=window.fetch;"
    "if(of){window.fetch=function(input,init){"
    "try{"
    "if(typeof input==='string'){input=p(input);}"
    "else if(input&&input.url){input=new Request(p(input.url),input);}"
    "}catch(e){}"
    "return of.call(window,input,init);"
    "};}"
    "var oo=XMLHttpRequest.prototype.open;"
    "XMLHttpRequest.prototype.open=function(m,u){"
    "var rest=Array.prototype.slice.call(arguments,2);"
    "try{u=p(u);}catch(e){}"
    "return oo.apply(this,[m,u].concat(rest));"
    "};"
    "try{history.pushState=function(){};history.replaceState=function(){};}catch(e){}"
    "})();"
    "</script>")


def bewerk_html(text, final_url, mode, status, oorsprong=""):
    """HTML toonbaar maken binnen Newly: alle bronnen lopen via de Pi.

    oorsprong = ons eigen adres (http://pi-ip:poort). Alle herschreven
    links worden absoluut, anders lost de <base>-tag van de site ze op
    tegen het echte adres en krijg je "404 /browse was not found".
    """
    if mode == "veilig":
        text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", text)
        text = re.sub(r"(?is)<script\b[^>]*/>", "", text)
        text = re.sub(r"(?is)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text)

    # Meta-CSP en meta-refresh weg: die kloppen niet meer vanaf ons eigen adres
    text = re.sub(r"(?is)<meta[^>]+http-equiv\s*=\s*[\"']content-security-policy[\"'][^>]*>", "", text)
    text = re.sub(r"(?is)<meta[^>]+http-equiv\s*=\s*[\"']refresh[\"'][^>]*>", "", text)

    mb = re.search(r"(?is)<base[^>]+href=[\"']([^\"']+)[\"']", text)
    base = urllib.parse.urljoin(final_url, mb.group(1)) if mb else final_url
    if mb:
        text = text.replace(mb.group(0), "")

    text = bewerk_urls(text, base, mode, oorsprong)
    text = bewerk_srcset(text, base, mode, oorsprong)
    text = bewerk_forms(text, base, mode, oorsprong)
    text = re.sub(r"(?is)\s+integrity\s*=\s*([\"']).*?\1", "", text)

    inject = '<base href="' + html.escape(base) + '">'
    if not re.search(r"(?is)<meta[^>]+name=[\"']viewport[\"']", text):
        inject = inject + ('<meta name="viewport" '
                            'content="width=device-width, initial-scale=1">')
    if mode == "volledig":
        inject = inject + SHIM_TEMPLATE.replace("__BASE__", json.dumps(base))
    if re.search(r"(?is)<head[^>]*>", text):
        text = re.sub(r"(?is)(<head[^>]*>)", lambda m: m.group(1) + inject, text, count=1)
    else:
        text = inject + text

    if status >= 400:
        text = (FOUT_BANNER_TEMPLATE.replace("{basis}", oorsprong)
                .replace("{url}", urllib.parse.quote(base, safe=""))
                .replace("{status}", str(status)) + text)
    elif mode == "veilig" and len(zichtbare_tekst(text)) < 200:
        text = (LEEG_BANNER_TEMPLATE.replace("{basis}", oorsprong)
                .replace("{url}", urllib.parse.quote(base, safe="")) + text)
    return text, base


# ---------- Nieuwsearch: de eigen zoekmachine van Newly ----------
def index_zoek(q, user_id=None):
    """Zoeken in de eigen index op de Pi en in bladwijzers/geschiedenis."""
    schoon = re.sub(r"[%_\\]", " ", q.lower()).strip()
    resultaten = []
    if not schoon:
        return resultaten
    term = "%" + schoon + "%"
    con = connect()
    try:
        for url, titel in con.execute(
                "SELECT url, title FROM pages WHERE lower(title) LIKE ? OR lower(tekst) LIKE ? "
                "ORDER BY updated DESC LIMIT 8", (term, term)).fetchall():
            resultaten.append({"title": titel or url, "url": url,
                               "snippet": "Gevonden in je eigen Newly-index op de Pi.",
                               "bron": "eigen index"})
        eigen = []
        if user_id:
            eigen += con.execute(
                "SELECT url, title FROM history WHERE user_id = ? "
                "AND (lower(title) LIKE ? OR lower(url) LIKE ?) "
                "ORDER BY id DESC LIMIT 5", (user_id, term, term)).fetchall()
            eigen += con.execute(
                "SELECT url, title FROM bookmarks WHERE user_id = ? "
                "AND (lower(title) LIKE ? OR lower(url) LIKE ?) "
                "ORDER BY id DESC LIMIT 5", (user_id, term, term)).fetchall()
        for url, titel in eigen:
            if url.startswith(("http://", "https://")):
                resultaten.append({"title": titel or url, "url": url,
                                   "snippet": "Uit je eigen geschiedenis of bladwijzers.",
                                   "bron": "jouw pagina's"})
    finally:
        con.close()
    return resultaten


def wiki_zoek(q):
    """Zoeken in Wikipedia (nl) via de openbare API; geen sleutel nodig."""
    api = ("https://nl.wikipedia.org/w/api.php?action=query&list=search"
           "&format=json&srlimit=8&srsearch=" + urllib.parse.quote_plus(q))
    text, _, _, _ = haal_pagina(api)
    data = json.loads(text)
    resultaten = []
    for item in data.get("query", {}).get("search", []):
        titel = item.get("title", "")
        url = "https://nl.wikipedia.org/wiki/" + urllib.parse.quote(titel.replace(" ", "_"))
        snippet = re.sub(r"(?is)<[^>]+>", "", item.get("snippet", ""))
        resultaten.append({"title": titel + " - Wikipedia", "url": url,
                           "snippet": snippet[:300], "bron": "Wikipedia (nl)"})
    return resultaten


def url_gokken(q):
    """Bij een enkel woord: check of dat woord als webadres bestaat."""
    woorden = q.split()
    if len(woorden) != 1:
        return []
    basis = re.sub(r"[^a-z0-9-]", "", woorden[0].lower())
    if not basis or len(basis) > 40:
        return []
    gokken = []
    for tld in (".com", ".nl"):
        kandidaat = "https://" + basis + tld
        try:
            _, _, ctype, status = haal_pagina(kandidaat, limiet=65536, timeout=6)
        except Exception:
            continue
        if status < 400 and "html" in ctype.lower():
            gokken.append({"title": basis + tld, "url": kandidaat,
                           "snippet": "Dit webadres bestaat en lijkt te kloppen.",
                           "bron": "webadres"})
        if len(gokken) >= 2:
            break
    return gokken


def nieuwsearch(q, user_id=None):
    """Eigen zoekmachine: geen externe zoekdienst.

    Volgorde: eigen index, bladwijzers/geschiedenis, Wikipedia (nl),
    webadres-gissingen. Eerlijk: dit is geen vervanging voor een webbrede
    zoekindex met crawlers; de index groeit mee met wat je zelf bezoekt.
    """
    resultaten = []

    def voeg(items):
        for it in items:
            if not any(r["url"] == it["url"] for r in resultaten):
                resultaten.append(it)

    voeg(index_zoek(q, user_id))
    try:
        voeg(wiki_zoek(q))
    except Exception:
        pass
    voeg(url_gokken(q))
    return resultaten[:20]


def pagina_tekst(url, limiet=8000):
    """Zichtbare tekst van een pagina, als context voor de AI."""
    text, _, _, _ = haal_pagina(url)
    return zichtbare_tekst(text)[:limiet]


FAVICON_CACHE = {}

def favicon_bytes(host):
    """Favicons ophalen door de Pi zelf; geen dienst van derden."""
    if host in FAVICON_CACHE:
        return FAVICON_CACHE[host]
    data, ctype = b"", "image/x-icon"
    try:
        req = urllib.request.Request("https://" + host + "/favicon.ico", headers={
            "User-Agent": UA_STR, "Accept": "image/*;q=0.8,*/*;q=0.5"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read(262144)
            ctype = resp.headers.get("Content-Type", "image/x-icon")
        if not ctype.startswith("image"):
            data = b""
    except Exception:
        data = b""
    FAVICON_CACHE[host] = (data, ctype)
    return data, ctype


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
    server_version = "ZelfSync/0.9"

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

    def dien_pagina(self, target, mode, method="GET", body=None, content_type=None):
        """Elk bronbestand via de Pi serveren (html, css, js, beeld, json, video)."""
        host = urllib.parse.urlsplit(target).hostname or ""
        if method == "GET" and is_ad_host(host):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        # Ons eigen adres: alle herschreven links in pagina's worden hier
        # absoluut mee gemaakt (anders gooit de <base> van de site ze weg).
        oorsprong = "http://" + (self.headers.get("Host")
                                 or ("localhost:" + str(PORT)))
        # Videospelers vragen om stukjes (Range); die geven we 1-op-1 door
        range_header = self.headers.get("Range")
        try:
            raw, final_url, ctype, status, rheaders = haal_bron(
                target, method=method, body=body, content_type=content_type,
                limiet=64 * 1024 * 1024 if range_header else MAX_PAGE,
                extra_headers={"Range": range_header} if range_header else None)
        except Exception as exc:
            self.send_html(502, FOUT_PAGINA.replace("__MELDING__", html.escape(str(exc)))
                           .replace("__URL__", html.escape(target, quote=True))
                           .replace("__URL_Q__", urllib.parse.quote(target, safe="")),
                           csp="script-src 'none'")
            return
        ct = (ctype or "").lower()
        if range_header and status in (200, 206) and not ("html" in ct or "text/css" in ct):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "max-age=3600")
            if "Content-Range" in rheaders:
                self.send_header("Content-Range", rheaders["Content-Range"])
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        csp = None
        cache = "max-age=3600"
        if "text/css" in ct:
            payload = herschrijf_css(als_tekst(raw, ctype), final_url).encode("utf-8", "replace")
            ctype = "text/css; charset=utf-8"
        elif "html" in ct or b"<html" in raw[:2000].lower():
            tekst, base = bewerk_html(als_tekst(raw, ctype), final_url, mode, status, oorsprong)
            payload = tekst.encode("utf-8", "replace")
            ctype = "text/html; charset=utf-8"
            csp = ("script-src 'none'; object-src 'none'; frame-src 'none'; "
                   "frame-ancestors 'self'") if mode == "veilig" else "frame-ancestors 'self'"
            cache = "no-store"
            try:
                indexeer(final_url, tekst, status)
            except Exception:
                pass
        elif any(t in ct for t in ("javascript", "json", "text/", "svg", "xml")):
            payload = als_tekst(raw, ctype).encode("utf-8", "replace")
            if "charset" in ctype:
                ctype = re.sub(r"charset=[\w.-]+", "charset=utf-8", ctype)
            else:
                ctype = ctype + "; charset=utf-8"
        else:
            payload = raw
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(payload)))
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        self.wfile.write(payload)

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
        if self.path.startswith("/browse") or self.path.startswith("/form"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query,
                                           keep_blank_values=True)
            target = (params.get("url") or [""])[0]
            mode = (params.get("mode") or ["volledig"])[0]
            if mode not in ("volledig", "veilig"):
                mode = "volledig"
            if self.path.startswith("/form") and target.startswith(("http://", "https://")):
                extra = []
                for k, lijst in params.items():
                    if k in ("url", "mode"):
                        continue
                    for v in lijst:
                        extra.append((k, v))
                if extra:
                    delen = urllib.parse.urlsplit(target)
                    q = urllib.parse.parse_qsl(delen.query, keep_blank_values=True) + extra
                    target = delen._replace(query=urllib.parse.urlencode(q)).geturl()
            if not target.startswith(("http://", "https://")):
                self.send_html(400,
                               "<h3 style='font-family:system-ui'>Ongeldig adres</h3>"
                               "<p><a href='/'>Terug naar Newly</a></p>")
                return
            self.dien_pagina(target, mode)
            return
        if self.path.startswith("/search"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            q = (params.get("q") or [""])[0].strip()[:300]
            if not q:
                self.send_json(400, {"error": "lege zoekterm"})
                return
            user_id = None
            con = connect()
            try:
                user = self.auth_user(con)
                if user:
                    user_id = user[0]
            except Exception:
                pass
            finally:
                con.close()
            try:
                self.send_json(200, {"results": nieuwsearch(q, user_id)})
            except Exception as exc:
                self.send_json(502, {"error": "Zoeken mislukt: " + str(exc)})
            return
        if self.path.startswith("/favicon"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            host = (params.get("u") or [""])[0].strip().lower()
            if not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host:
                self.send_response(400)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data, ctype = favicon_bytes(host)
            if not data:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/ai-status":
            self.send_json(200, {"key_set": bool(lees_api_key())})
            return

        con = connect()
        try:
            if self.path == "/health":
                self.send_json(200, {"status": "ok", "server": "zelfsync", "version": "0.9"})
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
        if self.path.startswith("/browse") or self.path.startswith("/form"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            target = (params.get("url") or [""])[0]
            mode = (params.get("mode") or ["volledig"])[0]
            if mode not in ("volledig", "veilig"):
                mode = "volledig"
            if not target.startswith(("http://", "https://")):
                self.send_html(400, "<h3 style='font-family:system-ui'>Ongeldig adres</h3>")
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            inhoud = self.rfile.read(min(length, MAX_BODY)) if length > 0 else None
            self.dien_pagina(target, mode, method="POST", body=inhoud,
                             content_type=self.headers.get("Content-Type", ""))
            return
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
    print("ZelfSync + Newly browser-in-browser draait op poort %d" % PORT)
    print("Open in een browser op hetzelfde netwerk: http://<pi-adres>:%d/" % PORT)
    print("Nieuwsearch zoekt in je eigen index, Wikipedia (nl) en raadt webadressen.")
    print("Volledige proxy + advertentieblokkering aan. Tv-knop opent de echte Chromium (poort 6080).")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("ZelfSync gestopt.")


if __name__ == "__main__":
    main()
