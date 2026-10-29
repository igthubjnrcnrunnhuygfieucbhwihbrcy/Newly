#!/usr/bin/env python3
"""ZelfGateway  lokale LLM-gateway voor Climora.

De browser praat alleen met deze gateway (localhost); de gateway praat met de
cloud-LLM-API met JOUW API-sleutel. Zo blijft de sleutel op het apparaat en is
de provider verwisselbaar (Mistral, OpenAI, Anthropic, Google, Claude, etc.).

Vereist:   export LLM_API_KEY="jouw-sleutel"
           export LLM_PROVIDER="mistral" (of openai, anthropic, google, etc.)
Start:      python3 server.py      (poort 8766, alleen 127.0.0.1)

Endpoints:
  GET  /health
  GET  /providers          Lijst van ondersteunde providers
  GET  /models             Beschikbare modellen per provider
  GET  /config             Huidige configuratie bekijken
  POST /ask               Stel een vraag aan de LLM
  POST /summarize         Vat tekst samen
  POST /chat              Chat-completie met geschiedenis
  POST /config/keys       Beheer API-sleutels per provider
"""
import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API_URL = os.environ.get("LLM_API_URL", "https://api.mistral.ai/v1/chat/completions")
API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "mistral-small-latest")
PROVIDER = os.environ.get("LLM_PROVIDER", "mistral").lower()
MAX_PROMPT = 60_000
PORT = int(os.environ.get("GATEWAY_PORT", "8766"))

# Configuratiebestand voor API-sleutels per provider
CONFIG_DIR = Path(__file__).resolve().parent / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "providers.json"

# Ondersteunde LLM providers
SUPPORTED_PROVIDERS = {
    "mistral": {
        "name": "Mistral AI",
        "api_url": "https://api.mistral.ai/v1/chat/completions",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "models": ["mistral-tiny", "mistral-small", "mistral-medium", "mistral-large", 
                   "mistral-small-latest", "mistral-medium-latest", "mistral-large-latest",
                   "mixtral-8x7b", "mixtral-8x22b", "codestral-latest"],
        "default_model": "mistral-small-latest",
        "supports_streaming": True
    },
    "openai": {
        "name": "OpenAI",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo", 
                   "gpt-3.5-turbo-16k", "gpt-3.5-turbo-instruct"],
        "default_model": "gpt-3.5-turbo",
        "supports_streaming": True
    },
    "anthropic": {
        "name": "Anthropic",
        "api_url": "https://api.anthropic.com/v1/messages",
        "api_key_header": "x-api-key",
        "api_key_prefix": "",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307", 
                   "claude-3-sonnet-20240229", "claude-3-opus-20240229",
                   "claude-2.1", "claude-2.0", "claude-instant-1.2"],
        "default_model": "claude-3-5-sonnet-20241022",
        "supports_streaming": True
    },
    "google": {
        "name": "Google Gemini",
        "api_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "api_key_header": "x-goog-api-key",
        "api_key_prefix": "",
        "models": ["gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-flash", 
                   "gemini-1.5-pro", "gemini-1.0-pro", "gemini-pro-vision"],
        "default_model": "gemini-2.0-flash",
        "supports_streaming": False
    },
    "groq": {
        "name": "Groq",
        "api_url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "models": ["llama-3.3-70b-versatile", "llama-3.2-90b-vision", "llama-3.2-11b-vision",
                   "llama3-70b-8192", "llama3-8b-8192", "mixtral-8x7b-32768",
                   "gemma2-9b-it", "gemma-7b-it"],
        "default_model": "llama-3.3-70b-versatile",
        "supports_streaming": True
    },
    "perplexity": {
        "name": "Perplexity",
        "api_url": "https://api.perplexity.ai/chat/completions",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "models": ["llama-3.3-70b-instruct", "llama-3.1-70b-instruct", "llama-3-70b-instruct",
                   "mixtral-8x7b-instruct", "sonar", "sonar-small", "sonar-pro"],
        "default_model": "llama-3.3-70b-instruct",
        "supports_streaming": True
    },
    "cohere": {
        "name": "Cohere",
        "api_url": "https://api.cohere.ai/v1/chat",
        "api_key_header": "Authorization",
        "api_key_prefix": "Bearer ",
        "models": ["command-r-plus", "command-r", "command", "command-light"],
        "default_model": "command-r-plus",
        "supports_streaming": True
    }
}


# Laad API-sleutels uit configuratiebestand
def load_api_keys():
    """Laad API-sleutels uit het configuratiebestand."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


# Sla API-sleutels op in configuratiebestand
def save_api_keys(keys):
    """Sla API-sleutels op in het configuratiebestand."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(keys, f, indent=2)
        # Zet permissies om veiligheid te waarborgen
        try:
            CONFIG_FILE.chmod(0o600)
        except:
            pass
    except IOError:
        pass


# Huidige API-sleutels
API_KEYS = load_api_keys()

# Voeg omgevingsvariabele toe aan API-sleutels als deze niet leeg is
if API_KEY and PROVIDER:
    if PROVIDER not in API_KEYS or not API_KEYS[PROVIDER]:
        API_KEYS[PROVIDER] = API_KEY


