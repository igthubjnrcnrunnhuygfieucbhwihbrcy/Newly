#!/usr/bin/env python3
"""Climora API Server — Externe REST API voor Climora browser.

Deze server biedt een eigen REST API voor externe toegang tot Climora functionaliteit.
Het is bedoeld om te draaien op een Raspberry Pi of VPS en biedt:

- API toegang tot browser functionaliteit
- Integreert met Climora Sync voor bookmarks en geschiedenis
- Kan verbinden met externe services en leveranciers
- Beveiliging via API-sleutels

Start:      python3 api_server.py      (poort 8767)
Config:     export NEWLY_API_PORT=8767
            export NEWLY_API_KEY="jouw-geheime-sleutel"
"""
import json
import os
import sqlite3
import secrets
import hashlib
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime

# Configuratie
API_PORT = int(os.environ.get("NEWLY_API_PORT", "8767"))
API_KEY = os.environ.get("NEWLY_API_KEY", "")
DEBUG = os.environ.get("NEWLY_API_DEBUG", "false").lower() == "true"

# Database configuratie (deelt database met sync-server)
DB_PATH = Path(__file__).resolve().parent / "data" / "zelfsync.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# API-sleutels voor externe clients (opslaan in apart bestand)
API_KEYS_FILE = Path(__file__).resolve().parent / "config" / "api_keys.json"
API_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)

