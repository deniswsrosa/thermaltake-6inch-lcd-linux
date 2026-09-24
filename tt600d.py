#!/usr/bin/env python3
"""tt600d — dashboard daemon for the Thermaltake 6.0" LCD Panel Kit.

Samples system sensors, renders the configured template and streams it to
the panel. Also serves a small settings page (default http://127.0.0.1:8600)
to pick a template, metrics, colours and brightness with a live preview.

Settings live in ~/.config/tt600/config.json and apply immediately.
The daemon reconnects if the panel disappears (replug, suspend/resume).
"""

import argparse
import io
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil

import sensors
import templates
import tt600

HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tt600" / "config.json"
DEFAULTS = {"template": "big", "slots": [], "accent": None, "accent2": None,
            "background": None, "unit": "C", "gpu": "all", "brightness": 100, "interval": 1.0}


class State:
    """Config and latest sensor values, shared by the render loop and the web UI."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.config = self._load()
        self.values = {k: None for k in sensors.METRICS}
        self.connected = None

    def _load(self):
        try:
            with open(self.path) as fh:
                return clean({**DEFAULTS, **json.load(fh)})
        except (OSError, ValueError):
            return dict(DEFAULTS)

    def get(self):
        with self.lock:
            return dict(self.config)

    def save(self, cfg):
        cfg = clean({**DEFAULTS, **cfg})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        tmp.replace(self.path)
        with self.lock:
            self.config = cfg
        return cfg


def clean(cfg):
    """Keep only known keys with sane values."""
    out = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    if out["template"] not in templates.TEMPLATES:
        out["template"] = "big"
    out["slots"] = [s for s in (out["slots"] or []) if s in sensors.METRICS][:4]
    for k in ("accent", "accent2", "background"):
        c = out[k]
        out[k] = c if isinstance(c, str) and len(c) == 7 and c.startswith("#") else None
    out["unit"] = "F" if out["unit"] == "F" else "C"
    out["gpu"] = out["gpu"] if out["gpu"] == "all" or str(out["gpu"]).isdigit() else "all"
    out["brightness"] = max(0, min(100, int(out["brightness"])))
    out["interval"] = max(0.5, min(4.0, float(out["interval"])))  # panel times out after 5 s
    return out


def png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _body(self):
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, (HERE / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._json({
                    "config": state.get(),
                    "resolved": templates.resolve(state.get()),
                    "connected": state.connected,
                    "gpus": sensors.gpu_count(),
                    "templates": {k: {kk: vv for kk, vv in t.items() if kk != "fn"}
                                  for k, t in templates.TEMPLATES.items()},
                    "metrics": {k: m.label or "(empty)" for k, m in sensors.METRICS.items()},
                })
            elif self.path.startswith("/api/preview"):
                self._send(200, png(templates.render(state.values, state.get())), "image/png")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            try:
                body = self._body()
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            if self.path == "/api/preview":
                cfg = clean({**DEFAULTS, **body})
                self._send(200, png(templates.render(state.values, cfg)), "image/png")
            elif self.path == "/api/config":
                cfg = state.save(body)
                self._json({"config": cfg, "resolved": templates.resolve(cfg)})
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


class Stop(Exception):
    pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", default="127.0.0.1", help="settings page address")
    ap.add_argument("--port", type=int, default=8600, help="settings page port (0 = off)")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--preview", metavar="PNG", help="render one frame to a file and exit")
    args = ap.parse_args()

    state = State(args.config)
    psutil.cpu_percent()  # prime the load counter
    if args.preview:
        time.sleep(0.5)
        cfg = state.get()
        templates.render(sensors.read(cfg["gpu"]), cfg).save(args.preview)
        return 0

    if args.port:
        server = ThreadingHTTPServer((args.listen, args.port), make_handler(state))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"tt600d: settings at http://{args.listen}:{args.port}", flush=True)

    def stop(*_):
        raise Stop
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    panel, brightness = None, None
    try:
        while True:
            t0 = time.monotonic()
            cfg = state.get()
            state.values = sensors.read(cfg["gpu"])
            try:
                if panel is None:
                    node = tt600.find_device()
                    if not node:
                        state.connected = False
                        time.sleep(5)
                        continue
                    panel = tt600.Panel(node)
                    status = panel.connect()
                    panel.realtime(True)
                    brightness = None
                    state.connected = True
                    print(f"tt600d: connected {node} (fw {status['version']['firmware']})", flush=True)
                if cfg["brightness"] != brightness:
                    panel.brightness(cfg["brightness"])
                    brightness = cfg["brightness"]
                panel.send_jpeg(tt600.to_jpeg(templates.render(state.values, cfg)))
            except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
                print(f"tt600d: {exc}; reconnecting", file=sys.stderr, flush=True)
                state.connected = False
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
