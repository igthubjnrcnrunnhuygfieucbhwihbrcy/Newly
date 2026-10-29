#!/usr/bin/env python3
"""Climora Sync-Server Extensions  Uitbreidingen voor externe services en leveranciers.

Deze module voegt functionaliteit toe aan de sync-server voor:
- Integreert met externe API's en services
- Beheer van webhooks
- Uitgebreide zoekfunctionaliteit
- Content aggregatie van meerdere bronnen

Gebruik: Voeg endpoints toe aan de hoofd server.py of gebruik als aparte service.
"""
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# Database configuratie
DB_PATH = Path(__file__).resolve().parent / "data" / "zelfsync.db"


def get_db_connection():
    """Maak verbinding met SQLite database."""
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    return con


# External Service Types
SUPPORTED_SERVICE_TYPES = {
    "news": {
        "name": "Nieuws Aggregator",
        "description": "Aggregatie van nieuwsbronnen",
        "config_fields": ["sources", "categories", "update_interval"],
        "endpoints": ["/news", "/news/sources", "/news/categories"]
    },
    "weather": {
        "name": "Weer Service",
        "description": "Weersinformatie van externe providers",
        "config_fields": ["api_key", "location", "units"],
        "endpoints": ["/weather", "/weather/forecast"]
    },
    "calendar": {
        "name": "Kalender Service",
        "description": "Integreer met externe kalenders",
        "config_fields": ["api_key", "calendar_id"],
        "endpoints": ["/calendar", "/calendar/events"]
    },
    "translation": {
        "name": "Vertaal Service",
        "description": "Vertaalfunctionaliteit",
        "config_fields": ["api_key", "default_language"],
        "endpoints": ["/translate", "/translate/languages"]
    },
    "social": {
        "name": "Social Media",
        "description": "Integreer met sociale media platforms",
        "config_fields": ["api_key", "api_secret", "access_token"],
        "endpoints": ["/social/posts", "/social/feeds"]
    },
    "storage": {
        "name": "Opslag Service",
        "description": "Externe opslag (Google Drive, Dropbox, etc.)",
        "config_fields": ["api_key", "client_id", "client_secret"],
        "endpoints": ["/storage/files", "/storage/upload", "/storage/download"]
    }
}


