#!/usr/bin/env bash
# Install tt600: udev rule, the tt600d service (starts at boot) and the tray app (starts at login).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

echo "==> udev rule (needs sudo)"
sudo install -m 644 "$DIR/99-thermaltake-lcd.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw

if ! id -nG | grep -qw plugdev; then
    echo "==> adding $USER to plugdev (log out and back in afterwards)"
    sudo usermod -aG plugdev "$USER"
fi

echo "==> dependencies"
if ! python3 -c "import PIL, psutil" 2>/dev/null; then
    if command -v apt-get >/dev/null; then
        sudo apt-get install -y python3-pil python3-psutil
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

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now tt600d
loginctl enable-linger "$USER"   # start the user service at boot, before login

echo "==> tray app (starts at login)"
mkdir -p "$CONF/autostart" "$DATA/applications"
desktop() {
    cat <<EOF
[Desktop Entry]
Type=Application
Name=Thermaltake LCD
Comment=Configure the Thermaltake 6" LCD panel dashboard
Exec=/usr/bin/python3 $DIR/tt600-tray.py
Icon=video-display
Categories=Utility;Settings;HardwareSettings;
Terminal=false
EOF
}
desktop > "$DATA/applications/tt600-tray.desktop"
desktop > "$CONF/autostart/tt600-tray.desktop"
setsid python3 "$DIR/tt600-tray.py" >/dev/null 2>&1 < /dev/null &

echo
echo "Done. Use the tray icon (or 'Thermaltake LCD' in your apps) to change the dashboard."
echo "Logs: journalctl --user -u tt600d -f"
