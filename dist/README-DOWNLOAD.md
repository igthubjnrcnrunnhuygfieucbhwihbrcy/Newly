# 📥 Newly Download - Windows Portable

**Wil je Newly nu direct proberen?** Hier is de **portable versie** die je kunt downloaden en gebruiken zonder te hoeven bouwen!

---

## 🎯 Wat is Newly Portable?

Newly Portable is een **klaar-om-te-gebruiken** versie van Newly die:
- ✅ **Geen installatie** nodig heeft
- ✅ **Portable** is (neem mee op USB stick)
- ✅ **Alle unieke features** bevat
- ✅ **100% Privacy** garandeert
- ✅ **AI Assistent** ingebouwd heeft

---

## 📥 Download Links

### 🔹 Directe Download (Aanbevolen)

**📦 [Download Newly Portable ZIP](https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/raw/main/dist/newly-portable.zip)**

*Grootte: ~21KB (compressed), ~100MB na installatie (met Node.js afhankelijkheden)*

---

### 🔹 Automatische Installatie

**📦 [Download Install Script](https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/raw/main/dist/install-newly-portable.bat)**

1. Download `install-newly-portable.bat`
2. Voer het uit (dubbelklik)
3. Het script download en installeert Newly automatisch

---

## 🚀 Snelle Start

### Optie 1: Handmatige Installatie (Aanbevolen)

1. **Download** de ZIP file:
   [newly-portable.zip](https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/raw/main/dist/newly-portable.zip)

2. **Pak uit** naar een map (bijv. `C:\Newly`)

