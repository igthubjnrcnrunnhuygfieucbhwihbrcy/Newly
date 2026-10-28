# Newly  Eigen Browser met AI-Agent

**Newly** is een eigen, Chromium-gebaseerde browser met een ingebouwde AI-agent. Local-first: het browsen gebeurt volledig op de hardware van de gebruiker (laptop/telefoon). Een Raspberry Pi 5 doet optioneel de rol van sync-server  zoals Google en Brave dat voor hun browser doen, maar dan bij jou thuis.

## [1mNieuwe Functionaliteit [0m

### [32m✨ Verbeterde UI & UX[0m
- **Consistentere stijling** met moderne kleurenschema's
- **Betere pictogrammen** met Font Awesome 6.5.1
- **Verbeterd tabbeheer** met favicons op basis van URL
- **Instellingenpaneel** voor AI-provider configuratie
- **Responsive design** voor betere mobiele ervaring
- **Toast notificaties** voor feedback aan de gebruiker

### [36m🤖 Multi-Provider AI Gateway[0m
De gateway ondersteunt nu **8 verschillende LLM providers**:

| Provider | Modellen | API Type |
|----------|----------|----------|
| **Mistral AI** | mistral-tiny, mistral-small, mistral-medium, mistral-large, mixtral-8x7b, codestral | OpenAI-compatibel |
| **OpenAI** | gpt-4o-mini, gpt-4o, gpt-4-turbo, gpt-4, gpt-3.5-turbo | OpenAI |
| **Anthropic** | claude-3-5-sonnet, claude-3-haiku, claude-3-sonnet, claude-3-opus | Anthropic |
| **Google** | gemini-2.0-flash, gemini-2.0-pro, gemini-1.5-pro | Google Cloud |
| **Groq** | llama-3.3-70b, llama-3.2-90b, mixtral-8x7b | OpenAI-compatibel |
| **Perplexity** | llama-3.3-70b-instruct, sonar, sonar-pro | OpenAI-compatibel |
| **Cohere** | command-r-plus, command-r, command | Cohere |

**Nieuwe Gateway Endpoints:**
```
GET  /providers          Lijst van ondersteunde providers
GET  /models             Beschikbare modellen per provider
GET  /config             Huidige configuratie bekijken
POST /config/keys       Beheer API-sleutels per provider
POST /chat              Chat-completie met geschiedenis
```

### [33m🔌 Eigen REST API Server[0m

Nieuwe **api_server.py** biedt een volwaardige REST API voor externe toegang:

**Endpoints:**
```
GET  /health            Server status
GET  /api              API informatie
GET  /api/bookmarks    Haal bladwijzers op
POST /api/bookmarks    Voeg bladwijzer toe
GET  /api/history       Haal geschiedenis op
POST /api/history       Voeg geschiedenis toe
POST /api/ask          Stel vraag aan AI (doorverwijst naar gateway)
POST /api/clients      Maak API client aan (admin)
GET  /api/services     Lijst externe services
POST /api/services     Voeg externe service toe
GET  /api/stats        Statistieken
```

**Authentatie:**
- **Master API Key**: `Authorization: Bearer <NEWLY_API_KEY>`
- **Client Credentials**: `X-Client-ID` en `X-Client-Secret` headers

**Start de API Server:**
```bash
cd sync-server
export NEWLY_API_KEY="jouw-geheime-sleutel"
export NEWLY_API_PORT=8767
python3 api_server.py
```

### [35m🌐 Externe Services & Integraties[0m

De **extensions.py** module biedt uitbreidingen voor:

- **Externe Service Beheer**
  - Nieuws aggregators (NewsAPI)
  - Weerservices (OpenWeatherMap)
  - Vertaalservices (Google Translate)
  - Sociale media integraties
  - Cloud opslag (Google Drive, Dropbox)

- **Webhook Ondersteuning**
  - Event-driven notificaties
  - Ondersteunde events: `bookmark.added`, `bookmark.removed`, `history.added`, `user.login`, `ai.request`, etc.

- **Content Aggregatie**
  - Zoek in meerdere bronnen tegelijk
  - Resultaten combineren en sorteren

### [34m📱 Verbeterde Web UI[0m

De **web/index.html** biedt nu:
- **AI Assistent Interface** met gespreksgeschiedenis
- **Provider selectie** voor verschillende LLM's
- **Model selectie** per provider
- **Gateway status monitoring**
- **Responsive design** voor alle schermgroottes

## Architectuur

