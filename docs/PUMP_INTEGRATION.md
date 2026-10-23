# Optional pump LCD

The Thermaltake settings window shows a **Pump LCD** page only when the
ID-COOLING SL360 XE's `CT21INCH` serial device is detected. The tray menu entry
is hidden when the pump is absent. The pump page uses live sensor readings in
its preview; **Save and apply** writes `~/.config/tt600/pump.json`.

`tt600-pumpd` watches that profile and owns the pump serial port. It uses the
same 480×480 renderer as the designer, follows GIF frame durations, and sends
changed image regions. It waits without opening a port if the pump is absent.
The original `tt600d` independently owns the Thermaltake panel.
Detection remembers the physical USB path of the `CT21INCH` interface so a
different Android serial device is never mistaken for the awakened pump.

The installer disables the previous `sl360xe.service` if present, since both
services must not write to the same pump. The pump's saved rotation is applied
by the renderer; the transport adds no second rotation. When updating an older
setup that used `sl360xe --rotate 180`, choose **180°** in the Pump LCD page and
save the profile.

The standalone `python3 pump_mock.py` command remains a preview-only designer.
Its **Save draft** button writes `pump-mock.json`, which the pump service does
not read. The installer copies an older draft to `pump.json` once during
migration. The transport module is adapted from
`mathoudebine/turing-smart-screen-python` and is licensed GPL-3.0-or-later;
see [the license](../licenses/GPL-3.0.txt). The pump worker that imports it is
distributed under GPL-3.0-or-later as a combined program. The independent
Thermaltake tray, daemon, renderer, and device detection modules retain their
MIT license.
