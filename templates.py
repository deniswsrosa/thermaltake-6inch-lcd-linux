"""Dashboard templates for the tt600 panel (1110x540).

Every template is built to be read from a distance: few metrics, very large
numbers. A template takes (canvas, values, cfg) and draws in panel pixels;
the canvas supersamples 2x so text and arcs come out smooth.

cfg keys used here: slots (list of metric keys), accent, accent2,
background, unit ("C" or "F").
"""

import importlib.util
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

import sensors
from sensors import METRICS

W, H = 1110, 540
SS = 2  # supersampling factor

FONTS = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "cond": "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
}
_font_cache = {}

WARN, CRIT = "#ffb020", "#ff4d4d"


_custom_font = None   # set per render from cfg["font"]


def _font(size, weight):
    path = _custom_font or FONTS[weight]
    key = (size, path)
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except OSError:
            _font_cache[key] = ImageFont.truetype(FONTS[weight], size) if _custom_font else \
                ImageFont.load_default()
    return _font_cache[key]


class Canvas:
    """PIL drawing in panel coordinates on a supersampled image."""

    def __init__(self, background, image=None, dim=50):
        self.img = _background(background, image, dim)
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def _s(seq):
        return [v * SS for v in seq]

    def text(self, xy, text, size, fill, weight=True, anchor="la"):
        self.d.text(self._s(xy), text, font=_font(size * SS, weight), fill=fill, anchor=anchor)

    def text_width(self, text, size, weight=True):
        return self.d.textlength(text, font=_font(size * SS, weight)) / SS

    def rect(self, box, fill, radius=0, outline=None, width=0):
        self.d.rounded_rectangle(self._s(box), radius=radius * SS, fill=fill,
                                 outline=outline, width=width * SS)

    def arc(self, box, start, end, fill, width):
        self.d.arc(self._s(box), start, end, fill=fill, width=width * SS)

    def line(self, points, fill, width=1):
        self.d.line(self._s(points), fill=fill, width=width * SS)

    def paste(self, img):
        self.img.paste(img.resize(self.img.size), (0, 0))

    def result(self):
        return self.img.resize((W, H), Image.LANCZOS)


_bg_cache = {}


def _background(colour, path, dim):
    """Solid colour, or an image cover-fitted to the panel and dimmed toward colour."""
    if not path:
        return Image.new("RGB", (W * SS, H * SS), colour)
    try:
        key = (path, os.path.getmtime(path), colour, dim)
    except OSError:
        return Image.new("RGB", (W * SS, H * SS), colour)
    if key not in _bg_cache:
        try:
            img = ImageOps.fit(Image.open(path).convert("RGB"), (W * SS, H * SS), Image.LANCZOS)
            img = Image.blend(img, Image.new("RGB", img.size, colour), dim / 100)
        except OSError:
            img = Image.new("RGB", (W * SS, H * SS), colour)
        _bg_cache.clear()
        _bg_cache[key] = img
    return _bg_cache[key].copy()


# ── value helpers ────────────────────────────────────────────────────────────
def label(key, cfg):
    """Metric label, unless the user renamed it in cfg["labels"]."""
    return (cfg.get("labels") or {}).get(key) or METRICS[key].label


def fmt(key, value, cfg, with_unit=True):
    m = METRICS[key]
    if key == "none":
        return ""
    if value is None:
        return "--"
    if m.unit == "temp":
        if cfg.get("unit") == "F":
            value = value * 9 / 5 + 32
        return f"{value:.0f}°" if with_unit else f"{value:.0f}"
    if m.unit == "%":
        return f"{value:.0f}%" if with_unit else f"{value:.0f}"
    return f"{value:.0f} {m.unit}".strip() if with_unit else f"{value:.0f}"


def unit_suffix(key, cfg):
    u = METRICS[key].unit
    return ("°F" if cfg.get("unit") == "F" else "°C") if u == "temp" else u


def fraction(key, value):
    if value is None or key == "none":
        return 0.0
    return max(0.0, min(1.0, value / METRICS[key].max))


def status_colour(key, value, normal):
    m = METRICS[key]
    if value is None or m.warn is None:
        return normal
    if value >= m.crit:
        return CRIT
    if value >= m.warn:
        return WARN
    return normal


