#!/usr/bin/env python3
"""tt600d — dashboard daemon for the Thermaltake 6.0" LCD Panel Kit.

Samples system sensors, renders the configured template and streams it to
the panel. Settings come from ~/.config/tt600/config.json (edited by the
tray app) and are reloaded whenever the file changes. Panel state is
published in $XDG_RUNTIME_DIR/tt600-status.json for the tray to show.

The daemon reconnects if the panel disappears (replug, suspend/resume).
"""

import argparse
import signal
import sys
import time
from pathlib import Path

import psutil

import config
import sensors
import templates
import tt600


class Stop(Exception):
    pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=config.CONFIG_PATH)
    ap.add_argument("--preview", metavar="PNG", help="render one frame to a file and exit")
    args = ap.parse_args()

    cfg, cfg_mtime = config.load(args.config), config.mtime(args.config)
    psutil.cpu_percent()  # prime the load counter
    if args.preview:
        time.sleep(0.5)
        templates.render(sensors.read(cfg["gpu"]), cfg).save(args.preview)
        return 0

    def stop(*_):
        raise Stop
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    status = {}

    def publish(**new):
        nonlocal status
        if new != status:
            status = new
            config.write_status(status)

    panel, brightness = None, None
    try:
        while True:
            t0 = time.monotonic()
            if config.mtime(args.config) != cfg_mtime:
                cfg, cfg_mtime = config.load(args.config), config.mtime(args.config)
            try:
                if panel is None:
                    node = tt600.find_device()
                    if not node:
                        publish(connected=False)
                        time.sleep(5)
                        continue
                    panel = tt600.Panel(node)
                    info = panel.connect()
                    panel.realtime(True)
                    brightness = None
                    publish(connected=True, node=node, firmware=info["version"]["firmware"])
                    print(f"tt600d: connected {node} (fw {info['version']['firmware']})", flush=True)
                if cfg["brightness"] != brightness:
                    panel.brightness(cfg["brightness"])
                    brightness = cfg["brightness"]
                values = sensors.read(cfg["gpu"])
                panel.send_jpeg(tt600.to_jpeg(templates.render(values, cfg)))
            except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
                print(f"tt600d: {exc}; reconnecting", file=sys.stderr, flush=True)
                publish(connected=False)
                if panel is not None:
                    try:
                        panel.close()
                    except OSError:
                        pass
                    panel = None
                time.sleep(2)
                continue
            time.sleep(max(0.0, cfg["interval"] - (time.monotonic() - t0)))
    except Stop:
        pass
    finally:
        if panel is not None:
            panel.close()
        publish(connected=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
