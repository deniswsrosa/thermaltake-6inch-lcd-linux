"""Settings shared by the tt600d daemon and the tray app.

The tray writes ~/.config/tt600/config.json; the daemon reloads it when it
changes. The daemon reports panel state in $XDG_RUNTIME_DIR/tt600-status.json.
"""

import json
import os
from pathlib import Path

import sensors
import templates

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tt600" / "config.json"
STATUS_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tt600-status.json"

DEFAULTS = {"template": "big", "slots": [], "accent": None, "accent2": None,
            "background": None, "unit": "C", "gpu": "all", "brightness": 100, "interval": 1.0}


def clean(cfg):
    """Keep only known keys with sane values."""
    out = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    if out["template"] not in templates.TEMPLATES:
        out["template"] = "big"
    out["slots"] = [s for s in (out["slots"] or []) if s in sensors.METRICS][:6]
    for k in ("accent", "accent2", "background"):
        c = out[k]
        out[k] = c if isinstance(c, str) and len(c) == 7 and c.startswith("#") else None
    out["unit"] = "F" if out["unit"] == "F" else "C"
    out["gpu"] = out["gpu"] if out["gpu"] == "all" or str(out["gpu"]).isdigit() else "all"
    out["brightness"] = max(0, min(100, int(out["brightness"])))
    out["interval"] = max(0.5, min(4.0, float(out["interval"])))  # panel times out after 5 s
    return out


def load(path=CONFIG_PATH):
    try:
        with open(path) as fh:
            return clean({**DEFAULTS, **json.load(fh)})
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(cfg, path=CONFIG_PATH):
    cfg = clean({**DEFAULTS, **cfg})
    _write_atomic(path, cfg)
    return cfg


def mtime(path=CONFIG_PATH):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def write_status(status, path=STATUS_PATH):
    _write_atomic(path, status)


def read_status(path=STATUS_PATH):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(path)
