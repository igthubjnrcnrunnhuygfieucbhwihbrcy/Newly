#!/usr/bin/env bash
# Newly — installer/updater voor Raspberry Pi (Ubuntu Server).
# Plak dit in de terminal (SSH, bijv. Terminus). Kan gerust opnieuw: werkt als update.
# Installeert: 1) Newly browser-in-browser op poort 8765
#              2) Echte browser-modus op poort 6080: een echte Chromium op de Pi,
#                 te bedienen vanaf je telefoon/laptop. Daar werkt alles:
#                 video, inloggen, en sites die servers blokkeren.
set -euo pipefail
REPO="https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly"
DEST="$HOME/zelfsync"
SUDO=""
[ "$(id -u)" = 0 ] || SUDO="sudo"

echo "[1/5] Nieuwste versie downloaden..."
command -v curl >/dev/null 2>&1 || { $SUDO apt-get update -y; $SUDO apt-get install -y curl unzip; }
command -v unzip >/dev/null 2>&1 || $SUDO apt-get install -y unzip
mkdir -p "$DEST"
curl -fsSL -o /tmp/newly.zip "$REPO/archive/refs/heads/main.zip"
unzip -qo /tmp/newly.zip -d /tmp/newly
cp -r /tmp/newly/Newly-main/sync-server/. "$DEST"/
rm -rf /tmp/newly /tmp/newly.zip

echo "[2/5] Browser-in-browser service installeren..."
cat > /tmp/zelfsync.service <<UNIT
[Unit]
Description=ZelfSync (Newly browser-in-browser)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$DEST
ExecStart=/usr/bin/python3 $DEST/server.py
Restart=on-failure
RestartSec=5
Environment=ZELFSYNC_PORT=8765

[Install]
WantedBy=multi-user.target
UNIT
$SUDO cp /tmp/zelfsync.service /etc/systemd/system/zelfsync.service

echo "[3/5] Echte browser-modus (alleen de eerste keer: dit kan enkele minuten duren)..."
$SUDO apt-get update -y >/dev/null 2>&1 || true
$SUDO apt-get install -y xvfb x11vnc novnc websockify >/dev/null 2>&1 || {
  echo "  Let op: schermdeel-pakketten konden niet geinstalleerd worden; echte modus wordt overgeslagen."
}
BROWSER=""
if [ -x /snap/bin/chromium ]; then BROWSER=/snap/bin/chromium; fi
if command -v chromium >/dev/null 2>&1; then BROWSER="$(command -v chromium)"; fi
if command -v chromium-browser >/dev/null 2>&1; then BROWSER="$(command -v chromium-browser)"; fi
if [ -z "$BROWSER" ]; then
  if ! command -v snap >/dev/null 2>&1; then
    $SUDO apt-get install -y snapd >/dev/null 2>&1 || true
    $SUDO systemctl enable --now snapd.socket >/dev/null 2>&1 || true
  fi
  $SUDO snap install chromium >/dev/null 2>&1 || true
  if [ -x /snap/bin/chromium ]; then BROWSER=/snap/bin/chromium; fi
fi
if [ -z "$BROWSER" ]; then
  $SUDO apt-get install -y chromium-browser >/dev/null 2>&1 || true
  if command -v chromium-browser >/dev/null 2>&1; then BROWSER="$(command -v chromium-browser)"; fi
fi
if [ -z "$BROWSER" ]; then
  $SUDO apt-get install -y chromium >/dev/null 2>&1 || true
  if command -v chromium >/dev/null 2>&1; then BROWSER="$(command -v chromium)"; fi
fi
if [ -z "$BROWSER" ]; then
  $SUDO apt-get install -y epiphany-browser >/dev/null 2>&1 || true
  if command -v epiphany >/dev/null 2>&1; then BROWSER="$(command -v epiphany)"; fi
fi
if [ -n "$BROWSER" ]; then
  FLAGS="--no-sandbox --disable-dev-shm-usage --no-first-run --no-default-browser-check --window-size=1280,720 --window-position=0,0 --autoplay-policy=no-user-gesture-required"
  case "$BROWSER" in *epiphany*) FLAGS="--new-window";; esac
  cat > "$DEST/echte-browser.sh" <<RUN
#!/usr/bin/env bash
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
sleep 2
DISPLAY=:99 "$BROWSER" $FLAGS "http://localhost:8765/" &
sleep 3
x11vnc -display :99 -forever -shared -localhost -nopw -quiet &
exec websockify --web /usr/share/novnc 0.0.0.0:6080 localhost:5900
RUN
  chmod +x "$DEST/echte-browser.sh"
  cat > /tmp/newly-echt.service <<UNIT
[Unit]
Description=Newly echte browser (Chromium op de Pi via schermdeling)
After=network-online.target zelfsync.service
Wants=network-online.target

[Service]
User=$USER
ExecStart=$DEST/echte-browser.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  $SUDO cp /tmp/newly-echt.service /etc/systemd/system/newly-echt.service
else
  echo "  Geen geschikte browser gevonden op dit systeem; echte modus overgeslagen."
  echo "  (De Newly web-interface op poort 8765 werkt gewoon.)"
fi

echo "[4/5] (Her)starten en controleren..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now zelfsync
$SUDO systemctl restart zelfsync
if [ -n "$BROWSER" ]; then
  $SUDO systemctl enable newly-echt >/dev/null 2>&1 || true
  $SUDO systemctl restart newly-echt >/dev/null 2>&1 || echo "  (echte modus startte niet meteen; de rest werkt gewoon)"
fi
sleep 2
curl -fsS http://localhost:8765/health || { echo "Start mislukt. Log: journalctl -u zelfsync -n 20"; exit 1; }

IP=$(hostname -I 2>/dev/null | cut -d' ' -f1)
echo
echo "======================================================"
echo " KLAAR (nieuwste versie actief)!"
echo ""
echo "   Newly openen:      http://$IP:8765/"
if [ -n "$BROWSER" ]; then
  echo "   Echte browser:     http://$IP:6080/vnc.html?autoconnect=true&resize=scale"
  echo "   (of tik in Newly op de Tv-knop bovenin)"
fi
echo ""
echo " Tip: laat de Newly-pagina daarna 1x verversen."
echo "======================================================"
