#!/usr/bin/env bash
# Install tt600d: udev rule (sudo), and a systemd user service that starts at boot.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

echo "==> udev rule (needs sudo)"
sudo install -m 644 "$DIR/99-thermaltake-lcd.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw

if ! id -nG | grep -qw plugdev; then
    echo "==> adding $USER to plugdev (log out and back in afterwards)"
    sudo usermod -aG plugdev "$USER"
fi

echo "==> python dependencies"
python3 -c "import PIL, psutil" 2>/dev/null || python3 -m pip install --user -r "$DIR/requirements.txt"

echo "==> systemd user service"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/tt600d.service" <<EOF
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

# Start the user service at boot, before anyone logs in.
loginctl enable-linger "$USER"

echo
echo "Done. Settings: http://127.0.0.1:8600   Logs: journalctl --user -u tt600d -f"