def slot(cfg, i, default="none"):
    slots = cfg.get("slots", [])
    key = slots[i] if i < len(slots) else default
    return key if key in METRICS else "none"


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def bar(c, box, frac, colour, track):
    x0, y0, x1, y1 = box
    r = (y1 - y0) // 2
    c.rect(box, track, radius=r)
    if frac > 0:
        c.rect((x0, y0, max(x0 + 2 * r, x0 + (x1 - x0) * frac), y1), colour, radius=r)


# ── templates ────────────────────────────────────────────────────────────────
def columns(cfg):
    """(value, secondary) pairs for column templates, skipping empty columns."""
    pairs = [(slot(cfg, 2 * i), slot(cfg, 2 * i + 1)) for i in range(3)]
    return [p for p in pairs if p[0] != "none"] or [("none", "none")]


def column_accent(cfg, i):
    return cfg["accent"] if i == 0 else cfg["accent2"]


def big(c, v, cfg):
    """Giant numbers in up to three columns, each with a thick bar below."""
    cols = columns(cfg)
    n, cw = len(cols), W / len(cols)
    size = {1: 300, 2: 220, 3: 165}[n]
    track = mix(cfg["background"], "#ffffff", 0.12)
    for i, (key, sub) in enumerate(cols):
        accent = column_accent(cfg, i)
        cx = cw * (i + 0.5)
        c.text((cx, 58), label(key, cfg), 44 if n < 3 else 38,
               mix(accent, "#ffffff", 0.35), anchor="mt")
        c.text((cx, 300), fmt(key, v[key], cfg), size,
               status_colour(key, v[key], accent), weight="cond", anchor="ms")
        if sub != "none":
            x0, x1 = cx - cw / 2 + 36, cx + cw / 2 - 36
            fs = 30 if n < 3 else 26
            c.text((x0, 360), label(sub, cfg), fs, "#a0a6b2", weight=False)
            c.text((x1, 356), fmt(sub, v[sub], cfg), fs + 10, "#ffffff", anchor="ra")
            bar(c, (x0, 420, x1, 460), fraction(sub, v[sub]), accent, track)
        if i:
            c.line((cw * i, 70, cw * i, 470), mix(cfg["background"], "#ffffff", 0.15), 3)


def gauges(c, v, cfg):
    """NZXT Kraken style: up to three ring gauges with the value in the middle."""
    cols = columns(cfg)
    n, cw = len(cols), W / len(cols)
    r = min(205, cw / 2 - 28)
    cy = 250 if n < 3 else 232
    stroke = 34 if n < 3 else 28
    track = mix(cfg["background"], "#ffffff", 0.12)
    for i, (key, sub) in enumerate(cols):
        accent = column_accent(cfg, i)
        cx = cw * (i + 0.5)
        box = (cx - r, cy - r, cx + r, cy + r)
        c.arc(box, 135, 405, track, stroke)
        frac = fraction(key, v[key])
        if frac > 0:
            c.arc(box, 135, 135 + 270 * frac, status_colour(key, v[key], accent), stroke)
        c.text((cx, cy + r * 0.28), fmt(key, v[key], cfg, with_unit=False), int(r * 0.73),
               "#ffffff", weight="cond", anchor="ms")
        c.text((cx, cy - r * 0.45), label(key, cfg), int(r * 0.19),
               mix(accent, "#ffffff", 0.35), anchor="mm")
        c.text((cx, cy + r * 0.49), unit_suffix(key, cfg), int(r * 0.15), "#a0a6b2",
               weight=False, anchor="mm")
        if sub != "none":
            c.text((cx, 515), f"{label(sub, cfg)}  {fmt(sub, v[sub], cfg)}",
                   36 if n < 3 else 28, "#ffffff", anchor="ms")


def bars(c, v, cfg):
    """AIDA64 SensorPanel style: up to four rows of label, value and thick bar."""
    keys = [k for k in (slot(cfg, i) for i in range(4)) if k != "none"] or ["none"]
    accents = (cfg["accent"], cfg["accent2"])
    track = mix(cfg["background"], "#ffffff", 0.12)
    row_h = (H - 40) / len(keys)
    for i, key in enumerate(keys):
        y = 20 + i * row_h
        accent = accents[i % 2]
        colour = status_colour(key, v[key], accent)
        size = min(96, int(row_h * 0.5))
        c.text((40, y + row_h * 0.55), label(key, cfg), int(size * 0.6),
               mix(accent, "#ffffff", 0.35), anchor="ls")
        c.text((W - 40, y + row_h * 0.55), fmt(key, v[key], cfg), size, colour,
               weight="cond", anchor="rs")
        bh = max(16, int(row_h * 0.16))
        bar(c, (40, y + row_h * 0.66, W - 40, y + row_h * 0.66 + bh),
            fraction(key, v[key]), colour, track)


