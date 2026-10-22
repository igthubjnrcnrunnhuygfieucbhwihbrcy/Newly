#!/usr/bin/env python3
"""ZelfGateway — lokale LLM-gateway voor Newly.

De browser praat alleen met deze gateway (localhost); de gateway praat met de
cloud-LLM-API met JOUW API-sleutel. Zo blijft de sleutel op het apparaat en is
de provider verwisselbaar (Mistral, OpenAI-compatibel, later lokaal).

Vereist:   export LLM_API_KEY="jouw-sleutel"
Start:      python3 server.py      (poort 8766, alleen 127.0.0.1)

Endpoints:
  GET  /health
  POST /ask        {"prompt": "...", "context": "...", "system": "..."}
  POST /summarize  {"text": "...", "max_words": 120}
"""
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_URL = os.environ.get("LLM_API_URL", "https://api.mistral.ai/v1/chat/completions")
API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "mistral-small-latest")
MAX_PROMPT = 60_000
PORT = int(os.environ.get("GATEWAY_PORT", "8766"))


def call_llm(messages):
    payload = json.dumps({"model": MODEL, "messages": messages}).encode()
    req = urllib.request.Request(API_URL, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + API_KEY,
    }, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


class Handler(BaseHTTPRequestHandler):
    server_version = "ZelfGateway/0.1"

    def log_message(self, fmt, *args):
        pass  # privacy: geen prompts of antwoorden in logs

    def send_json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_PROMPT:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "model": MODEL, "key_set": bool(API_KEY)})
        else:
            self.send_json(404, {"error": "onbekend endpoint"})

    def do_POST(self):
        body = self.read_json() or {}
        if not API_KEY:
            self.send_json(500, {"error": "LLM_API_KEY is niet ingesteld"})
            return
        route = self.path.rstrip("/")
        try:
            if route == "/ask":
                system = str(body.get("system",
                    "Je bent de assistent van de Newly-browser. Antwoord kort en in de taal van de gebruiker."))
                messages = [{"role": "system", "content": system}]
                context = str(body.get("context", ""))[:MAX_PROMPT]
                if context:
                    messages.append({"role": "system",
                                     "content": "Context van de huidige pagina:" + context})
                messages.append({"role": "user", "content": str(body.get("prompt", ""))[:MAX_PROMPT]})
                self.send_json(200, {"answer": call_llm(messages)})
                return
            if route == "/summarize":
                text = str(body.get("text", ""))[:MAX_PROMPT]
                try:
                    max_words = int(body.get("max_words", 120))
                except (TypeError, ValueError):
                    max_words = 120
                answer = call_llm([
                    {"role": "system",
                     "content": "Vat de tekst samen in max %d woorden, in de taal van de tekst." % max_words},
                    {"role": "user", "content": text}])
                self.send_json(200, {"answer": answer})
                return
            self.send_json(404, {"error": "onbekend endpoint"})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})


def main():
    print("ZelfGateway op poort %d, model: %s, sleutel ingesteld: %s" % (PORT, MODEL, bool(API_KEY)))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
