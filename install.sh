#!/usr/bin/env bash
# Install tt600: udev rule, the tt600d service (starts at boot) and the tray app (starts at login).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

echo "==> udev rule (needs sudo)"
sudo install -m 644 "$DIR/99-thermaltake-lcd.rules" /etc/udev/rules.d/
sudo install -m 644 "$DIR/70-idcooling-pump.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
sudo udevadm trigger --subsystem-match=tty

if ! id -nG | grep -qw plugdev; then
    echo "==> adding $USER to plugdev (log out and back in afterwards)"
    sudo usermod -aG plugdev "$USER"
fi

echo "==> dependencies"
if ! python3 -c "import PIL, psutil, serial" 2>/dev/null; then
    if command -v apt-get >/dev/null; then
        sudo apt-get install -y python3-pil python3-psutil python3-serial
    else
        python3 -m pip install --user -r "$DIR/requirements.txt"
    fi
fi
if ! python3 -c "import gi; gi.require_version('AyatanaAppIndicator3', '0.1')" 2>/dev/null; then
    if command -v apt-get >/dev/null; then
        sudo apt-get install -y python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
    else
        echo "    tray app needs PyGObject, GTK 3 and Ayatana AppIndicator; install them with your package manager"
    fi
fi

echo "==> tt600d service (starts at boot)"
mkdir -p "$CONF/systemd/user"
cat > "$CONF/systemd/user/tt600d.service" <<EOF
[Unit]
Description=Thermaltake 6" LCD panel dashboard (264a:2347)

[Service]
ExecStart=/usr/bin/python3 -u $DIR/tt600d.py
Restart=always
RestartSec=5
TimeoutStopSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now tt600d
echo "==> optional pump LCD service"
mkdir -p "$CONF/tt600"
if [ -f "$CONF/tt600/pump-mock.json" ] && [ ! -f "$CONF/tt600/pump.json" ]; then
    cp "$CONF/tt600/pump-mock.json" "$CONF/tt600/pump.json"
fi
cat > "$CONF/systemd/user/tt600-pumpd.service" <<EOF
[Unit]
Description=ID-COOLING SL360 XE LCD dashboard

[Service]
ExecStart=/usr/bin/python3 -u $DIR/pumpd.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
# The earlier standalone pump service must not own the same serial port.
systemctl --user disable --now sl360xe.service 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now tt600-pumpd
loginctl enable-linger "$USER"   # start the user service at boot, before login

echo "==> tray app (starts at login)"
mkdir -p "$CONF/autostart" "$DATA/applications"
desktop() {
    cat <<EOF
[Desktop Entry]
Type=Application
Name=Thermaltake LCD
Comment=Configure the Thermaltake panel and optional pump LCD
Exec=/usr/bin/python3 $DIR/tt600-tray.py
Icon=video-display
Categories=Utility;Settings;HardwareSettings;
Terminal=false
EOF
}
desktop > "$DATA/applications/tt600-tray.desktop"
desktop > "$CONF/autostart/tt600-tray.desktop"
rm -f "$DATA/applications/tt600-pump-mock.desktop"
pkill -f "^/usr/bin/python3 $DIR/tt600-tray.py$" 2>/dev/null || true
setsid python3 "$DIR/tt600-tray.py" >/dev/null 2>&1 < /dev/null &

echo
echo "Done. Use the tray icon (or 'Thermaltake LCD' in your apps) to change the dashboard."
echo "Logs: journalctl --user -u tt600d -f"
