#!/usr/bin/env python3
"""ZelfSync — multi-user sync-server voor Newly (draait op de Raspberry Pi 5).

Dit is de "Google-server" van de browser, maar dan van jou: per gebruiker
worden bookmarks en geschiedenis bewaard zodat alle apparaten synken.
Alleen Python-standaardbibliotheken + SQLite. Exact dezelfde code kan later
op een VPS draaien als de schaal groeit.

Start:      python3 server.py      (poort 8765, of ZELFSYNC_PORT=...)

Endpoints:
  GET  /health
  POST /register   {"username": ..., "password": ...}        -> {"token": ...}
  POST /login      {"username": ..., "password": ...}       -> {"token": ...}
  GET  /bookmarks                                           (Bearer token)
  POST /bookmarks  {"title": ..., "url": ...}
  GET  /history?limit=500
  POST /history     {"title": ..., "url": ...}
  GET  /export
"""
import hashlib
import json
import os
import re
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "zelfsync.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
MAX_BODY = 1_000_000
PORT = int(os.environ.get("ZELFSYNC_PORT", "8765"))


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


class Handler(BaseHTTPRequestHandler):
    server_version = "ZelfSync/0.1"

    # ---------- helpers ----------
    def send_json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
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
        con = connect()
        try:
            if self.path == "/health":
                self.send_json(200, {"status": "ok", "server": "zelfsync", "version": "0.1"})
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
    print("ZelfSync draait op poort %d (Ctrl+C om te stoppen)" % PORT)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("ZelfSync gestopt.")


if __name__ == "__main__":
    main()