def get_provider_config(provider_name=None):
    """Get configuration for a specific provider or the current provider."""
    if provider_name is None:
        provider_name = PROVIDER
    
    if provider_name in SUPPORTED_PROVIDERS:
        return SUPPORTED_PROVIDERS[provider_name]
    
    # Default to Mistral
    return SUPPORTED_PROVIDERS["mistral"]


def get_api_url(provider_name=None):
    """Get the API URL for a provider."""
    config = get_provider_config(provider_name)
    return config["api_url"]


def get_api_key_header(provider_name=None):
    """Get the API key header name for a provider."""
    config = get_provider_config(provider_name)
    return config["api_key_header"]


def get_api_key_prefix(provider_name=None):
    """Get the API key prefix for a provider."""
    config = get_provider_config(provider_name)
    return config["api_key_prefix"]


def get_default_model(provider_name=None):
    """Get the default model for a provider."""
    config = get_provider_config(provider_name)
    return config["default_model"]


def get_models(provider_name=None):
    """Get available models for a provider."""
    config = get_provider_config(provider_name)
    return config["models"]


def get_all_providers():
    """Get list of all supported providers."""
    return {
        provider: {
            "name": info["name"],
            "models": info["models"],
            "default_model": info["default_model"],
            "supports_streaming": info["supports_streaming"]
        }
        for provider, info in SUPPORTED_PROVIDERS.items()
    }


def get_api_key_for_provider(provider_name):
    """Get the API key for a specific provider."""
    return API_KEYS.get(provider_name, "")


class Handler(BaseHTTPRequestHandler):
    server_version = "ZelfGateway/0.2"

    def log_message(self, fmt, *args):
        pass  # privacy: geen prompts of antwoorden in logs

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
        if length <= 0 or length > MAX_PROMPT:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {
                "status": "ok",
                "model": MODEL,
                "provider": PROVIDER,
                "key_set": bool(API_KEY),
                "version": "0.2",
                "providers_loaded": len(API_KEYS)
            })
        elif self.path == "/providers":
            self.send_json(200, {
                "providers": get_all_providers(),
                "current_provider": PROVIDER,
                "current_model": MODEL
            })
        elif self.path == "/models":
            provider = self.headers.get("X-Provider", PROVIDER)
            self.send_json(200, {
                "models": get_models(provider),
                "default": get_default_model(provider),
                "provider": provider
            })
        elif self.path == "/config":
            # Return current configuration
            provider_keys = {}
            for provider in SUPPORTED_PROVIDERS:
                key = get_api_key_for_provider(provider)
                if key:
                    provider_keys[provider] = {
                        "has_key": True,
                        "key_length": len(key)
                    }
                else:
                    provider_keys[provider] = {"has_key": False}
            
            self.send_json(200, {
                "current_provider": PROVIDER,
                "current_model": MODEL,
                "providers": provider_keys,
                "default_provider": PROVIDER
            })
        else:
            self.send_json(404, {"error": "onbekend endpoint"})

    def do_POST(self):
        body = self.read_json() or {}
        route = self.path.rstrip("/")
        
        try:
            # Handle API key management
            if route == "/config/keys":
                action = body.get("action", "get")
                
                if action == "set":
                    provider = body.get("provider")
                    api_key = body.get("key", "")
                    
                    if not provider:
                        self.send_json(400, {"error": "provider ontbreekt"})
                        return
                    
                    if not api_key:
                        self.send_json(400, {"error": "API-sleutel ontbreekt"})
                        return
                    
                    if provider not in SUPPORTED_PROVIDERS:
                        self.send_json(400, {"error": f"Ondersteunde providers: {', '.join(SUPPORTED_PROVIDERS.keys())}"})
                        return
                    
                    API_KEYS[provider] = api_key
                    save_api_keys(API_KEYS)
                    self.send_json(200, {"ok": True, "provider": provider})
                    return
                
                elif action == "remove":
                    provider = body.get("provider")
                    
                    if not provider:
                        self.send_json(400, {"error": "provider ontbreekt"})
                        return
                    
                    if provider in API_KEYS:
                        del API_KEYS[provider]
                        save_api_keys(API_KEYS)
                    
                    self.send_json(200, {"ok": True, "provider": provider})
                    return
                
                elif action == "get":
                    provider = body.get("provider", PROVIDER)
                    key = get_api_key_for_provider(provider)
                    
                    self.send_json(200, {
                        "provider": provider,
                        "has_key": bool(key),
                        "key_length": len(key) if key else 0
                    })
                    return
                
                else:
                    self.send_json(400, {"error": f"Onbekende actie: {action}. Gebruik: get, set, remove"})
                    return
            
            # Get provider and model from request
            provider = body.get("provider") or PROVIDER
            model = body.get("model") or MODEL
            api_key = get_api_key_for_provider(provider)
            
            if not api_key:
                self.send_json(500, {"error": f"Geen API-sleutel ingesteld voor provider '{provider}'. Gebruik /config/keys om een sleutel toe te voegen."})
                return
            
            # Store API key temporarily for this request
            temp_api_key = API_KEY
            API_KEY = api_key
            
            try:
                if route == "/ask":
                    system = str(body.get("system",
                        "Je bent de assistent van de Climora-browser. Antwoord kort en in de taal van de gebruiker."))
                    messages = [{"role": "system", "content": system}]
                    context = str(body.get("context", ""))[:MAX_PROMPT]
                    if context:
                        messages.append({"role": "system",
                                         "content": "Context van de huidige pagina:" + context})
                    messages.append({"role": "user", "content": str(body.get("prompt", ""))[:MAX_PROMPT]})
                    
                    answer = call_llm(messages, provider, model)
                    self.send_json(200, {"answer": answer, "provider": provider, "model": model})
                    return
                
                if route == "/summarize":
                    text = str(body.get("text", ""))[:MAX_PROMPT]
                    try:
                        max_words = int(body.get("max_words", 120))
                    except (TypeError, ValueError):
                        max_words = 120
                    
                    system_prompt = (f"Vat de tekst samen in max {max_words} woorden, "
                                   "in de taal van de tekst. Wees accuraat en beknopt.")
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ]
                    answer = call_llm(messages, provider, model)
                    self.send_json(200, {"answer": answer, "provider": provider, "model": model})
                    return
                
                if route == "/chat":
                    # Chat completion with conversation history
                    messages = body.get("messages", [])
                    if not messages:
                        self.send_json(400, {"error": "messages ontbreekt"})
                        return
                    
                    # Limit message count to prevent token overflow
                    if len(messages) > 20:
                        messages = messages[-20:]
                    
                    answer = call_llm(messages, provider, model)
                    self.send_json(200, {
                        "answer": answer,
                        "provider": provider,
                        "model": model
                    })
                    return
                
                self.send_json(404, {"error": "onbekend endpoint"})
            
            finally:
                # Restore original API key
                API_KEY = temp_api_key
        
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})