class ExternalServiceManager:
    """Beheer externe services en integraties."""
    
    def __init__(self, user_id=None):
        self.user_id = user_id
    
    def add_service(self, name, service_type, config, is_active=True):
        """Voeg een externe service toe."""
        if service_type not in SUPPORTED_SERVICE_TYPES:
            raise ValueError(f"Ondersteunde service types: {', '.join(SUPPORTED_SERVICE_TYPES.keys())}")
        
        con = get_db_connection()
        try:
            con.execute(
                "INSERT INTO external_services (user_id, name, service_type, config, is_active) VALUES (?, ?, ?, ?, ?)",
                (self.user_id, name, service_type, json.dumps(config), is_active)
            )
            con.commit()
            return con.total_changes
        finally:
            con.close()
    
    def get_services(self):
        """Haal alle services voor een gebruiker op."""
        con = get_db_connection()
        try:
            if self.user_id:
                rows = con.execute(
                    "SELECT id, name, service_type, config, is_active, created_at FROM external_services WHERE user_id = ? ORDER BY created_at DESC",
                    (self.user_id,)
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT id, name, service_type, config, is_active, created_at FROM external_services ORDER BY created_at DESC"
                ).fetchall()
            
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "service_type": row["service_type"],
                    "config": json.loads(row["config"]) if row["config"] else {},
                    "is_active": bool(row["is_active"]),
                    "created_at": row["created_at"]
                }
                for row in rows
            ]
        finally:
            con.close()
    
    def get_service(self, service_id):
        """Haal een specifieke service op."""
        con = get_db_connection()
        try:
            row = con.execute(
                "SELECT id, name, service_type, config, is_active FROM external_services WHERE id = ?",
                (service_id,)
            ).fetchone()
            
            if row:
                return {
                    "id": row["id"],
                    "name": row["name"],
                    "service_type": row["service_type"],
                    "config": json.loads(row["config"]) if row["config"] else {},
                    "is_active": bool(row["is_active"])
                }
            return None
        finally:
            con.close()
    
    def update_service(self, service_id, name=None, config=None, is_active=None):
        """Update een service."""
        con = get_db_connection()
        try:
            updates = []
            params = []
            
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if config is not None:
                updates.append("config = ?")
                params.append(json.dumps(config))
            if is_active is not None:
                updates.append("is_active = ?")
                params.append(is_active)
            
            if updates:
                params.append(service_id)
                if self.user_id:
                    params.append(self.user_id)
                    con.execute(
                        f"UPDATE external_services SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                        params
                    )
                else:
                    con.execute(
                        f"UPDATE external_services SET {', '.join(updates)} WHERE id = ?",
                        params
                    )
                con.commit()
                return True
            return False
        finally:
            con.close()
    
    def delete_service(self, service_id):
        """Verwijder een service."""
        con = get_db_connection()
        try:
            if self.user_id:
                con.execute(
                    "DELETE FROM external_services WHERE id = ? AND user_id = ?",
                    (service_id, self.user_id)
                )
            else:
                con.execute(
                    "DELETE FROM external_services WHERE id = ?",
                    (service_id,)
                )
            con.commit()
            return con.total_changes > 0
        finally:
            con.close()
    
    def call_service(self, service_id, endpoint, data=None):
        """Roep een externe service endpoint aan."""
        service = self.get_service(service_id)
        if not service or not service["is_active"]:
            raise ValueError("Service niet gevonden of niet actief")
        
        service_type = service["service_type"]
        config = service["config"]
        
        if service_type not in SUPPORTED_SERVICE_TYPES:
            raise ValueError(f"Ondersteunde service types: {', '.join(SUPPORTED_SERVICE_TYPES.keys())}")
        
        # Bouw de request op basis van service type
        if service_type == "news":
            return self._call_news_service(config, endpoint, data)
        elif service_type == "weather":
            return self._call_weather_service(config, endpoint, data)
        elif service_type == "translation":
            return self._call_translation_service(config, endpoint, data)
        else:
            raise NotImplementedError(f"Service type {service_type} niet geimplementeerd")
    
    def _call_news_service(self, config, endpoint, data):
        """Roep nieuws service aan."""
        # Voorbeeld: Integreer met NewsAPI
        sources = config.get("sources", [])
        api_key = config.get("api_key", "")
        
        if endpoint == "/news":
            # Haal nieuws op
            category = data.get("category", "general") if data else "general"
            country = data.get("country", "nl") if data else "nl"
            
            url = f"https://newsapi.org/v2/top-headlines?country={country}&category={category}&apiKey={api_key}"
            
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                return {"error": str(e), "source": "newsapi"}
        
        return {"error": f"Onbekend endpoint: {endpoint}"}
    
    def _call_weather_service(self, config, endpoint, data):
        """Roep weer service aan."""
        api_key = config.get("api_key", "")
        location = config.get("location", "Amsterdam")
        units = config.get("units", "metric")
        
        if endpoint == "/weather":
            # Huidig weer
            url = f"https://api.openweathermap.org/data/2.5/weather?q={location}&units={units}&appid={api_key}"
            
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                return {"error": str(e), "source": "openweathermap"}
        
        elif endpoint == "/weather/forecast":
            # Weersvoorspelling
            url = f"https://api.openweathermap.org/data/2.5/forecast?q={location}&units={units}&appid={api_key}"
            
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                return {"error": str(e), "source": "openweathermap"}
        
        return {"error": f"Onbekend endpoint: {endpoint}"}
    
    def _call_translation_service(self, config, endpoint, data):
        """Roep vertaal service aan."""
        api_key = config.get("api_key", "")
        default_lang = config.get("default_language", "en")
        
        if endpoint == "/translate":
            text = data.get("text", "") if data else ""
            target_lang = data.get("target_language", default_lang)
            source_lang = data.get("source_language", "auto")
            
            # Gebruik Google Translate API (vereist api_key)
            url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
            
            payload = {
                "q": text,
                "target": target_lang,
                "source": source_lang if source_lang != "auto" else None,
                "format": "text"
            }
            
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                return {"error": str(e), "source": "google-translate"}
        
        elif endpoint == "/translate/languages":
            # Haal ondersteunde talen op
            return {
                "languages": [
                    {"code": "nl", "name": "Nederlands"},
                    {"code": "en", "name": "Engels"},
                    {"code": "fr", "name": "Frans"},
                    {"code": "de", "name": "Duits"},
                    {"code": "es", "name": "Spaans"},
                    {"code": "it", "name": "Italiaans"}
                ]
            }
        
        return {"error": f"Onbekend endpoint: {endpoint}"}


