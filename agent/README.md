# agent/ — MCP-brug tussen LLM en browser

De agent krijgt toegang tot alles in de browser via CDP (Chrome DevTools Protocol).
De Electron-shell in browser/main.js heeft de debugger al geattacht en blootgesteld
via ipcMain.handle('cdp:send', tab, methode, params).

## Bouwplan (fase 3)

1. MCP-server in TypeScript met @modelcontextprotocol/sdk
2. Tools die via de CDP-brug werken:

   - navigate(url)             -> Page.navigate
   - read_text()               -> DOMSnapshot.captureSnapshot + tekstextractie
   - click(selector_of_x,y)    -> Runtime.evaluate of Input.dispatchMouseEvent
   - fill(selector, value)     -> Runtime.evaluate
   - screenshot()              -> Page.captureScreenshot
   - list_tabs() / switch_tab(i)

3. Model zit ACHTER de gateway (gateway/server.py): de agent vraagt tools aan bij
   de MCP-server en stopt pagina-inhoud in de gateway /ask-call. Zo blijft de
   API-sleutel op het apparaat en is het model verwisselbaar.

## Permissies (niet overslaan!)

Dit is het grootste beveiligingsvlak van het project. Minimaal:

- Per-tab toestemming: agent mag alleen de tab(s) die de gebruiker heeft gedeeld
- Actie-categorieen: lezen (standaard), navigeren (bevestigen), klikken/typen (altijd bevestigen)
- Alles gelogd en zichtbaar in een agent-activitypaneel
- Nooit toegang tot andere BrowserWindow-resources, bestandssysteem of prive-tabs

Vergelijk chrome-devtools-mcp van Google zelf voor de tool-vormen en de
beveiligingsafwegingen.
