# Newly — eigen browser met AI-agent

Newly is een eigen, Chromium-gebaseerde browser met een ingebouwde AI-agent. Local-first: het browsen gebeurt volledig op de hardware van de gebruiker (laptop/telefoon); een Raspberry Pi 5 doet optioneel de rol van sync-server — zoals Google en Brave dat voor hun browser doen, maar dan bij jou thuis.

## Architectuur

    +---------------------- gebruikersapparaten (laptop / telefoon) ----------------------+
    |                                                                                      |
    |   browser/  (Electron + Chromium)            web/  (browser-in-browser, fase 5)     |
    |        |  CDP = Chrome DevTools Protocol          |  fetch / WebSocket                |
    |        v                                           v                                 |
    |   agent/   (MCP-brug, fase 3)  --->  gateway/  (LLM-gateway: cloud-API met          |
    |   laat de LLM navigeren, klikken,               JOUW API-sleutel; draait op          |
    |   lezen, screenshots maken                      localhost, stuurt niets mee)        |
    +--------------------------------------------------------------------------------------+
                                     | optioneel: alleen sync + webproxy
                                     v
              sync-server/  op Raspberry Pi 5  (ZelfSync: multi-user accounts,
              bookmarks + geschiedenis, zelfde code draait later ook op een VPS)

## Onderdelen

- browser/ — Electron-schil met tabs, adresbalk en een CDP-agenthook (debugger-API)
- agent/ — ontwerp voor de MCP-server die de LLM toegang tot de browser geeft (fase 3)
- gateway/ — lokale LLM-gateway; de browser praat alleen met localhost, de API-sleutel blijft op het apparaat
- sync-server/ — ZelfSync: werkende multi-user sync-service, alleen Python-standaardbibliotheken
- web/ — stub voor de browser-in-browser webversie (server-side tekstproxy, fase 5)

## Snel starten

Electron-browser:

    cd browser
    npm install
    npm start

LLM-gateway (aparte terminal, eigen API-sleutel):

    cd gateway
    export LLM_API_KEY="jouw-sleutel"
    python3 server.py            # poort 8766, alleen localhost

Sync-server op de Raspberry Pi 5:

    cd sync-server
    python3 server.py            # poort 8765
    curl http://localhost:8765/health

## De Raspberry Pi 5 als sync-server

ZelfSync is de "Google-server" van deze browser, maar dan van jou: kleine API-service die per gebruiker bookmarks, geschiedenis en instellingen bewaart zodat al je apparaten synchen. Dit is lichtgewicht werk (JSON-records + SQLite): een Pi 5 met SSD doet dit ruim voor honderden gebruikers. Bereik je een echt grote schaal, dan verhuist exact dezelfde code naar een VPS.

Installeren als service (systemd):

    sudo cp zelfsync.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now zelfsync

Zet daarna port-forwarding of een reverse proxy (Caddy/nginx met HTTPS) voor bereik van buitenaf.

## Roadmap

Zie ROADMAP.md voor de fasen 1 t/m 6.

## Veiligheid

- De LLM-API-sleutel blijft op het apparaat; de gateway luistert alleen op 127.0.0.1.
- De agent krijgt per-permissie toegang tot de browser (fase 3): "wel lezen, niet klikken" moet kunnen.
- ZelfSync hasht wachtwoorden met PBKDF2 en werkt met bearer-tokens; zet er altijd TLS voor (reverse proxy).
- Logs van de gateway bevatten bewust geen prompt-inhoud.