```
+---------------------- Gebruikersapparaten (laptop / telefoon) ----------------------+
|                                                                                      |
|   browser/  (Electron + Chromium)            web/  (browser-in-browser, fase 5)     |
|        |  CDP = Chrome DevTools Protocol          |  fetch / WebSocket                |
|        v                                           v                                 |
|   agent/   (MCP-brug, fase 3)  --->  gateway/  (LLM-gateway: multi-provider        |
|   laat de LLM navigeren, klikken,               met ondersteuning voor 8+ providers) |
|   lezen, screenshots maken                                                     |
+--------------------------------------------------------------------------------------+
                                     | optioneel: alleen sync + webproxy
                                     v
              sync-server/  op Raspberry Pi 5  (ZelfSync: multi-user accounts,
              bookmarks + geschiedenis, zelfde code draait later ook op een VPS)
                                     |
                                     v
              api_server/   op Raspberry Pi 5  (REST API voor externe toegang)
```

## Onderdelen

- **browser/**  Electron-schil met tabs, adresbalk, AI-instellingen en CDP-agenthook
- **agent/**  Ontwerp voor de MCP-server die de LLM toegang tot de browser geeft
- **gateway/**  Lokale LLM-gateway met ondersteuning voor meerdere providers
- **sync-server/**  ZelfSync: werkende multi-user sync-service + webproxy
- **sync-server/api_server.py**  Eigen REST API voor externe integraties
- **sync-server/extensions.py**  Uitbreidingen voor externe services
- **web/**  Web-UI met AI-assistent en provider selectie

## Snel Starten

### Electron Browser

```bash
cd browser
npm install
npm start
```

### LLM Gateway (Meerdere Providers)

```bash
cd gateway
# Kies je provider
export LLM_PROVIDER="mistral"  # of openai, anthropic, google, groq, etc.
export LLM_API_KEY="jouw-sleutel"
export LLM_MODEL="mistral-small-latest"  # optioneel
python3 server.py            # poort 8766, alleen localhost
```

**Meerdere API-sleutels beheer via de API:**
```bash
# Voeg een sleutel toe voor Mistral
curl -X POST http://localhost:8766/config/keys \
  -H "Content-Type: application/json" \
  -d '{"action": "set", "provider": "mistral", "key": "jouw-mistral-sleutel"}'

# Voeg een sleutel toe voor OpenAI
curl -X POST http://localhost:8766/config/keys \
  -H "Content-Type: application/json" \
  -d '{"action": "set", "provider": "openai", "key": "jouw-openai-sleutel"}'

# Bekijk configuratie
curl http://localhost:8766/config
```

### Sync-Server op Raspberry Pi 5

```bash
cd sync-server
python3 server.py            # poort 8765
curl http://localhost:8765/health
```

### API Server (Nieuw!)

```bash
cd sync-server
# Stel master API sleutel in
export NEWLY_API_KEY="jouw-geheime-api-sleutel"
export NEWLY_API_PORT=8767
python3 api_server.py

# Test de API
curl -H "Authorization: Bearer jouw-geheime-api-sleutel" http://localhost:8767/health
```

## De Raspberry Pi 5 als Sync-Server

ZelfSync is de "Google-server" van deze browser, maar dan van jou: kleine API-service die per gebruiker bookmarks, geschiedenis en instellingen bewaart zodat al je apparaten synchen. Dit is lichtgewicht werk (JSON-records + SQLite): een Pi 5 met SSD doet dit ruim voor honderden gebruikers. Bereik je een echt grote schaal, dan verhuist exact dezelfde code naar een VPS.

### Installeren als Service (systemd)

```bash
# Voor sync-server
sudo cp zelfsync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zelfsync

# Voor api-server (maak een nieuw service bestand)
cat > /etc/systemd/system/newly-api.service << 'EOF'
[Unit]
Description=Newly API Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/path/to/Newly/sync-server
ExecStart=/usr/bin/python3 /path/to/Newly/sync-server/api_server.py
Environment=NEWLY_API_KEY=jouw-geheime-sleutel
Environment=NEWLY_API_PORT=8767
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now newly-api
```

Zet daarna port-forwarding of een reverse proxy (Caddy/nginx met HTTPS) voor bereik van buitenaf.

## Roadmap

Zie ROADMAP.md voor de fasen 1 t/m 6.

### Toekomstige Uitbreidingen

- [ ] **Streaming responses** voor real-time AI interactie
- [ ] **Lokale modellen** (LLama, Mistral) ondersteuning
- [ ] **Plug-in systeem** voor custom integraties
- [ ] **Android app** met WebView
- [ ] **iOS app** (WebKit beperkingen)
- [ ] **Browser extensies** voor Chrome/Firefox
- [ ] **Voice interface** voor spraakgestuurd browsen

## Veiligheid

- De LLM-API-sleutel blijft op het apparaat; de gateway luistert alleen op 127.0.0.1
- De agent krijgt per-permissie toegang tot de browser (fase 3): "wel lezen, niet klikken" moet kunnen
- ZelfSync hasht wachtwoorden met PBKDF2 en werkt met bearer-tokens; zet er altijd TLS voor (reverse proxy)
- Logs van de gateway bevatten bewust geen prompt-inhoud
- API-sleutels worden versleuteld opgeslagen met beperkte permissies (600)

## API Documentatie

### Gateway API (poort 8766)

```
GET  /health               Server status
GET  /providers           Lijst van ondersteunde providers
GET  /models              Beschikbare modellen per provider
GET  /config              Huidige configuratie
POST /ask                Stel een vraag
POST /summarize          Vat tekst samen
POST /chat               Chat-completie
POST /config/keys        Beheer API-sleutels
```

**Voorbeeld: Stel een vraag aan Mistral**
```bash
curl -X POST http://localhost:8766/ask \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Wat is de hoofdstad van Nederland?",
    "provider": "mistral",
    "model": "mistral-small-latest"
  }'
```

### API Server (poort 8767)

```
GET  /health               Server status
GET  /api                 API informatie
GET  /api/bookmarks       Haal bladwijzers op
POST /api/bookmarks       Voeg bladwijzer toe
GET  /api/history          Haal geschiedenis op
POST /api/history          Voeg geschiedenis toe
POST /api/ask             Stel vraag aan AI
POST /api/clients         Maak API client aan (admin)
GET  /api/services        Lijst externe services
POST /api/services        Voeg externe service toe
GET  /api/stats           Statistieken
```

**Voorbeeld: Voeg een bladwijzer toe**
```bash
curl -X POST http://localhost:8767/api/bookmarks \
  -H "Authorization: Bearer jouw-api-sleutel" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://github.com",
    "title": "GitHub",
    "user_id": 1
  }'
```

**Voorbeeld: Maak een API client aan**
```bash
curl -X POST http://localhost:8767/api/clients \
  -H "Authorization: Bearer master-api-sleutel" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Mijn App",
    "permissions": "read,write",
    "rate_limit": 1000
  }'
```

## Browser Functionaliteit

### Keyboard Shortcuts

| Shortcut | Actie |
|----------|-------|
| Ctrl+T | Nieuwe tab |
| Ctrl+W | Tab sluiten |
| Ctrl+Tab | Volgende tab |
| Ctrl+Shift+Tab | Vorige tab |
| Ctrl+, | Instellingen openen |
| Ctrl+L | Adresbalk selecteren |
| Enter | Navigeer naar URL |
| Escape | Adresbalk sluiten |

### AI Assistent

- Klik op de **🤖 AI-knop** in de toolbar
- Of gebruik **Ctrl+Shift+A** (toekomstige implementatie)
- Selecteer je **provider** en **model** in de instellingen
- Stel vragen over de huidige pagina of iets anders

### Instellingen

- **Provider selectie**: Kies uit 8 verschillende LLM providers
- **Model selectie**: Selecteer specifieke modellen per provider
- **API-sleutel beheer**: Voeg en verwijder API-sleutels voor elke provider
- **Thema**: Licht/donker modus (toekomstig)

## Troubleshooting

### Gateway Fouten

**Probleem:** `LLM_API_KEY is niet ingesteld`
**Oplossing:** Zet de omgevingsvariabele in:
```bash
export LLM_API_KEY="jouw-sleutel"
```

**Probleem:** `Geen API-sleutel ingesteld voor provider 'openai'`
**Oplossing:** Voeg een sleutel toe via de configuratie:
```bash
curl -X POST http://localhost:8766/config/keys \
  -H "Content-Type: application/json" \
  -d '{"action": "set", "provider": "openai", "key": "jouw-openai-sleutel"}'
```

### API Server Fouten

**Probleem:** `Niet geauthoriseerd`
**Oplossing:** Voeg de juiste headers toe:
```bash
# Voor master toegang
-H "Authorization: Bearer jouw-master-sleutel"

# Voor client toegang
-H "X-Client-ID: jouw-client-id" \
-H "X-Client-Secret: jouw-client-secret"
```

**Probleem:** Poort in gebruik
**Oplossing:** Kies een andere poort:
```bash
export NEWLY_API_PORT=8768
```

### Database Fouten

**Probleem:** SQLite fouten
**Oplossing:** Zorg dat de data directory bestaat:
```bash
mkdir -p sync-server/data
chmod 755 sync-server/data
```

## Licentie

Newly is open source software, gelicenseerd onder de MIT licentie.

## Bijdragen

Bijdragen zijn welkom! Open een pull request of meld issues in de GitHub repository.

### Ontwikkelomgeving

```bash
# Clone de repository
git clone https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly.git
cd Newly

# Installeer afhankelijkheden
cd browser
npm install

# Start de development servers
# Terminal 1: Browser
npm start

# Terminal 2: Gateway
export LLM_API_KEY="jouw-sleutel"
python3 gateway/server.py

# Terminal 3: Sync-Server
python3 sync-server/server.py

# Terminal 4: API Server (optioneel)
export NEWLY_API_KEY="jouw-api-sleutel"
python3 sync-server/api_server.py
```

## Contact

Voor vragen en ondersteuning, bezoek de [GitHub repository](https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly).