def call_llm(messages, provider_name=None, model=None):
    """Call the LLM API with the given messages."""
    config = get_provider_config(provider_name)
    api_url = config["api_url"]
    api_key = get_api_key_for_provider(provider_name)
    
    # Replace {model} placeholder in URL if present
    if "{model}" in api_url and model:
        api_url = api_url.replace("{model}", model)
    elif "{model}" in api_url:
        api_url = api_url.replace("{model}", config["default_model"])
    
    # Build headers
    headers = {
        "Content-Type": "application/json",
        get_api_key_header(provider_name): get_api_key_prefix(provider_name) + api_key
    }
    
    # Build payload based on provider
    payload = build_payload(messages, provider_name, model)
    
    # Make the request
    payload_bytes = json.dumps(payload).encode()
    req = urllib.request.Request(api_url, data=payload_bytes, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        # Extract response based on provider
        return extract_response(data, provider_name)
    except urllib.error.HTTPError as e:
        error_data = e.read().decode("utf-8")
        try:
            error_json = json.loads(error_data)
            error_msg = error_json.get("error", {}).get("message", str(error_json))
        except:
            error_msg = error_data
        raise Exception(f"API error {e.code}: {error_msg}")


def build_payload(messages, provider_name=None, model=None):
    """Build the API payload based on the provider."""
    config = get_provider_config(provider_name)
    
    if provider_name == "google":
        # Google Gemini format
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                # System messages go in the first user message for Google
                if contents and contents[0].get("role") == "user":
                    contents[0]["parts"][0]["text"] = content + "\n\n" + contents[0]["parts"][0]["text"]
                else:
                    contents.append({
                        "role": "user",
                        "parts": [{"text": content}]
                    })
            else:
                contents.append({
                    "role": role,
                    "parts": [{"text": content}]
                })
        
        return {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4096
            }
        }
    
    elif provider_name == "anthropic":
        # Anthropic format
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                anthropic_messages.append({
                    "role": "user",
                    "content": content
                })
            else:
                anthropic_messages.append({
                    "role": role,
                    "content": content
                })
        
        return {
            "model": model or config["default_model"],
            "messages": anthropic_messages,
            "max_tokens": 4096,
            "temperature": 0.7
        }
    
    else:
        # Standard OpenAI-compatible format (Mistral, OpenAI, Groq, Perplexity, Cohere)
        return {
            "model": model or config["default_model"],
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096
        }


def extract_response(data, provider_name=None):
    """Extract the response text from the API response based on provider."""
    if provider_name == "google":
        # Google Gemini response format
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            return str(data)
    
    elif provider_name == "anthropic":
        # Anthropic response format
        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError):
            return str(data)
    
    elif provider_name == "cohere":
        # Cohere response format
        try:
            return data["generations"][0]["text"]
        except (KeyError, IndexError):
            return str(data)
    
    else:
        # Standard OpenAI-compatible format
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return str(data)


def main():
    print("ZelfGateway op poort %d, provider: %s, model: %s, sleutel ingesteld: %s" % 
          (PORT, PROVIDER, MODEL, bool(API_KEY)))
    print("Ondersteunde providers:", ", ".join(SUPPORTED_PROVIDERS.keys()))
    print("Gebruik /config/keys endpoint om API-sleutels toe te voegen")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