3. **Installeer Node.js** (verplicht):
   - Download: [https://nodejs.org/](https://nodejs.org/)
   - Kies **LTS versie** (18.x of 20.x)
   - Installeer met alle standaard opties

4. **Start Newly**:
   - Open de map waar je de ZIP hebt uitgepakt
   - Voer `start-newly.bat` uit (dubbelklik)
   - Wacht even voor de installatie van afhankelijkheden
   - Newly start automatisch!

### Optie 2: Automatische Installatie

1. **Download** het install script:
   [install-newly-portable.bat](https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/raw/main/dist/install-newly-portable.bat)

2. **Voer uit** (dubbelklik)

3. **Volg de instructies**

4. **Start Newly** vanaf het bureaublad of startmenu

---

## 📁 Wat zit er in de ZIP?

```
newly-portable/
├── index.html          # Browser UI (unieke cyaan thema)
├── main.js             # Electron hoofdproces
├── preload.js          # Preload script voor IPC
├── package.json        # Electron & electron-builder configuratie
├── start-newly.bat     # Start script voor Windows
├── Newly.exe           # Placeholder (voor toekomstige EXE)
├── README.md           # Documentatie
└── build/              # Build scripts en icon
    ├── build.bat       # Bouw script (CMD)
    ├── build.ps1       # Bouw script (PowerShell)
    ├── generate_icon.py # Icon generatie
    ├── icon.svg        # SVG bronbestand
    └── icon.ico        # Windows icon (gegenereerd)
```

---

## ⚙️ Systeem Vereisten

| Vereiste | Details |
|----------|---------|
| **Besturingssysteem** | Windows 10 of 11 (64-bit) |
| **Node.js** | 18.x of hoger (verplicht) |
| **RAM** | 4GB aanbevolen |
| **Schijfruimte** | ~500MB (voor afhankelijkheden) |
| **Admin rechten** | Niet nodig voor portable versie |

---

## 🎨 Unieke Features

### 🔒 Privacy
- ❌ Geen tracking
- ❌ Geen telemetrie
- ❌ Geen data-verkoop
- ✅ DuckDuckGo als standaard zoekmachine
- ✅ Tracker detectie

### 🤖 AI Assistent
- ✅ Samenvattingen van pagina's
- ✅ Uitleggen wat er staat
- ✅ Vertalen
- ✅ Slim zoeken
- ✅ AI Sidekick paneel (Ctrl+K)

### 🌐 Sync-Server
- ✅ Draai op Raspberry Pi
- ✅ Draai op VPS
- ✅ Geen cloud afhankelijkheid
- ✅ Volledige controle

### ⚡ Snel & Licht
- ✅ Geen bloatware
- ✅ Alleen wat je nodig hebt
- ✅ Snelle start
- ✅ Lage geheugen gebruik

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Actie |
|----------|-------|
| **Ctrl+T** | Nieuwe tab |
| **Ctrl+W** | Sluit tab |
| **Ctrl+Tab** | Volgende tab |
| **Ctrl+Shift+Tab** | Vorige tab |
| **Ctrl+K** | Open AI Sidekick |
| **Ctrl+L** | Focus URL bar |
| **Enter** | Navigeer naar URL |

---

## 🛠️ Problemen Oplossen

### ❌ Newly start niet

**Mogelijke oorzaken:**
1. Node.js is niet geinstalleerd
2. Node.js versie is te oud (< 18)
3. Afhankelijkheden zijn niet geinstalleerd

**Oplossingen:**
```cmd
:: Controleer Node.js versie
node --version

:: Installeer afhankelijkheden
cd newly-portable
npm install

:: Start handmatig
node main.js
```

### ❌ Fout: "Electron niet gevonden"

**Oplossing:**
```cmd
cd newly-portable
npm install electron
```

### ❌ Fout: "Port already in use"

**Oplossing:** Sluit alle Newly instanties en probeer opnieuw.

### ❌ Fout bij downloaden

**Oplossing:**
- Controleer je internet verbinding
- Probeer de download handmatig
- Gebruik een andere browser

---

## 🏗️ Voor Ontwikkelaars: Bouw je Eigen EXE

Wil je een **echt Windows EXE** bestand? Volg deze stappen:

1. Installeer Node.js 18+
2. Open Command Prompt in de `newly-portable` map
3. Voer uit:
   ```cmd
   npm install
   npm run build:win
   ```
4. De installer staat in `dist/Newly-Setup-x.x.x.exe`

**Vereisten:**
- Node.js 18+
- npm
- Python 3.6+ (voor icon generatie)
- Optional: Visual Studio Build Tools

---

## 📊 Wat is het verschil tussen Portable en Installer?

| Kenmerk | Portable | Installer |
|---------|----------|-----------|
| **Installatie** | Niet nodig | Vereist |
| **Draagbaar** | ✅ Ja | ❌ Nee |
| **Shortcuts** | Handmatig | Automatisch |
| **Uninstall** | Verwijder map | Via Control Panel |
| **Grootte** | ~100MB | ~100MB |
| **Updates** | Handmatig | Automatisch |

---

## 🔗 Handige Links

- **GitHub Repository:** [https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly](https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly)
- **Node.js Download:** [https://nodejs.org/](https://nodejs.org/)
- **DuckDuckGo:** [https://duckduckgo.com/](https://duckduckgo.com/)

---

## 🤝 Bijdragen

Vind je Newly leuk? Help mee:
- 🐛 **Rapporteer bugs** op GitHub
- 💡 **Deel ideeën** voor nieuwe features
- ⭐ **Geef een ster** op GitHub
- 💬 **Vertel het verder** aan vrienden

---

## 📜 Licentie

**MIT License** - Vrije software voor iedereen.

Je mag:
- ✅ Gebruiken voor persoonlijk en commercieel gebruik
- ✅ Aanpassen en distribueren
- ✅ Broncode inzien en wijzigen

Je mag niet:
- ❌ Claimen dat het van jou is
- ❌ Ons aansprakelijk stellen voor schade

---

## 🙏 Bedankt!

Bedankt voor het proberen van Newly!

**Newly = Jouw browser, jouw data, jouw controle.** 🎯

---

*Laatste update: November 2024*
