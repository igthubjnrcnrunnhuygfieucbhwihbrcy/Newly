#!/usr/bin/env python3
"""ZelfSync + Nieuwsearch browser-in-browser (Raspberry Pi 5). Versie 0.9.

Taken:
1. Sync-server: accounts, bladwijzers, geschiedenis (SQLite).
2. Browser-in-browser op http://pi-adres:8765/ :
   - Tabbladen, terug/vooruit, volledige en veilige weergave
   - Nieuwsearch: de eigen zoekmachine van Nieuwsearch (eigen index op de Pi,
     bladwijzers/geschiedenis, Wikipedia nl, webadres-radiging)
   - AI-assistent via je eigen Mistral API-sleutel, opgeslagen op de Pi
3. Volledige proxy-engine: ALLE bronnen lopen via de Pi, met ABSOLUUT
   herschreven adressen (http://pi:8765/browse?...). Relatieve paden
   werden door de <base>-tag van de site verkeerd opgelost - dat was de
   oorzaak van dode links, kapotte css en formulieren.
4. Ingebouwde advertentieblokkering op de Pi zelf.
5. Knop "Echte browser": echte Chromium op de Pi via schermdeling
   (poort 6080, zie install-pi.sh). Daar werkt alles.

Start:      python3 server.py      (poort 8765, of CLIMORA_PORT=...)
Service:    zie install-pi.sh (systemd)
"""
import gzip
import hashlib
import html
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB_PATH = Path(os.environ.get("NEWLY_DB_PATH",
                              Path(__file__).resolve().parent / "data" / "zelfsync.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
KEY_PATH = DB_PATH.parent / "data" / "apikey.txt"
MAX_BODY = 1_000_000
MAX_PAGE = 6 * 1024 * 1024
PORT = int(os.environ.get("CLIMORA_PORT", "8765"))
LLM_MODEL = os.environ.get("LLM_MODEL", "mistral-small-latest")
UA_STR = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 NieuwsearchBrowser/0.9")

# De UI staat in een apart bestand zodat die normaal te bewerken is;
# de installer kopieert de hele sync-servermap inclusief static/.
INDEX_HTML_PATH = Path(__file__).resolve().parent / "static" / "index.html"
try:
    INDEX_HTML = INDEX_HTML_PATH.read_text(encoding="utf-8")
except OSError:
    INDEX_HTML = ("<!DOCTYPE html><html lang=\"nl\"><head><meta charset=\"utf-8\">"
                  "<title>Climora</title></head><body>"
                  "<h1>Climora</h1><p>static/index.html ontbreekt; "
                  "installeer de server opnieuw (zie install-pi.sh).</p></body></html>")


# ---------- SSRF-bescherming ----------
# De proxy mag nooit interne adressen ophalen (router, localhost-diensten,
# cloud-metadata). We lossen de hostnaam op en weigeren private IP's.
def is_private_host(host):
    if not host:
        return True
    host = host.strip("[].").lower()
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return True
    return False


def veilige_target(url):
    """Geef True terug als de URL veilig opgehaald mag worden."""
    delen = urllib.parse.urlsplit(url)
    if delen.scheme not in ("http", "https"):
        return False
    if delen.username or delen.password:
        return False
    return not is_private_host(delen.hostname or "")


def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        "CREATE TABLE IF NOT EXISTS users ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  username TEXT UNIQUE NOT NULL,"
        "  pwhash TEXT NOT NULL,"
        "  salt TEXT NOT NULL,"
        "  token TEXT UNIQUE,"
        "  token_hash TEXT UNIQUE,"
        "  token_created TEXT"
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
        "  updated TEXT DEFAULT (datetime('now')),"
        "  user_id INTEGER"
        ");")
    # Migraties voor bestaande databases
    for kolom, definitie in (("token_hash", "TEXT UNIQUE"),
                             ("token_created", "TEXT")):
        try:
            con.execute(f"ALTER TABLE users ADD COLUMN {kolom} {definitie}")
        except sqlite3.OperationalError:
            pass
    try:
        con.execute("ALTER TABLE pages ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError:
        pass
    # Bestaande plaintext-tokens eenmalig hashen en daarna wissen
    rows = con.execute(
        "SELECT id, token FROM users WHERE token_hash IS NULL AND token IS NOT NULL AND token != ''").fetchall()
    for rid, tok in rows:
        con.execute("UPDATE users SET token_hash = ?, token = NULL, token_created = datetime('now') WHERE id = ?",
                    (hash_token(tok), rid))
    con.commit()
    return con


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               bytes.fromhex(salt_hex), 120_000).hex()


# ---------- rate limiting (brute-force login/register) ----------
POGINGEN = {}
POGING_LOCK = threading.Lock()
POGING_VENSTER = 300
POGING_MAX = 10

def toegestaan(sleutel, max_pogingen=POGING_MAX):
    nu = time.time()
    with POGING_LOCK:
        lijst = [t for t in POGINGEN.get(sleutel, []) if nu - t < POGING_VENSTER]
        if len(lijst) >= max_pogingen:
            POGINGEN[sleutel] = lijst
            return False
        lijst.append(nu)
        POGINGEN[sleutel] = lijst
        if len(POGINGEN) > 10_000:
            for k in [k for k, v in POGINGEN.items() if not v]:
                POGINGEN.pop(k, None)
        return True


# ---------- cookies (per sessie, per domein, alleen in het geheugen) ----------
KOEKJES = {}
KOEK_LOCK = threading.Lock()
KOEK_MAX_SESSIES = 500

def koekjes_voor(sessie, host):
    if not host or not sessie:
        return ""
    with KOEK_LOCK:
        items = KOEKJES.get(sessie, {}).get(host, {})
    return "; ".join(k + "=" + v for k, v in items.items())

def koekjes_opslaan(sessie, host, headers):
    if not sessie or not host or headers is None:
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
            KOEKJES.setdefault(sessie, {}).setdefault(host, {})[k.strip()] = v.strip()
            if len(KOEKJES) > KOEK_MAX_SESSIES:
                KOEKJES.pop(next(iter(KOEKJES)), None)


def haal_bron(url, method="GET", body=None, content_type=None,
              limiet=MAX_PAGE, timeout=25, extra_headers=None, sessie=None):
    """Ruwe bytes van een bron ophalen (gzip, cookies, ook foutpagina's)."""
    host = urllib.parse.urlsplit(url).hostname or ""
    headers = {
        "User-Agent": UA_STR,
        "Accept": "*/*",
        "Accept-Encoding": "gzip",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    }
    koek = koekjes_voor(sessie, host)
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
        koekjes_opslaan(sessie, urllib.parse.urlsplit(final_url).hostname or host, resp.headers)
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


def indexeer(url, pagina, status, user_id=None):
    """Bezochte pagina's opslaan in de eigen Nieuwsearch-index op de Pi.

    Per gebruiker: wat de ene gebruiker bezoekt is niet doorzoekbaar voor
    een andere (privacy).
    """
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
            "INSERT INTO pages (url, title, tekst, updated, user_id) VALUES (?, ?, ?, datetime('now'), ?) "
            "ON CONFLICT(url) DO UPDATE SET title=excluded.title, tekst=excluded.tekst, "
            "updated=excluded.updated, user_id=excluded.user_id",
            (url, titel, tekst[:6000], user_id))
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
    "<p><a href='__URL__' target='_blank' rel='noopener'>Openen buiten Nieuwsearch</a> &nbsp;|&nbsp; "
    "<a href='/browse?url=__URL_Q__&amp;mode=veilig'>Opnieuw in veilige modus</a></p>"
    "<p style='margin-top:40px'><a href='/'>Terug naar Nieuwsearch</a></p></div>")


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
    """HTML toonbaar maken binnen Nieuwsearch: alle bronnen lopen via de Pi.

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


# ---------- Nieuwsearch: de eigen zoekmachine van Nieuwsearch ----------
def index_zoek(q, user_id=None):
    """Zoeken in de eigen index op de Pi en in bladwijzers/geschiedenis."""
    schoon = re.sub(r"[%_\\]", " ", q.lower()).strip()
    resultaten = []
    if not schoon:
        return resultaten
    term = "%" + schoon + "%"
    con = connect()
    try:
        if user_id:
            for url, titel in con.execute(
                    "SELECT url, title FROM pages WHERE user_id = ? "
                    "AND (lower(title) LIKE ? OR lower(tekst) LIKE ?) "
                    "ORDER BY updated DESC LIMIT 8", (user_id, term, term)).fetchall():
                resultaten.append({"title": titel or url, "url": url,
                                   "snippet": "Gevonden in je eigen Nieuwsearch-index op de Pi.",
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
                 "content": "Je bent de AI-assistent van de Nieuwsearch-browser. "
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
    server_version = "Climora/1.0"

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
        return con.execute(
            "SELECT id, username FROM users WHERE token_hash = ? "
            "AND (token_created IS NULL "
            "     OR datetime(token_created, '+30 days') > datetime('now'))",
            (hash_token(token),)).fetchone()

    def sessie_id(self):
        """Sessiesleutel voor de cookie-jar: per account, anders per client-IP."""
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        if token:
            return "tok:" + hash_token(token)[:24]
        return "ip:" + (self.client_address[0] if self.client_address else "onbekend")

    def dien_pagina(self, target, mode, method="GET", body=None, content_type=None,
                    sessie=None, user_id=None):
        """Elk bronbestand via de Pi serveren (html, css, js, beeld, json, video)."""
        if not veilige_target(target):
            self.send_html(403,
                           "<h3 style='font-family:system-ui'>Geblokkeerd adres</h3>"
                           "<p style='font-family:system-ui;font-size:14px'>Interne en "
                           "private adressen (localhost, het lokale netwerk, 169.254.x.x) "
                           "kunnen niet via de proxy worden geopend.</p>"
                           "<p><a href='/'>Terug naar Nieuwsearch</a></p>",
                           csp="script-src 'none'")
            return
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
                extra_headers={"Range": range_header} if range_header else None,
                sessie=sessie)
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
            # CSP-sandbox: geproxiede pagina's draaien altijd in een ondoorzichtig
            # (opaque) origin, ook als de gebruiker /browse direct (buiten het
            # sandboxed iframe) opent. Zo komen ze nooit bij de tokens van de app.
            if mode == "veilig":
                csp = ("sandbox allow-forms allow-popups; script-src 'none'; "
                       "object-src 'none'; frame-src 'none'; frame-ancestors 'self'")
            else:
                csp = ("sandbox allow-scripts allow-forms allow-popups allow-downloads; "
                       "object-src 'none'; frame-ancestors 'self'")
            cache = "no-store"
            try:
                indexeer(final_url, tekst, status, user_id)
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

    APP_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
               "connect-src 'self'; frame-src 'self'; base-uri 'none'; "
               "form-action 'self'")

    def verzend_beveiliging(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_response(200)
            data = INDEX_HTML.encode("utf-8", "replace")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", self.APP_CSP)
            self.verzend_beveiliging()
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith("/browse") or self.path.startswith("/form"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query,
                                           keep_blank_values=True)
            target = (params.get("url") or [""])[0]
            mode = (params.get("mode") or ["volledig"])[0]
            if mode not in ("volledig", "veilig"):
                mode = "volledig"
            sessie = self.sessie_id()
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
                               "<p><a href='/'>Terug naar Nieuwsearch</a></p>")
                return
            self.dien_pagina(target, mode, sessie=sessie, user_id=user_id)
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
            except Exception:
                self.send_json(502, {"error": "Zoeken mislukt, probeer het opnieuw."})
            return
        if self.path.startswith("/favicon"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            host = (params.get("u") or [""])[0].strip().lower()
            if not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host or is_private_host(host):
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
            sessie = self.sessie_id()
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
            if not target.startswith(("http://", "https://")):
                self.send_html(400, "<h3 style='font-family:system-ui'>Ongeldig adres</h3>")
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            inhoud = self.rfile.read(min(length, MAX_BODY)) if length > 0 else None
            self.dien_pagina(target, mode, method="POST", body=inhoud,
                             content_type=self.headers.get("Content-Type", ""),
                             sessie=sessie, user_id=user_id)
            return
        con = connect()
        try:
            path = self.path.rstrip("/")
            body = self.read_json() or {}
            if path == "/api-key":
                user = self.auth_user(con)
                if not user:
                    self.send_json(401, {"error": "log eerst in om de AI-sleutel te beheren"})
                    return
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
                user = self.auth_user(con)
                if not user:
                    self.send_json(401, {"error": "log eerst in om de AI-assistent te gebruiken"})
                    return
                prompt = str(body.get("prompt", ""))[:4000]
                if not prompt:
                    self.send_json(400, {"error": "lege vraag"})
                    return
                try:
                    self.send_json(200, ai_vraag(prompt, str(body.get("url", ""))))
                except urllib.error.HTTPError as exc:
                    self.send_json(502, {"error": "LLM-api gaf fout " + str(exc.code)
                                               + " (controleer je API-sleutel)"})
                except Exception:
                    self.send_json(502, {"error": "de AI-assistent is nu niet bereikbaar, probeer het later opnieuw"})
                return
            if path == "/register":
                if not toegestaan("reg:" + self.client_address[0]):
                    self.send_json(429, {"error": "te veel pogingen, probeer het later opnieuw"})
                    return
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
                        "INSERT INTO users (username, pwhash, salt, token, token_hash, token_created) "
                        "VALUES (?, ?, ?, NULL, ?, datetime('now'))",
                        (username, hash_password(password, salt), salt, hash_token(token)))
                    con.commit()
                except sqlite3.IntegrityError:
                    self.send_json(409, {"error": "gebruikersnaam bestaat al"})
                    return
                self.send_json(201, {"ok": True, "token": token})
                return
            if path == "/login":
                if not toegestaan("log:" + self.client_address[0]):
                    self.send_json(429, {"error": "te veel inlogpogingen, probeer het over 5 minuten opnieuw"})
                    return
                row = con.execute("SELECT id, pwhash, salt FROM users WHERE username = ?",
                                  (str(body.get("username", "")),)).fetchone()
                if not row or not secrets.compare_digest(
                        hash_password(str(body.get("password", "")), row[2]), row[1]):
                    self.send_json(401, {"error": "verkeerde inloggegevens"})
                    return
                # Nieuw token bij elke login (oude sessies vervallen niet meteen,
                # maar hetzelfde token wordt nooit opnieuw uitgegeven)
                token = secrets.token_hex(32)
                con.execute(
                    "UPDATE users SET token = NULL, token_hash = ?, token_created = datetime('now') "
                    "WHERE id = ?", (hash_token(token), row[0]))
                con.commit()
                self.send_json(200, {"ok": True, "token": token})
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
                if not url.startswith(("http://", "https://")):
                    self.send_json(400, {"error": "url moet met http(s):// beginnen"})
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
    print("ZelfSync + Nieuwsearch browser-in-browser draait op poort %d" % PORT)
    print("Open in een browser op hetzelfde netwerk: http://<pi-adres>:%d/" % PORT)
    print("Nieuwsearch zoekt in je eigen index, Wikipedia (nl) en raadt webadressen.")
    print("Volledige proxy + advertentieblokkering aan. Tv-knop opent de echte Chromium (poort 6080).")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("ZelfSync gestopt.")


if __name__ == "__main__":
    main()
