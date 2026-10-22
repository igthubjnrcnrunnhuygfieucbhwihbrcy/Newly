# Roadmap

## Fase 0 — scaffold (deze commit)
Monorevo met Electron-browser (CDP-hook aanwezig), LLM-gateway, ZelfSync sync-server en web-stub.

## Fase 1 — bruikbare browser (weken)
- Tabs, adresbalk, terug/vooruit, verversen werken vlot
- Lokale bookmarks + geschiedenis (SQLite in de app)
- Sidebar-UI met adresveld voor de assistent

## Fase 2 — AI in de browser
- Sidebar praat met gateway /ask en /summarize
- "Vat deze pagina samen", "wat staat hier over X"
- Paginatekst via CDP (DOMSnapshot.captureSnapshot) als context

## Fase 3 — agent (het onderscheidende deel)
- MCP-server (TypeScript, @modelcontextprotocol/sdk) die via CDP tools biedt:
  navigate(url), click(selector), read_text(), fill(selector, value), screenshot(), list_tabs()
- Permissiesysteem per actie en per tab; mens bevestigt klik-acties (human in the loop)
- Model-keuze vrij: elke cloud-API via de gateway, later lokale modellen

## Fase 4 — sync over apparaten
- ZelfSync-accounts; bookmarks/geschiedenis syncen tussen desktop en mobiel
- Token per apparaat, export/import

## Fase 5 — browser-in-browser
- Web-UI die met de gateway en de Pi praat
- Server-side tekstproxy voor pagina's (hergebruik de HTML-parser uit het oude ZelfBrowser-project)
- Eerlijkheid: iframen van willekeurige sites blokkeert X-Frame-Options, dus de webversie rendert via de proxy

## Fase 6 — mobiel en publiceren
- Android-app op WebView die dezelfde gateway/sync gebruikt
- Releases, website, documentatie
- iOS: WebKit is gedwongen door Apple; enginekeuze bestaat daar niet
