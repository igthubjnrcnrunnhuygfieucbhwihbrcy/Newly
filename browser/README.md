# Newly Browser - Windows App

**Newly** is de browser die werkt **VOOR JOU**, niet voor adverteerders, tech-giganten of data brokers.

## 🎯 Unieke Voordelen

- ✅ **100% Privacy** - Geen tracking, geen telemetrie, geen data-verkoop
- ✅ **AI Assistent** - Vraag om samenvattingen, uitleg, vertalingen
- ✅ **Eigen Sync-Server** - Draai op Raspberry Pi of VPS
- ✅ **Lokaal Everything** - API-sleutels blijven op jouw apparaat
- ✅ **DuckDuckGo Standaard** - Privacy-first zoekmachine
- ✅ **Geen Cloud Afhankelijkheid** - Geen Google/Firefox account nodig

---

## 📥 Installatie (Voor Gebruikers)

### Optie 1: Voorgebouwde Installer (Aanbevolen)

1. Download de nieuwste installer van [Releases](https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/releases)
2. Voer `Newly-Setup-x.x.x.exe` uit
3. Volg de installatie-instructies
4. Start Newly vanaf je Startmenu of Bureaublad

### Optie 2: Portable Versie

1. Download de ZIP file van [Releases](https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/releases)
2. Pak het ZIP bestand uit
3. Voer `Newly.exe` uit

---

## 🏗️ Bouwen (Voor Ontwikkelaars)

### Vereisten

- [Node.js](https://nodejs.org/) 18 of hoger
- [npm](https://www.npmjs.com/) (meestal meegeleverd met Node.js)
- [Python](https://www.python.org/) 3.6+ (voor icon generatie)
- Optioneel: [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (voor native modules)

### Stappen

#### 1. Repository cloneren

```bash
cd browser
```

(Je bent al in de browser directory)

#### 2. Afhankelijkheden installeren

```bash
npm install
```

#### 3. Icon genereren (optioneel)

Als je een eigen icon wilt:

```bash
# Installeer vereiste Python packages
pip install pillow cairosvg

# Genereer ICO van SVG
python build/generate_icon.py
```

Of gebruik een online tool zoals [icoconvert.com](https://icoconvert.com/) om een 256x256 ICO bestand te maken en sla het op als `build/icon.ico`.

#### 4. Bouwen voor Windows

**Met PowerShell (Aanbevolen):**
```powershell
.\build\build.ps1
```

**Met CMD:**
```cmd
build\build.bat
```

**Handmatig:**
```bash
# Bouw de Windows installer
npm run build:win

# Of specifieke architectuur
npm run build:win     # 64-bit
npm run build:win32   # 32-bit
```

#### 5. Resultaat

De gebouwde app staat in de `dist/` directory:
- `Newly Setup x.x.x.exe` - Installer
- `Newly-win32-x64/` - Portable versie

---

## 📁 Project Structuur

```
browser/
├── main.js          # Electron hoofdproces
├── preload.js       # Preload script voor IPC
├── index.html       # Browser UI
├── package.json     # Electron configuratie
└── build/
    ├── icon.svg     # SVG bronbestand
    ├── icon.ico     # Windows icon (gegenereerd)
    ├── build.bat    # Build script voor CMD
    ├── build.ps1    # Build script voor PowerShell
    └── generate_icon.py  # Icon generatie script
```

---

## 🚀 Snelle Start (Ontwikkeling)

```bash
# Start de browser in ontwikkelmodus
npm start

# Of met debug logging
npm run dev
```

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Actie |
|----------|-------|
| Ctrl+T | Nieuwe tab |
| Ctrl+W | Sluit tab |
| Ctrl+Tab | Volgende tab |
| Ctrl+Shift+Tab | Vorige tab |
| Ctrl+K | Open AI Sidekick |
| Ctrl+L | Focus URL bar |
| Enter | Navigeer naar URL |

---

## 🛠️ Configuratie

### package.json

De belangrijkste configuratie voor electron-builder:

```json
{
  "build": {
    "appId": "com.newly.browser",
    "productName": "Newly",
    "win": {
      "target": ["nsis", "zip"],
      "icon": "build/icon.ico"
    },
    "nsis": {
      "oneClick": false,
      "allowToChangeInstallationDirectory": true,
      "createDesktopShortcut": true,
      "createStartMenuShortcut": true
    }
  }
}
```

### Aangepaste Opties

Je kunt de volgende opties aanpassen:

- **appId**: Unieke identifier voor de app
- **productName**: Naam die getoond wordt
- **icon**: Pad naar het icon bestand
- **target**: Bouw doelen (nsis = installer, zip = portable)
- **requestedExecutionLevel**: Admin rechten (requireAdministrator, asInvoker, highestAvailable)

---

## 🔧 Problemen Oplossen

### Fout: Node.js niet gevonden

**Oplossing:** Installeer Node.js 18+ van [nodejs.org](https://nodejs.org/)

### Fout: electron-builder niet gevonden

**Oplossing:**
```bash
npm install -g electron-builder
```

### Fout: Visual Studio Build Tools ontbreken

**Oplossing:** Installeer Visual Studio Build Tools met:
```bash
npm install --global windows-build-tools
```

### Fout: Icon niet gevonden

**Oplossing:** Genereer een ICO bestand:
1. Maak een 256x256 PNG bestand
2. Gebruik [icoconvert.com](https://icoconvert.com/) om het om te zetten naar ICO
3. Sla het op als `build/icon.ico`

### Fout: Build mislukt met exit code 1

**Oplossing:**
```bash
# Schone installatie
rm -rf node_modules package-lock.json
npm cache clean --force
npm install
npm run build:win
```

---

## 📦 Afhankelijkheden

- [Electron](https://www.electronjs.org/) - Framework voor desktop apps
- [electron-builder](https://www.electron.build/) - Bouw tool voor Electron apps
- [Pillow](https://python-pillow.org/) - Python image processing (voor icon)
- [CairoSVG](https://cairosvg.org/) - SVG naar PNG conversie (voor icon)

---

## 🤝 Bijdragen

1. Fork de repository
2. Maak een feature branch (`git checkout -b feature/amazing-feature`)
3. Commit je wijzigingen (`git commit -m 'Add amazing feature'`)
4. Push naar de branch (`git push origin feature/amazing-feature`)
5. Open een Pull Request

---

## 📜 Licentie

MIT License - Zie [LICENSE](../../LICENSE) voor details.

---

## 🙏 Bedankt

Bedankt voor het gebruiken van Newly! 

**Newly = Jouw browser, jouw data, jouw controle.** 🎯
