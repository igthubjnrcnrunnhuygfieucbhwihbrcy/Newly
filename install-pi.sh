#!/usr/bin/env bash
# Newly — browser-in-browser installer/updater voor Raspberry Pi (Ubuntu Server).
# Plak dit in de terminal (SSH, bijv. Terminus). Kan gerust opnieuw: werkt als update.
set -euo pipefail
REPO="https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly"
DEST="$HOME/zelfsync"
SUDO=""
[ "$(id -u)" = 0 ] || SUDO="sudo"

echo "[1/4] Nieuwste versie downloaden..."
command -v curl >/dev/null 2>&1 || { $SUDO apt-get update -y; $SUDO apt-get install -y curl unzip; }
command -v unzip >/dev/null 2>&1 || $SUDO apt-get install -y unzip
mkdir -p "$DEST"
curl -fsSL -o /tmp/newly.zip "$REPO/archive/refs/heads/main.zip"
unzip -qo /tmp/newly.zip -d /tmp/newly
cp -r /tmp/newly/Newly-main/sync-server/. "$DEST"/
rm -rf /tmp/newly /tmp/newly.zip

echo "[2/4] Service installeren..."
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

echo "[3/4] (Her)starten..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now zelfsync
$SUDO systemctl restart zelfsync
sleep 2

echo "[4/4] Controle..."
curl -fsS http://localhost:8765/health || { echo "Start mislukt. Log: journalctl -u zelfsync -n 20"; exit 1; }

IP=$(hostname -I 2>/dev/null | cut -d' ' -f1)
echo
echo "======================================================"
echo " KLAAR (nieuwste versie actief)! Open in je browser:"
echo ""
echo "     http://$IP:8765/"
echo ""
echo " Tip: laat de pagina daarna 1x verversen."
echo "======================================================"