def single(c, v, cfg):
    """One metric, as large as the panel allows, with an optional second below."""
    key, sub = slot(cfg, 0, "cpu_temp"), slot(cfg, 1)
    colour = status_colour(key, v[key], cfg["accent"])
    c.text((W // 2, 70), label(key, cfg), 56, mix(cfg["accent"], "#ffffff", 0.35),
           anchor="mt")
    c.text((W // 2, 400), fmt(key, v[key], cfg), 330, colour, weight="cond", anchor="ms")
    if sub != "none":
        c.text((W // 2, 500), f"{label(sub, cfg)}  {fmt(sub, v[sub], cfg)}", 48,
               cfg["accent2"], anchor="ms")


def synthwave(c, v, cfg):
    """AIDA64-style 80s neon: sunset, perspective grid, glowing numbers."""
    from PIL import ImageChops, ImageFilter
    cols = columns(cfg)
    n, cw = len(cols), W / len(cols)
    bg = Image.new("RGB", (W, H), cfg["background"])
    d = ImageDraw.Draw(bg)
    horizon = 330
    for y in range(horizon):  # sky gradient
        d.line((0, y, W, y), fill=mix(cfg["background"], mix(cfg["accent2"], "#000000", 0.55),
                                      (y / horizon) ** 2))
    sun_r = 115 if n != 3 else 80
    for i in range(sun_r):  # striped sun
        y = horizon - sun_r + i
        half = int((sun_r ** 2 - (sun_r - i) ** 2) ** 0.5)
        if i > sun_r * 0.55 and (i // 9) % 2:
            continue
        d.line((W // 2 - half, y, W // 2 + half, y),
               fill=mix(cfg["accent"], cfg["accent2"], i / sun_r))
    d.rectangle((0, horizon, W, H), fill=mix(cfg["background"], "#000000", 0.4))
    grid = mix(cfg["accent2"], "#000000", 0.2)
    for i in range(-12, 13):  # converging lines
        d.line((W // 2 + i * 22, horizon, W // 2 + i * 190, H), fill=grid, width=2)
    y, step = horizon, 6
    while y < H:  # receding horizontals
        d.line((0, y, W, y), fill=grid, width=2)
        step *= 1.35
        y += step
    c.paste(bg)

    glow = Image.new("RGB", (W * SS, H * SS), "#000000")
    g = Canvas.__new__(Canvas)
    g.img, g.d = glow, ImageDraw.Draw(glow)
    size = {1: 240, 2: 190, 3: 150}[n]
    for i, (key, sub) in enumerate(cols):
        cx = cw * (i + 0.5)
        colour = status_colour(key, v[key], column_accent(cfg, i))
        for target, fill in ((g, colour), (c, "#ffffff")):
            target.text((cx, 250), fmt(key, v[key], cfg), size, fill, weight="cond", anchor="ms")
        c.text((cx, 62), label(key, cfg), 44 if n < 3 else 38, colour, anchor="mt")
        if sub != "none":
            fs = 34 if n < 3 else 26
            pill = f"{label(sub, cfg)}  {fmt(sub, v[sub], cfg)}"
            half = c.text_width(pill, fs) / 2 + 20
            c.rect((cx - half, 372, cx + half, 432), "#0b0414", radius=30, outline=colour, width=2)
            c.text((cx, 402), pill, fs, "#ffffff", anchor="mm")
    halo = glow.filter(ImageFilter.GaussianBlur(18 * SS))
    c.img = ImageChops.add(c.img, halo)
    c.d = ImageDraw.Draw(c.img)


COLUMN_SLOTS = ["Column 1 value", "Column 1 bar", "Column 2 value", "Column 2 bar",
                "Column 3 value", "Column 3 bar"]

TEMPLATES = {
    "big":       {"fn": big, "name": "Big numbers", "slots": COLUMN_SLOTS,
                  "accent": "#ff7a45", "accent2": "#76b900", "background": "#0b0d12"},
    "gauges":    {"fn": gauges, "name": "Ring gauges (Kraken style)",
                  "slots": [s.replace("bar", "footer") for s in COLUMN_SLOTS],
                  "accent": "#00c2ff", "accent2": "#b36bff", "background": "#07080c"},
    "bars":      {"fn": bars, "name": "Bars (SensorPanel style)",
                  "slots": ["Row 1", "Row 2", "Row 3", "Row 4"],
                  "accent": "#35e0a1", "accent2": "#3fb8ff", "background": "#0a0f14"},
    "single":    {"fn": single, "name": "Single metric", "slots": ["Main value", "Footer"],
                  "accent": "#ffffff", "accent2": "#8f98a8", "background": "#000000"},
    "synthwave": {"fn": synthwave, "name": "Synthwave (neon)",
                  "slots": [s.replace("bar", "footer") for s in COLUMN_SLOTS],
                  "accent": "#ff3fa4", "accent2": "#29e7ff", "background": "#12021f"},
}


def defaults(name, gpus=None):
    """Default metrics for a template: one column/row per GPU when there are several."""
    gpus = sensors.gpu_count() if gpus is None else gpus
    if "defaults" in TEMPLATES.get(name, {}):
        return list(TEMPLATES[name]["defaults"])
    if name == "single":
        return ["cpu_temp", "cpu_load"]
    if name == "bars":
        if gpus >= 2:
            return ["cpu_temp", "gpu0_temp", "gpu1_temp", "cpu_load"]
        return ["cpu_temp", "gpu_temp", "cpu_load", "gpu_load"]
    if gpus >= 2:
        return ["cpu_temp", "cpu_load", "gpu0_temp", "gpu0_load", "gpu1_temp", "gpu1_load"]
    return ["cpu_temp", "cpu_load", "gpu_temp", "gpu_load", "none", "none"]


def resolve(cfg):
    """Fill template defaults into cfg for any unset keys."""
    name = cfg.get("template") if cfg.get("template") in TEMPLATES else "big"
    t = TEMPLATES[name]
    out = dict(cfg, template=name)
    for k in ("accent", "accent2", "background"):
        out[k] = cfg.get(k) or t[k]
    slots, dflt = list(cfg.get("slots") or []), defaults(name)
    dflt += ["none"] * (len(t["slots"]) - len(dflt))
    out["slots"] = [slots[i] if i < len(slots) and slots[i] in METRICS else dflt[i]
                    for i in range(len(t["slots"]))]
    return out


def render(values, cfg):
    global _custom_font
    cfg = resolve(cfg)
    _custom_font = cfg.get("font") or None
    values = {**{k: None for k in METRICS}, **values}
    c = Canvas(cfg["background"], cfg.get("background_image"), cfg.get("background_dim", 50))
    try:
        TEMPLATES[cfg["template"]]["fn"](c, values, cfg)
    except Exception as exc:  # a broken plugin template must not take the daemon down
        c = Canvas("#000000")
        c.text((W // 2, H // 2), f"template error: {exc}"[:60], 30, "#ff4d4d", anchor="mm")
    return c.result()


# ── user templates ───────────────────────────────────────────────────────────
PLUGIN_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tt600" / "templates"


def load_plugins(directory=PLUGIN_DIR):
    """Load user templates: each <name>.py defines TEMPLATE (dict) and draw(c, values, cfg).

    TEMPLATE keys: "name", "slots" (list of slot names), and optionally
    "defaults" (metric per slot), "accent", "accent2", "background".
    Errors are reported and the file is skipped.
    """
    for path in sorted(Path(directory).glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"tt600_template_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            meta = dict(module.TEMPLATE)
            TEMPLATES[path.stem] = {"fn": module.draw, "name": meta.get("name", path.stem),
                                    "slots": list(meta["slots"]),
                                    "accent": meta.get("accent", "#ffffff"),
                                    "accent2": meta.get("accent2", "#8f98a8"),
                                    "background": meta.get("background", "#000000"),
                                    **({"defaults": list(meta["defaults"])} if "defaults" in meta else {})}
        except Exception as exc:
            print(f"tt600: skipping template {path}: {exc}", file=sys.stderr)


load_plugins()