# Laad API-sleutels
def load_api_keys():
    """Laad API-sleutels voor externe clients."""
    if not API_KEYS_FILE.exists():
        return {}
    try:
        with open(API_KEYS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

# Sla API-sleutels op
def save_api_keys(keys):
    """Sla API-sleutels op (alleen gehashte secrets)."""
    try:
        with open(API_KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(keys, f, indent=2)
        try:
            API_KEYS_FILE.chmod(0o600)
        except OSError:
            pass
    except IOError:
        pass


def hash_secret(secret):
    """Hash een client-secret; plaintext secrets worden nooit opgeslagen."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


# Huidige API-sleutels
CLIENT_API_KEYS = load_api_keys()
# Migratie: bestaande plaintext-secrets eenmalig hashen
_migreer = False
for _cid, _info in CLIENT_API_KEYS.items():
    _sec = _info.get("secret", "")
    if _sec and not _info.get("secret_hash"):
        _info["secret_hash"] = hash_secret(_sec)
        _info.pop("secret", None)
        _migreer = True
if _migreer:
    save_api_keys(CLIENT_API_KEYS)

# ---------- rate limiting ----------
VERZOEKEN = {}
VERZOEK_LOCK = threading.Lock()
VERZOEK_VENSTER = 60
VERZOEK_MAX = 120

def rate_ok(identiteit):
    nu = time.time()
    with VERZOEK_LOCK:
        lijst = [t for t in VERZOEKEN.get(identiteit, []) if nu - t < VERZOEK_VENSTER]
        if len(lijst) >= VERZOEK_MAX:
            VERZOEKEN[identiteit] = lijst
            return False
        lijst.append(nu)
        VERZOEKEN[identiteit] = lijst
        return True

# Verbinding met database
def get_db_connection():
    """Maak verbinding met SQLite database."""
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    return con

# Initialiseer database
def init_database():
    """Initialiseer de database met benodigde tabellen."""
    con = get_db_connection()
    try:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS api_clients (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id TEXT UNIQUE NOT NULL,
              client_secret TEXT NOT NULL,
              name TEXT NOT NULL,
              permissions TEXT DEFAULT 'read',
              rate_limit INTEGER DEFAULT 100,
              created_at TEXT DEFAULT (datetime('now')),
              expires_at TEXT
            );
            CREATE TABLE IF NOT EXISTS api_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id TEXT,
              endpoint TEXT NOT NULL,
              method TEXT NOT NULL,
              status_code INTEGER NOT NULL,
              request_data TEXT,
              response_time_ms INTEGER,
              timestamp TEXT DEFAULT (datetime('now')),
              ip_address TEXT
            );
            CREATE TABLE IF NOT EXISTS external_services (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              service_type TEXT NOT NULL,
              api_url TEXT NOT NULL,
              api_key TEXT,
              config TEXT,
              is_active BOOLEAN DEFAULT 1,
              created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS webhooks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              url TEXT NOT NULL,
              events TEXT NOT NULL,
              secret TEXT,
              is_active BOOLEAN DEFAULT 1,
              created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        con.commit()
    finally:
        con.close()

# Initialiseer bij starten
init_database()


class APIHandler(BaseHTTPRequestHandler):
    """HTTP request handler voor de Climora API."""
    server_version = "ClimoraAPI/1.0"

    def log_message(self, fmt, *args):
        """Log berichten (alleen in debug mode)."""
        if DEBUG:
            print(fmt % args)

    def send_json(self, code, obj, headers=None):
        """Stuur JSON response."""
        data = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Client-ID")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        """Lees JSON body."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > 1_000_000:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return None

    def authenticate(self):
        """Authenticeer de request (constante-tijd-vergelijkingen)."""
        # Check master API key; zonder ingestelde sleutel bestaat er geen
        # admin-toegang (anders was een lege Bearer-token al admin).
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and API_KEY:
            token = auth_header[7:].strip()
            if token and secrets.compare_digest(token, API_KEY):
                return {"authenticated": True, "client_id": "admin", "permissions": "*"}
        
        # Check client API key (secret staat gehasht opgeslagen)
        client_id = self.headers.get("X-Client-ID", "")
        client_secret = self.headers.get("X-Client-Secret", "")
        
        if client_id and client_secret:
            info = CLIENT_API_KEYS.get(client_id)
            if info:
                stored_hash = info.get("secret_hash", "")
                if stored_hash and secrets.compare_digest(hash_secret(client_secret), stored_hash):
                    return {
                        "authenticated": True,
                        "client_id": client_id,
                        "permissions": info.get("permissions", "read")
                    }
        
        return {"authenticated": False}

    def has_permission(self, required_permission):
        """Controleer of de client de benodigde permissie heeft."""
        auth = self.authenticate()
        if not auth["authenticated"]:
            return False
        
        if auth["permissions"] == "*":
            return True
        
        if required_permission in auth["permissions"].split(","):
            return True
        
        return False

    def audit_log(self, endpoint, method, status_code, start_time=None):
        """Log de request voor auditing."""
        auth = self.authenticate()
        client_id = auth.get("client_id", "anonymous")
        
        try:
            con = get_db_connection()
            response_time = 0
            if start_time:
                response_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            con.execute(
                "INSERT INTO api_logs (client_id, endpoint, method, status_code, response_time_ms) VALUES (?, ?, ?, ?, ?)",
                (client_id, endpoint, method, status_code, response_time)
            )
            con.commit()
        except Exception as e:
            if DEBUG:
                print(f"Error logging request: {e}")
        finally:
            if 'con' in locals():
                con.close()

    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Client-ID, X-Client-Secret")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def check_rate(self):
        """Eenvoudige snelheidslimiet per client; 429 bij overschrijding."""
        auth = self.authenticate()
        identiteit = auth.get("client_id") or (self.client_address[0] if self.client_address else "onbekend")
        if not rate_ok(identiteit):
            self.send_json(429, {"error": "Te veel verzoeken, wacht even."})
            return False
        return True

    def do_GET(self):
        """Handle GET requests."""
        start_time = datetime.now()
        
        if not self.check_rate():
            self.audit_log("rate-limited", "GET", 429, start_time)
            return
        
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query_params = urllib.parse.parse_qs(parsed.query)
        
        try:
            # Open endpoints
            if path == "/health":
                self.send_json(200, {
                    "status": "ok",
                    "version": "1.0",
                    "timestamp": datetime.now().isoformat()
                })
                self.audit_log("/health", "GET", 200, start_time)
                return
            
            if path == "/":
                self.send_json(200, {
                    "name": "Climora API",
                    "version": "1.0",
                    "description": "REST API voor Climora browser functionaliteit",
                    "endpoints": {
                        "GET /health": "Server status",
                        "GET /api": "API informatie",
                        "POST /api/clients": "Maak een nieuwe API client aan",
                        "GET /api/clients": "Lijst van API clients (admin)",
                        "POST /api/bookmarks": "Voeg een bladwijzer toe",
                        "GET /api/bookmarks": "Haal bladwijzers op",
                        "POST /api/history": "Voeg geschiedenis item toe",
                        "GET /api/history": "Haal geschiedenis op",
                        "POST /api/search": "Zoek in eigen index",
                        "POST /api/ask": "Stel een vraag aan de AI",
                        "GET /api/services": "Lijst van externe services",
                        "POST /api/services": "Voeg externe service toe",
                        "POST /api/webhooks": "Voeg webhook toe",
                        "GET /api/stats": "Statistieken"
                    },
                    "authentication": {
                        "header": "Authorization: Bearer <API_KEY>",
                        "or": "X-Client-ID and X-Client-Secret headers"
                    }
                })
                self.audit_log("/", "GET", 200, start_time)
                return
            
            if path == "/api":
                if not self.has_permission("read"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api", "GET", 401, start_time)
                    return
                
                self.send_json(200, {
                    "name": "Climora API",
                    "version": "1.0",
                    "capabilities": ["bookmarks", "history", "search", "ai", "webhooks"],
                    "rate_limit": 100,
                    "timestamp": datetime.now().isoformat()
                })
                self.audit_log("/api", "GET", 200, start_time)
                return
            
            # Bookmarks endpoints
            if path == "/api/bookmarks":
                if not self.has_permission("read"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api/bookmarks", "GET", 401, start_time)
                    return
                
                user_id = query_params.get("user_id", [None])[0]
                try:
                    limit = min(1000, max(1, int(query_params.get("limit", ["100"])[0])))
                except ValueError:
                    limit = 100
                
                con = get_db_connection()
                try:
                    if user_id:
                        rows = con.execute(
                            "SELECT id, title, url, created FROM bookmarks WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                            (user_id, limit)
                        ).fetchall()
                    else:
                        rows = con.execute(
                            "SELECT id, title, url, created FROM bookmarks ORDER BY id DESC LIMIT ?",
                            (limit,)
                        ).fetchall()
                    
                    bookmarks = [dict(row) for row in rows]
                    self.send_json(200, {"bookmarks": bookmarks, "count": len(bookmarks)})
                finally:
                    con.close()
                
                self.audit_log("/api/bookmarks", "GET", 200, start_time)
                return
            
            # History endpoints
            if path == "/api/history":
                if not self.has_permission("read"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api/history", "GET", 401, start_time)
                    return
                
                user_id = query_params.get("user_id", [None])[0]
                try:
                    limit = min(1000, max(1, int(query_params.get("limit", ["100"])[0])))
                except ValueError:
                    limit = 100
                
                con = get_db_connection()
                try:
                    if user_id:
                        rows = con.execute(
                            "SELECT id, title, url, visited FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                            (user_id, limit)
                        ).fetchall()
                    else:
                        rows = con.execute(
                            "SELECT id, title, url, visited FROM history ORDER BY id DESC LIMIT ?",
                            (limit,)
                        ).fetchall()
                    
                    history = [dict(row) for row in rows]
                    self.send_json(200, {"history": history, "count": len(history)})
                finally:
                    con.close()
                
                self.audit_log("/api/history", "GET", 200, start_time)
                return
            
            # Stats endpoint
            if path == "/api/stats":
                if not self.has_permission("read"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api/stats", "GET", 401, start_time)
                    return
                
                con = get_db_connection()
                try:
                    bookmark_count = con.execute("SELECT COUNT(*) as cnt FROM bookmarks").fetchone()["cnt"]
                    history_count = con.execute("SELECT COUNT(*) as cnt FROM history").fetchone()["cnt"]
                    user_count = con.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
                    
                    self.send_json(200, {
                        "statistics": {
                            "bookmarks": bookmark_count,
                            "history_items": history_count,
                            "users": user_count
                        }
                    })
                finally:
                    con.close()
                
                self.audit_log("/api/stats", "GET", 200, start_time)
                return
            
            # External services
            if path == "/api/services":
                if not self.has_permission("read"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api/services", "GET", 401, start_time)
                    return
                
                con = get_db_connection()
                try:
                    rows = con.execute(
                        "SELECT id, name, service_type, api_url, is_active, created_at FROM external_services ORDER BY id DESC"
                    ).fetchall()
                    services = [dict(row) for row in rows]
                    self.send_json(200, {"services": services, "count": len(services)})
                finally:
                    con.close()
                
                self.audit_log("/api/services", "GET", 200, start_time)
                return
            
            # 404 for unknown endpoints
            self.send_json(404, {"error": "Onbekend endpoint"})
            self.audit_log(path, "GET", 404, start_time)
            
        except Exception:
            if DEBUG:
                import traceback
                traceback.print_exc()
            self.send_json(500, {"error": "Interne serverfout"})
            self.audit_log(path, "GET", 500, start_time)

    def do_POST(self):
        """Handle POST requests."""
        start_time = datetime.now()
        
        if not self.check_rate():
            self.audit_log("rate-limited", "POST", 429, start_time)
            return
        
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self.read_json() or {}
        
        try:
            # Create API client
            if path == "/api/clients":
                if not self.has_permission("*"):
                    self.send_json(401, {"error": "Alleen admin kan clients aanmaken"})
                    self.audit_log("/api/clients", "POST", 401, start_time)
                    return
                
                name = str(body.get("name", "Unnamed Client"))[:100]
                permissions = str(body.get("permissions", "read"))
                try:
                    rate_limit = min(10_000, max(1, int(body.get("rate_limit", 100))))
                except (TypeError, ValueError):
                    rate_limit = 100
                
                # Genereer client ID en secret; alleen de hash wordt bewaard
                client_id = secrets.token_hex(16)
                client_secret = secrets.token_hex(32)
                secret_hash = hash_secret(client_secret)
                
                CLIENT_API_KEYS[client_id] = {
                    "secret_hash": secret_hash,
                    "name": name,
                    "permissions": permissions,
                    "rate_limit": rate_limit,
                    "created_at": datetime.now().isoformat()
                }
                save_api_keys(CLIENT_API_KEYS)
                
                # Sla ook op in database voor persistentie (gehasht)
                con = get_db_connection()
                try:
                    con.execute(
                        "INSERT INTO api_clients (client_id, client_secret, name, permissions, rate_limit) VALUES (?, ?, ?, ?, ?)",
                        (client_id, secret_hash, name, permissions, rate_limit)
                    )
                    con.commit()
                finally:
                    con.close()
                
                self.send_json(201, {
                    "ok": True,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "name": name,
                    "permissions": permissions,
                    "rate_limit": rate_limit
                })
                self.audit_log("/api/clients", "POST", 201, start_time)
                return
            
            # Add bookmark
            if path == "/api/bookmarks":
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api/bookmarks", "POST", 401, start_time)
                    return
                
                url = body.get("url", "")
                title = body.get("title", "")
                user_id = body.get("user_id")
                
                if not url:
                    self.send_json(400, {"error": "URL is verplicht"})
                    self.audit_log("/api/bookmarks", "POST", 400, start_time)
                    return
                
                con = get_db_connection()
                try:
                    if user_id:
                        exists = con.execute(
                            "SELECT id FROM bookmarks WHERE user_id = ? AND url = ?",
                            (user_id, url)
                        ).fetchone()
                        if not exists:
                            con.execute(
                                "INSERT INTO bookmarks (user_id, title, url) VALUES (?, ?, ?)",
                                (user_id, title, url)
                            )
                    else:
                        con.execute(
                            "INSERT INTO bookmarks (title, url) VALUES (?, ?)",
                            (title, url)
                        )
                    con.commit()
                    self.send_json(201, {"ok": True})
                finally:
                    con.close()
                
                self.audit_log("/api/bookmarks", "POST", 201, start_time)
                return
            
            # Add history
            if path == "/api/history":
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api/history", "POST", 401, start_time)
                    return
                
                url = body.get("url", "")
                title = body.get("title", "")
                user_id = body.get("user_id")
                
                if not url:
                    self.send_json(400, {"error": "URL is verplicht"})
                    self.audit_log("/api/history", "POST", 400, start_time)
                    return
                
                con = get_db_connection()
                try:
                    if user_id:
                        con.execute(
                            "INSERT INTO history (user_id, title, url) VALUES (?, ?, ?)",
                            (user_id, title, url)
                        )
                    else:
                        con.execute(
                            "INSERT INTO history (title, url) VALUES (?, ?)",
                            (title, url)
                        )
                    con.commit()
                    self.send_json(201, {"ok": True})
                finally:
                    con.close()
                
                self.audit_log("/api/history", "POST", 201, start_time)
                return
            
            # AI ask endpoint
            if path == "/api/ask":
                if not self.has_permission("ai"):
                    self.send_json(401, {"error": "Niet geauthoriseerd voor AI"})
                    self.audit_log("/api/ask", "POST", 401, start_time)
                    return
                
                prompt = str(body.get("prompt", ""))[:8000]
                system = str(body.get("system", "Je bent een AI-assistent. Antwoord in de taal van de gebruiker."))[:4000]
                context = str(body.get("context", ""))[:30_000]
                
                if not prompt:
                    self.send_json(400, {"error": "Prompt is verplicht"})
                    self.audit_log("/api/ask", "POST", 400, start_time)
                    return
                
                # Vaste gateway-URL: de client bepaalt nooit waarheen de server
                # zelf een verzoek stuurt (voorkomt SSRF naar het interne netwerk).
                gateway_url = os.environ.get("NEWLY_GATEWAY_URL", "http://127.0.0.1:8766/ask")
                
                try:
                    gateway_body = {
                        "prompt": prompt,
                        "system": system,
                        "context": context
                    }
                    
                    gateway_req = urllib.request.Request(
                        gateway_url,
                        data=json.dumps(gateway_body).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    
                    with urllib.request.urlopen(gateway_req, timeout=60) as resp:
                        gateway_data = json.loads(resp.read().decode())
                    
                    self.send_json(200, {
                        "answer": gateway_data.get("answer", ""),
                        "provider": gateway_data.get("provider", "unknown"),
                        "model": gateway_data.get("model", "unknown")
                    })
                    self.audit_log("/api/ask", "POST", 200, start_time)
                    
                except Exception:
                    self.send_json(502, {"error": "Gateway onbereikbaar"})
                    self.audit_log("/api/ask", "POST", 502, start_time)
                
                return
            
            # Add external service
            if path == "/api/services":
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api/services", "POST", 401, start_time)
                    return
                
                name = body.get("name")
                service_type = body.get("service_type")
                api_url = body.get("api_url")
                api_key = body.get("api_key", "")
                config = body.get("config", {})
                is_active = body.get("is_active", True)
                
                if not name or not service_type or not api_url:
                    self.send_json(400, {"error": "name, service_type en api_url zijn verplicht"})
                    self.audit_log("/api/services", "POST", 400, start_time)
                    return
                
                con = get_db_connection()
                try:
                    con.execute(
                        "INSERT INTO external_services (name, service_type, api_url, api_key, config, is_active) VALUES (?, ?, ?, ?, ?, ?)",
                        (name, service_type, api_url, api_key, json.dumps(config), is_active)
                    )
                    con.commit()
                    service_id = con.total_changes
                    self.send_json(201, {"ok": True, "id": service_id})
                finally:
                    con.close()
                
                self.audit_log("/api/services", "POST", 201, start_time)
                return
            
            # Add webhook
            if path == "/api/webhooks":
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log("/api/webhooks", "POST", 401, start_time)
                    return
                
                name = body.get("name")
                url = body.get("url")
                events = body.get("events", "")
                secret = body.get("secret", "")
                is_active = body.get("is_active", True)
                
                if not name or not url:
                    self.send_json(400, {"error": "name en url zijn verplicht"})
                    self.audit_log("/api/webhooks", "POST", 400, start_time)
                    return
                
                con = get_db_connection()
                try:
                    con.execute(
                        "INSERT INTO webhooks (name, url, events, secret, is_active) VALUES (?, ?, ?, ?, ?)",
                        (name, url, events, secret, is_active)
                    )
                    con.commit()
                    webhook_id = con.total_changes
                    self.send_json(201, {"ok": True, "id": webhook_id})
                finally:
                    con.close()
                
                self.audit_log("/api/webhooks", "POST", 201, start_time)
                return
            
            # 404 for unknown endpoints
            self.send_json(404, {"error": "Onbekend endpoint"})
            self.audit_log(path, "POST", 404, start_time)
            
        except Exception:
            if DEBUG:
                import traceback
                traceback.print_exc()
            self.send_json(500, {"error": "Interne serverfout"})
            self.audit_log(path, "POST", 500, start_time)

    def do_PUT(self):
        """Handle PUT requests."""
        start_time = datetime.now()
        
        if not self.check_rate():
            self.audit_log("rate-limited", "PUT", 429, start_time)
            return
        
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self.read_json() or {}
        
        try:
            # Update bookmark
            if path.startswith("/api/bookmarks/"):
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log(path, "PUT", 401, start_time)
                    return
                
                bookmark_id = path.split("/")[-1]
                url = body.get("url")
                title = body.get("title")
                
                if not url:
                    self.send_json(400, {"error": "URL is verplicht"})
                    self.audit_log(path, "PUT", 400, start_time)
                    return
                
                con = get_db_connection()
                try:
                    con.execute(
                        "UPDATE bookmarks SET title = ?, url = ? WHERE id = ?",
                        (title, url, bookmark_id)
                    )
                    con.commit()
                    self.send_json(200, {"ok": True})
                finally:
                    con.close()
                
                self.audit_log(path, "PUT", 200, start_time)
                return
            
            # Update service
            if path.startswith("/api/services/"):
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log(path, "PUT", 401, start_time)
                    return
                
                service_id = path.split("/")[-1]
                name = body.get("name")
                service_type = body.get("service_type")
                api_url = body.get("api_url")
                api_key = body.get("api_key")
                config = body.get("config")
                is_active = body.get("is_active")
                
                con = get_db_connection()
                try:
                    updates = []
                    params = []
                    if name is not None:
                        updates.append("name = ?")
                        params.append(name)
                    if service_type is not None:
                        updates.append("service_type = ?")
                        params.append(service_type)
                    if api_url is not None:
                        updates.append("api_url = ?")
                        params.append(api_url)
                    if api_key is not None:
                        updates.append("api_key = ?")
                        params.append(api_key)
                    if config is not None:
                        updates.append("config = ?")
                        params.append(json.dumps(config))
                    if is_active is not None:
                        updates.append("is_active = ?")
                        params.append(is_active)
                    
                    if updates:
                        params.append(service_id)
                        con.execute(
                            f"UPDATE external_services SET {', '.join(updates)} WHERE id = ?",
                            params
                        )
                        con.commit()
                    
                    self.send_json(200, {"ok": True})
                finally:
                    con.close()
                
                self.audit_log(path, "PUT", 200, start_time)
                return
            
            # 404 for unknown endpoints
            self.send_json(404, {"error": "Onbekend endpoint"})
            self.audit_log(path, "PUT", 404, start_time)
            
        except Exception:
            self.send_json(500, {"error": "Interne serverfout"})
            self.audit_log(path, "PUT", 500, start_time)

    def do_DELETE(self):
        """Handle DELETE requests."""
        start_time = datetime.now()
        
        if not self.check_rate():
            self.audit_log("rate-limited", "DELETE", 429, start_time)
            return
        
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        
        try:
            # Delete bookmark
            if path.startswith("/api/bookmarks/"):
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log(path, "DELETE", 401, start_time)
                    return
                
                bookmark_id = path.split("/")[-1]
                
                con = get_db_connection()
                try:
                    con.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
                    con.commit()
                    self.send_json(200, {"ok": True})
                finally:
                    con.close()
                
                self.audit_log(path, "DELETE", 200, start_time)
                return
            
            # Delete service
            if path.startswith("/api/services/"):
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log(path, "DELETE", 401, start_time)
                    return
                
                service_id = path.split("/")[-1]
                
                con = get_db_connection()
                try:
                    con.execute("DELETE FROM external_services WHERE id = ?", (service_id,))
                    con.commit()
                    self.send_json(200, {"ok": True})
                finally:
                    con.close()
                
                self.audit_log(path, "DELETE", 200, start_time)
                return
            
            # Delete webhook
            if path.startswith("/api/webhooks/"):
                if not self.has_permission("write"):
                    self.send_json(401, {"error": "Niet geauthoriseerd"})
                    self.audit_log(path, "DELETE", 401, start_time)
                    return
                
                webhook_id = path.split("/")[-1]
                
                con = get_db_connection()
                try:
                    con.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
                    con.commit()
                    self.send_json(200, {"ok": True})
                finally:
                    con.close()
                
                self.audit_log(path, "DELETE", 200, start_time)
                return
            
            # 404 for unknown endpoints
            self.send_json(404, {"error": "Onbekend endpoint"})
            self.audit_log(path, "DELETE", 404, start_time)
            
        except Exception:
            self.send_json(500, {"error": "Interne serverfout"})
            self.audit_log(path, "DELETE", 500, start_time)


def main():
    """Start de API server."""
    print("=" * 60)
    print("Climora API Server")
    print("=" * 60)
    print(f"Server draait op poort {API_PORT}")
    print(f"Authentatie: Bearer token of X-Client-ID/X-Client-Secret")
    
    if not API_KEY:
        print("WAARSCHUWING: NEWLY_API_KEY is niet ingesteld!")
        print("Zet omgevingsvariabele: export NEWLY_API_KEY='jouw-geheime-sleutel'")
        print("Zonder sleutel is er GEEN admin-toegang tot deze API.")
    else:
        print("Master API sleutel: ingesteld")
    
    print("=" * 60)
    print("Beschikbare endpoints:")
    print("  GET  /health           — Server status")
    print("  GET  /api             — API informatie")
    print("  GET  /api/bookmarks   — Haal bladwijzers op")
    print("  POST /api/bookmarks   — Voeg bladwijzer toe")
    print("  GET  /api/history      — Haal geschiedenis op")
    print("  POST /api/history      — Voeg geschiedenis toe")
    print("  POST /api/ask         — Stel vraag aan AI")
    print("  POST /api/clients     — Maak API client aan (admin)")
    print("  GET  /api/services    — Lijst externe services")
    print("  POST /api/services    — Voeg externe service toe")
    print("  GET  /api/stats       — Statistieken")
    print("=" * 60)
    
    # Laad API-sleutels uit database (secrets staan gehasht opgeslagen)
    global CLIENT_API_KEYS
    try:
        con = get_db_connection()
        try:
            con.execute("ALTER TABLE api_clients ADD COLUMN secret_is_hash INTEGER DEFAULT 0")
            con.commit()
        except sqlite3.OperationalError:
            pass
        rows = con.execute(
            "SELECT client_id, client_secret, name, permissions, rate_limit, secret_is_hash "
            "FROM api_clients").fetchall()
        for row in rows:
            secret_waarde = row["client_secret"] or ""
            if not row["secret_is_hash"]:
                # Legacy: plaintext secrets worden eenmalig gehasht
                secret_waarde = hash_secret(secret_waarde)
                con.execute(
                    "UPDATE api_clients SET client_secret = ?, secret_is_hash = 1 WHERE client_id = ?",
                    (secret_waarde, row["client_id"]))
                con.commit()
            CLIENT_API_KEYS[row["client_id"]] = {
                "secret_hash": secret_waarde,
                "name": row["name"],
                "permissions": row["permissions"],
                "rate_limit": row["rate_limit"]
            }
        con.close()
        save_api_keys(CLIENT_API_KEYS)
        print(f"Geladen: {len(CLIENT_API_KEYS)} API clients uit database")
    except Exception as e:
        print(f"Fout bij laden clients: {e}")
    
    # Start server
    try:
        ThreadingHTTPServer(("0.0.0.0", API_PORT), APIHandler).serve_forever()
    except KeyboardInterrupt:
        print("\nServer gestopt.")
    except Exception as e:
        print(f"Fout: {e}")


if __name__ == "__main__":
    main()
