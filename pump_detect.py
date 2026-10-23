"""Identify the optional SL360 XE pump without opening a serial port.

The awake USB identity is generic. Some controllers expose the sleeping and
awake identities simultaneously on sibling ports of the same internal hub.
"""

from __future__ import annotations

import os
from pathlib import Path

from serial.tools.list_ports import comports

SLEEP_ID = (0x1A86, 0xCA21)
AWAKE_IDS = {(0x1D6B, 0x0121), (0x1D6B, 0x0106), (0x0525, 0xA4A7)}
LOCATION_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tt600" / "pump-location"


def sleeping_port():
    return next((port for port in comports()
                 if port.serial_number == "CT21INCH" and (port.vid, port.pid) == SLEEP_ID), None)


def target_location() -> str | None:
    sleeping = sleeping_port()
    if sleeping and sleeping.location:
        location = sleeping.location
        try:
            if not LOCATION_PATH.exists() or LOCATION_PATH.read_text() != location:
                LOCATION_PATH.parent.mkdir(parents=True, exist_ok=True)
                LOCATION_PATH.write_text(location)
        except OSError:
            pass
        return location
    try:
        return LOCATION_PATH.read_text().strip() or None
    except OSError:
        return None


def awake_port():
    location = target_location()
    if not location:
        return None
    candidates = [port for port in comports()
                  if port.location and port.serial_number == "20080411"
                  and (port.vid, port.pid) in AWAKE_IDS]
    exact = next((port for port in candidates if port.location == location), None)
    if exact:
        return exact
    # USB location "8-12.2:1.0" is port 2 below hub 8-12. The awake
    # identity can remain visible beside CT21INCH at "8-12.1:1.0".
    parent = location.split(":", 1)[0].rsplit(".", 1)[0]
    if parent == location.split(":", 1)[0]:
        return None
    siblings = [port for port in candidates
                if port.location.split(":", 1)[0].rsplit(".", 1)[0] == parent]
    return siblings[0] if len(siblings) == 1 else None


def present() -> bool:
    if sleeping_port():
        target_location()
        return True
    return awake_port() is not None
