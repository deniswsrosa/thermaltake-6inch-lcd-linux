# Thermaltake View 600 TG 6" LCD screen on Linux

Use the **Thermaltake 6.0" LCD Panel Kit for View 600 TG** on Linux: a system
monitor dashboard for the case screen, with no Windows and no TT RGB Plus.

Thermaltake only supports this panel on Windows. This project drives it
directly over USB and shows your CPU and GPU temperatures in big, readable
layouts, so you can read them from across the room.

![Dashboard templates](docs/templates.png)

## Supported hardware

| | |
|---|---|
| Product | Thermaltake 6.0" LCD Panel Kit for View 600 TG |
| Part number | `AC-080-OO1NAN-A1` |
| USB ID | `264a:2347` (`lsusb` shows "ThermalTake USB Device") |

Check that yours is connected: `lsusb | grep 264a:2347`

Other Thermaltake screens (Tower 200/500 bar, RC Pro, TH420 and AIO displays)
use a different protocol. See the
[projects listed here](docs/PROTOCOL.md#why-not-the-existing-thermaltake-linux-tools).

## Features

- **10 templates**: big numbers, ring gauges, bars, tiles, speedometer, digital
  7-segment, history graph, terminal, synthwave, single metric
- **Multi-GPU**: each NVIDIA card gets its own reading
- **Any sensor**: CPU, GPU, RAM, SSD and fans, any `hwmon` sensor, or any
  command that prints a number
- **Tray app** with a live-preview settings window: templates, colours,
  labels, background image, font, brightness
- **Starts at boot**, and uses about 0.2% of one CPU core and ~35 MB of memory
- **Your own templates**: drop a Python file in a folder

## Install

Tested on Ubuntu 26.04 (GNOME). Needs Python 3. The installer pulls in Pillow,
psutil, and GTK/AppIndicator for the tray.

```sh
git clone https://github.com/deniswsrosa/thermaltake-6inch-lcd-linux.git
cd thermaltake-6inch-lcd-linux
./install.sh
```

The installer asks for `sudo` once, to install a udev rule so the panel can be
used without root. It then:

- starts the `tt600d` service, which runs from boot, even before you log in
- adds a **Thermaltake LCD** tray icon that starts when you log in

## Use

Click the **tray icon** to switch template, °C/°F or brightness, or open
**Customize…** to change what each slot shows, colours, labels and more,
with a live preview. Changes show on the panel right away.

More in [docs/CUSTOMIZING.md](docs/CUSTOMIZING.md): custom sensors and
commands, background images, fonts, writing your own template, and the
command-line tools.

## Troubleshooting

| Problem | Fix |
|---|---|
| Nothing on the panel | `systemctl --user status tt600d` and `journalctl --user -u tt600d -f` |
| "Panel not found" in the tray | check `lsusb \| grep 264a:2347`; re-run `./install.sh` (udev rule); log out and in if you were just added to `plugdev` |
| No tray icon on GNOME | enable the AppIndicator extension (`gnome-extensions enable ubuntu-appindicators@ubuntu.com` on Ubuntu) |
| GPU shows `--` | only NVIDIA cards are read directly; for AMD, pick the `amdgpu` sensor in the metric list |

## Uninstall

```sh
./uninstall.sh
```

## How it works

The panel runs embedded Linux and speaks an HTTP-like protocol over USB HID,
recovered from TT RGB Plus. The details are in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## License

MIT. Not affiliated with or endorsed by Thermaltake.