class WebhookManager:
    """Beheer webhooks voor events."""
    
    SUPPORTED_EVENTS = [
        "bookmark.added",
        "bookmark.removed",
        "history.added",
        "user.login",
        "user.logout",
        "ai.request",
        "search.performed"
    ]
    
    def __init__(self, user_id=None):
        self.user_id = user_id
    
    def add_webhook(self, name, url, events, secret=None, is_active=True):
        """Voeg een webhook toe."""
        # Valideer events
        for event in events:
            if event not in self.SUPPORTED_EVENTS:
                raise ValueError(f"Ondersteunde events: {', '.join(self.SUPPORTED_EVENTS)}")
        
        con = get_db_connection()
        try:
            con.execute(
                "INSERT INTO webhooks (user_id, name, url, events, secret, is_active) VALUES (?, ?, ?, ?, ?, ?)",
                (self.user_id, name, url, ",".join(events), secret, is_active)
            )
            con.commit()
            return con.total_changes
        finally:
            con.close()
    
    def get_webhooks(self):
        """Haal alle webhooks op."""
        con = get_db_connection()
        try:
            if self.user_id:
                rows = con.execute(
                    "SELECT id, name, url, events, secret, is_active, created_at FROM webhooks WHERE user_id = ? ORDER BY created_at DESC",
                    (self.user_id,)
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT id, name, url, events, secret, is_active, created_at FROM webhooks ORDER BY created_at DESC"
                ).fetchall()
            
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "url": row["url"],
                    "events": row["events"].split(",") if row["events"] else [],
                    "has_secret": bool(row["secret"]),
                    "is_active": bool(row["is_active"]),
                    "created_at": row["created_at"]
                }
                for row in rows
            ]
        finally:
            con.close()
    
    def trigger_webhook(self, event, data):
        """Activeer alle webhooks voor een specifiek event."""
        con = get_db_connection()
        try:
            # Haal actieve webhooks op voor dit event
            rows = con.execute(
                "SELECT id, url, secret FROM webhooks WHERE is_active = 1 AND events LIKE ?",
                (f"%{event}%",)
            ).fetchall()
            
            results = []
            for row in rows:
                try:
                    payload = {
                        "event": event,
                        "timestamp": datetime.now().isoformat(),
                        "data": data
                    }
                    
                    headers = {
                        "Content-Type": "application/json",
                        "User-Agent": "Climora-Webhook/1.0"
                    }
                    
                    if row["secret"]:
                        # Voeg signature header toe voor verificatie
                        import hmac
                        import hashlib
                        signature = hmac.new(
                            row["secret"].encode(),
                            json.dumps(payload).encode(),
                            hashlib.sha256
                        ).hexdigest()
                        headers["X-Climora-Signature"] = signature
                    
                    req = urllib.request.Request(
                        row["url"],
                        data=json.dumps(payload).encode(),
                        headers=headers,
                        method="POST"
                    )
                    
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        results.append({
                            "webhook_id": row["id"],
                            "status": "success",
                            "status_code": resp.status
                        })
                except Exception as e:
                    results.append({
                        "webhook_id": row["id"],
                        "status": "error",
                        "error": str(e)
                    })
            
            return results
        finally:
            con.close()
    
    def delete_webhook(self, webhook_id):
        """Verwijder een webhook."""
        con = get_db_connection()
        try:
            if self.user_id:
                con.execute(
                    "DELETE FROM webhooks WHERE id = ? AND user_id = ?",
                    (webhook_id, self.user_id)
                )
            else:
                con.execute(
                    "DELETE FROM webhooks WHERE id = ?",
                    (webhook_id,)
                )
            con.commit()
            return con.total_changes > 0
        finally:
            con.close()


class ContentAggregator:
    """Aggregatie van content van meerdere bronnen."""
    
    def __init__(self):
        self.services = {}
    
    def add_source(self, name, service_type, config):
        """Voeg een content bron toe."""
        self.services[name] = {
            "service_type": service_type,
            "config": config
        }
    
    def aggregate(self, query, source_types=None):
        """Aggregatie van content van meerdere bronnen."""
        results = []
        
        for name, service in self.services.items():
            if source_types and service["service_type"] not in source_types:
                continue
            
            try:
                if service["service_type"] == "news":
                    # Zoek in nieuwsbronnen
                    service_manager = ExternalServiceManager()
                    result = service_manager.call_service(
                        name, 
                        "/news", 
                        {"query": query}
                    )
                    if "articles" in result:
                        results.extend(result["articles"])
                
                elif service["service_type"] == "web":
                    # Zoek op het web via de proxy
                    # (Implementatie afhankelijk van de sync-server proxy)
                    pass
                    
            except Exception as e:
                # Log fout maar ga door
                if "error" not in str(e).lower():
                    results.append({
                        "source": name,
                        "error": str(e)
                    })
        
        # Sorteer resultaten op relevantie/datum
        results.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
        
        return results[:50]  # Beperk tot 50 resultaten


# Helper functies voor de hoofd server
def get_supported_service_types():
    """Haal ondersteunde service types op."""
    return {
        service_type: {
            "name": info["name"],
            "description": info["description"],
            "config_fields": info["config_fields"],
            "endpoints": info["endpoints"]
        }
        for service_type, info in SUPPORTED_SERVICE_TYPES.items()
    }


def get_supported_events():
    """Haal ondersteunde events op."""
    return WebhookManager.SUPPORTED_EVENTS


if __name__ == "__main__":
    # Test de extensions
    print("Climora Sync-Server Extensions")
    print("=" * 50)
    
    # Toon ondersteunde service types
    print("\nOndersteunde Service Types:")
    for service_type, info in SUPPORTED_SERVICE_TYPES.items():
        print(f"  - {service_type}: {info['name']}")
    
    # Toon ondersteunde events
    print("\nOndersteunde Events:")
    for event in get_supported_events():
        print(f"  - {event}")
    
    print("\nGebruik: Import deze module in server.py")
