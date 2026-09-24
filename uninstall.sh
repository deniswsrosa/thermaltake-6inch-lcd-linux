#!/usr/bin/env bash
# Remove the tt600d service, tray app and udev rule. Keeps ~/.config/tt600 (your settings).
set -uo pipefail

CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

systemctl --user disable --now tt600d 2>/dev/null
rm -f "$CONF/systemd/user/tt600d.service"
systemctl --user daemon-reload
pkill -f "tt600-tray.py" 2>/dev/null
rm -f "$CONF/autostart/tt600-tray.desktop" "$DATA/applications/tt600-tray.desktop"
if [ -f /etc/udev/rules.d/99-thermaltake-lcd.rules ]; then
    sudo rm -f /etc/udev/rules.d/99-thermaltake-lcd.rules && sudo udevadm control --reload-rules
fi
echo "Removed. Settings are kept in $CONF/tt600 (delete it to reset)."
echo "Lingering is left on; turn it off with: loginctl disable-linger $USER"
