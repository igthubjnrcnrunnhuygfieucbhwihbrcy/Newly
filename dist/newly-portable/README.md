# Newly Portable - Windows

**Newly** is de browser die werkt **VOOR JOU**, niet voor adverteerders, tech-giganten of data brokers.

## 📥 Snelle Start

### Optie 1: Direct Starten (Aanbevolen)

1. Download deze ZIP file
2. Pak uit naar een map (bijv. `C:\Newly`)
3. Voer `start-newly.bat` uit (dubbelklik)
4. Wacht even voor de installatie van afhankelijkheden
5. Newly start automatisch!

### Optie 2: Handmatige Installatie

1. Pak de ZIP file uit
2. Open een Command Prompt in de map
3. Voer uit:
   ```cmd
   npm install
   node main.js
   ```

---

## 🎯 Unieke Voordelen

- ✅ **100% Privacy** - Geen tracking, geen telemetrie, geen data-verkoop
- ✅ **AI Assistent** - Vraag om samenvattingen, uitleg, vertalingen
- ✅ **Eigen Sync-Server** - Draai op Raspberry Pi of VPS
- ✅ **Lokaal Everything** - API-sleutels blijven op jouw apparaat
- ✅ **DuckDuckGo Standaard** - Privacy-first zoekmachine
- ✅ **Portable** - Neem mee op USB stick, geen installatie nodig

---

## 🏗️ Vereisten

- **Node.js 18 of hoger** (verplicht)
  - Download: [https://nodejs.org/](https://nodejs.org/)
  - Kies de LTS versie (18.x of 20.x)

---

## 📁 Inhoud van deze Map

```
newly-portable/
├── index.html          # Browser UI
├── main.js             # Electron hoofdproces
├── preload.js          # Preload script
├── package.json        # App configuratie
├── start-newly.bat     # Start script (Windows)
├── Newly.exe           # Placeholder (echt EXE na bouwen)
└── README.md           # Deze file
```

---

## 🚀 Hoe te Bouwen (Voor Geavanceerde Gebruikers)

Als je een **echt Windows EXE** wilt maken:

1. Installeer Node.js 18+
2. Open Command Prompt in deze map
3. Voer uit:
   ```cmd
   npm install
   npm run build:win
   ```
4. De installer staat in `dist/Newly-Setup-x.x.x.exe`

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

## 🛠️ Problemen Oplossen

### Fout: Node.js niet gevonden

**Oplossing:** Installeer Node.js van [https://nodejs.org/](https://nodejs.org/)

### Fout: Afhankelijkheden niet gevonden

**Oplossing:** Voer uit in deze map:
```cmd
npm install
```

### Fout: Electron niet gevonden

**Oplossing:**
```cmd
npm install electron
```

### Fout: Port in gebruik

**Oplossing:** Sluit alle Newly instanties en probeer opnieuw.

### Newly start niet

**Oplossing:**
1. Zorg dat Node.js geinstalleerd is
2. Voer `start-newly.bat` uit in Command Prompt om foutmeldingen te zien
3. Stuur de foutmelding naar de ontwikkelaars

---

## 📊 Systeem Vereisten

- **Besturingssysteem:** Windows 10 of 11 (64-bit)
- **Node.js:** 18.x of hoger
- **RAM:** 4GB aanbevolen
- **Schijfruimte:** 500MB voor afhankelijkheden

---

## 🔒 Privacy & Veiligheid

Newly verzamelt **GEEN** van de volgende:
- ❌ Zoekgeschiedenis
- ❌ Browse geschiedenis
- ❌ IP adres
- ❌ Persoonlijke gegevens
- ❌ Telemetrie
- ❌ Crash reports

**Jouw data blijft van JOU.**

---

## 🤝 Bijdragen

Vind je Newly leuk? Help mee:
- 🐛 Rapporteer bugs
- 💡 Deel ideeën
- ⭐ Geef een ster op GitHub
- 💬 Vertel het verder

---

## 📜 Licentie

MIT License - Vrije software voor iedereen.

---

## 🙏 Bedankt

Bedankt voor het gebruiken van Newly!

**Newly = Jouw browser, jouw data, jouw controle.** 🎯
