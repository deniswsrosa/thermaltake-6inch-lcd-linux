#!/usr/bin/env python3
"""Render the saved pump design and send it to a detected SL360 XE LCD."""
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

from PIL import Image, ImageSequence

import config
import pump_detect
import pump_mock
import pump_transport
import sensors
from pump_presets import PRESETS, PRESET_DIR, ensure_presets

STATUS_PATH = pump_mock.STATUS_PATH
RUNNING = True


def stop(*_):
    global RUNNING
    RUNNING = False


def publish(**status):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(status))
    temporary.replace(STATUS_PATH)


def gif_frames(settings: dict) -> list[tuple[Image.Image, float]]:
    if settings["layout"] not in ("gif_only", "gif_overlay", "gif_stat"):
        return []
    key = settings["animation"]
    if key == "none":
        return []
    if key == "custom" and not settings["custom_gif"]:
        return []
    path = PRESET_DIR / PRESETS[key][1] if key in PRESETS else Path(settings["custom_gif"] or "")
    if path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("GIF exceeds 25 MB")
    frames = []
    with Image.open(path) as image:
        if image.format != "GIF":
            raise ValueError(f"Not a GIF: {path}")
        for item in ImageSequence.Iterator(image):
            frames.append((item.convert("RGB"), max(0.08, (item.info.get("duration") or 100) / 1000)))
            if len(frames) >= 120:
                break
    return frames


def run_panel():
    """Own the pump serial port until it disappears or a transfer fails."""
    settings = pump_mock.load()
    stamp = pump_mock.CONFIG_PATH.stat().st_mtime_ns if pump_mock.CONFIG_PATH.exists() else None
    try:
        frames = gif_frames(settings)
    except (OSError, ValueError) as exc:
        print(f"pumpd: {exc}", file=sys.stderr, flush=True)
        frames = []
    frame_index = 0
    next_frame = time.monotonic() + (frames[0][1] if frames else 1)
    next_stats = 0.0
    readings = pump_mock.format_values({})
    with pump_transport.Panel(brightness=100, reset_on_start=False) as panel:
        publish(present=True, connected=True)
        while RUNNING and pump_detect.present():
            now = time.monotonic()
            current_stamp = (pump_mock.CONFIG_PATH.stat().st_mtime_ns
                             if pump_mock.CONFIG_PATH.exists() else None)
            if current_stamp != stamp:
                settings, stamp = pump_mock.load(), current_stamp
                try:
                    frames = gif_frames(settings)
                except (OSError, ValueError) as exc:
                    print(f"pumpd: {exc}", file=sys.stderr, flush=True)
                    frames = []
                frame_index = 0
                next_frame = now + (frames[0][1] if frames else 1)
                next_stats = 0.0
            if now >= next_stats:
                keys = {settings[slot] for slot in pump_mock.SLOTS if settings[slot] != "none"}
                readings = pump_mock.format_values(sensors.read(keys=keys))
                next_stats = now + 1.0
            if frames and now >= next_frame:
                while now >= next_frame:
                    frame_index = (frame_index + 1) % len(frames)
                    next_frame += frames[frame_index][1]
            frame = frames[frame_index][0] if frames else None
            panel.show(pump_mock.render(settings, frame, now=now, readings=readings))
            tick = 0.15 if settings["layout"] in ("aurora", "arcade") else 1.0
            deadline = min(next_stats, next_frame if frames else now + tick, now + tick)
            time.sleep(max(0.05, deadline - time.monotonic()))


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    ensure_presets()
    config.load()  # register user-defined metrics shared with the Thermaltake panel
    while RUNNING:
        if not pump_detect.present():
            publish(present=False, connected=False)
            time.sleep(2)
            continue
        try:
            run_panel()
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"pumpd: {exc}; retrying", file=sys.stderr, flush=True)
            publish(present=pump_detect.present(), connected=False, error=str(exc))
            time.sleep(5)
    publish(present=pump_detect.present(), connected=False)


if __name__ == "__main__":
    main()
