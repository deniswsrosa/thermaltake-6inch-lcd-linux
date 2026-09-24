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
import time
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
    "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
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
        """Scale coordinates; accepts flat numbers or (x, y) pairs."""
        flat = [n for v in seq for n in (v if isinstance(v, (tuple, list)) else (v,))]
        return [n * SS for n in flat]

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

    def poly(self, points, fill):
        self.d.polygon([(x * SS, y * SS) for x, y in points], fill=fill)

    def circle(self, centre, r, fill, outline=None, width=0):
        x, y = centre
        self.d.ellipse(self._s((x - r, y - r, x + r, y + r)), fill=fill,
                       outline=outline, width=width * SS)

    def glow(self, draw, radius=16):
        """Run draw(canvas) on a black layer, blur it and add it as a glow."""
        from PIL import ImageChops, ImageFilter
        layer = Canvas.__new__(Canvas)
        layer.img = Image.new("RGB", self.img.size, "#000000")
        layer.d = ImageDraw.Draw(layer.img)
        draw(layer)
        small = layer.img.reduce(4).filter(ImageFilter.GaussianBlur(radius * SS / 4))
        self.img = ImageChops.add(self.img, small.resize(self.img.size, Image.BILINEAR))
        self.d = ImageDraw.Draw(self.img)

    def paste(self, img):
        self.img.paste(img.resize(self.img.size), (0, 0))

    def result(self):
        return self.img.reduce(SS)


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


_scenery = {}


def _synthwave_scenery(background, accent, accent2, n):
    """Sky, striped sun and perspective grid; depends only on colours, so it is cached."""
    key = (background, accent, accent2, n)
    if key not in _scenery:
        bg = Image.new("RGB", (W, H), background)
        d = ImageDraw.Draw(bg)
        horizon = 330
        for y in range(horizon):  # sky gradient
            d.line((0, y, W, y), fill=mix(background, mix(accent2, "#000000", 0.55), (y / horizon) ** 2))
        sun_r = 115 if n != 3 else 80
        for i in range(sun_r):  # striped sun
            y = horizon - sun_r + i
            half = int((sun_r ** 2 - (sun_r - i) ** 2) ** 0.5)
            if i > sun_r * 0.55 and (i // 9) % 2:
                continue
            d.line((W // 2 - half, y, W // 2 + half, y), fill=mix(accent, accent2, i / sun_r))
        d.rectangle((0, horizon, W, H), fill=mix(background, "#000000", 0.4))
        grid = mix(accent2, "#000000", 0.2)
        for i in range(-12, 13):  # converging lines
            d.line((W // 2 + i * 22, horizon, W // 2 + i * 190, H), fill=grid, width=2)
        y, step = horizon, 6
        while y < H:  # receding horizontals
            d.line((0, y, W, y), fill=grid, width=2)
            step *= 1.35
            y += step
        _scenery.clear()
        _scenery[key] = bg          # kept at 1x; scaled up per frame to save memory
    return _scenery[key].resize((W * SS, H * SS), Image.BILINEAR)


def synthwave(c, v, cfg):
    """AIDA64-style 80s neon: sunset, perspective grid, glowing numbers."""
    cols = columns(cfg)
    n, cw = len(cols), W / len(cols)
    c.img = _synthwave_scenery(cfg["background"], cfg["accent"], cfg["accent2"], n)
    c.d = ImageDraw.Draw(c.img)
    size = {1: 240, 2: 190, 3: 150}[n]
    numbers = []
    for i, (key, sub) in enumerate(cols):
        cx = cw * (i + 0.5)
        colour = status_colour(key, v[key], column_accent(cfg, i))
        numbers.append((cx, fmt(key, v[key], cfg), colour))
        c.text((cx, 250), fmt(key, v[key], cfg), size, "#ffffff", weight="cond", anchor="ms")
        c.text((cx, 62), label(key, cfg), 44 if n < 3 else 38, colour, anchor="mt")
        if sub != "none":
            fs = 34 if n < 3 else 26
            pill = f"{label(sub, cfg)}  {fmt(sub, v[sub], cfg)}"
            half = c.text_width(pill, fs) / 2 + 20
            c.rect((cx - half, 372, cx + half, 432), "#0b0414", radius=30, outline=colour, width=2)
            c.text((cx, 402), pill, fs, "#ffffff", anchor="mm")
    c.glow(lambda g: [g.text((x, 250), t, size, col, weight="cond", anchor="ms")
                      for x, t, col in numbers], 18)


def tiles(c, v, cfg):
    """Grid of cards (Corsair iCUE / Lian Li style), one big value each."""
    keys = [k for k in (slot(cfg, i) for i in range(6)) if k != "none"] or ["none"]
    n = len(keys)
    cols = n if n <= 3 else (2 if n == 4 else 3)
    rows = -(-n // cols)
    gap, pad = 16, 16
    tw = (W - 2 * pad - (cols - 1) * gap) / cols
    th = (H - 2 * pad - (rows - 1) * gap) / rows
    size = int(min(th * 0.5, tw * 0.36, 190))
    for i, key in enumerate(keys):
        x0 = pad + (i % cols) * (tw + gap)
        y0 = pad + (i // cols) * (th + gap)
        colour = status_colour(key, v[key], cfg["accent"])
        c.rect((x0, y0, x0 + tw, y0 + th), mix(cfg["background"], colour, 0.10), radius=22,
               outline=mix(cfg["background"], colour, 0.35), width=2)
        c.text((x0 + 26, y0 + 22), label(key, cfg), max(24, size // 4),
               mix(cfg["accent2"], "#ffffff", 0.2))
        c.text((x0 + tw / 2, y0 + th * 0.5 + size * 0.42), fmt(key, v[key], cfg), size,
               colour if colour != cfg["accent"] else "#ffffff", weight="cond", anchor="ms")
        bar(c, (x0 + 26, y0 + th - 34, x0 + tw - 26, y0 + th - 20),
            fraction(key, v[key]), colour, mix(cfg["background"], "#ffffff", 0.10))


_history = {}          # metric key -> deque of (time, value)
HISTORY_SECONDS = 300


def history(c, v, cfg):
    """Current values on top, a line chart of the last five minutes below."""
    import collections
    keys = [k for k in (slot(cfg, i) for i in range(3)) if k != "none"] or ["none"]
    palette = [cfg["accent"], cfg["accent2"], mix(cfg["accent"], cfg["accent2"], 0.5)]
    now = time.monotonic()
    for key in keys:
        series = _history.setdefault(key, collections.deque())
        if v[key] is not None and (not series or now - series[-1][0] >= 0.9):
            series.append((now, v[key]))
        while series and now - series[0][0] > HISTORY_SECONDS:
            series.popleft()

    cw = W / len(keys)
    for i, key in enumerate(keys):
        cx = cw * (i + 0.5)
        colour = status_colour(key, v[key], palette[i])
        c.text((cx, 26), label(key, cfg), 34, palette[i], anchor="mt")
        c.text((cx, 190), fmt(key, v[key], cfg), 130 if len(keys) > 1 else 160, colour,
               weight="cond", anchor="ms")

    x0, y0, x1, y1 = 40, 230, W - 40, H - 30
    grid = mix(cfg["background"], "#ffffff", 0.10)
    for f in (0, 0.25, 0.5, 0.75, 1):
        y = y1 - (y1 - y0) * f
        c.line((x0, y, x1, y), grid, 1 if f % 0.5 else 2)
    c.text((x1, y1 + 4), "now", 18, "#6b7280", weight=False, anchor="ra")
    c.text((x0, y1 + 4), f"-{HISTORY_SECONDS // 60} min", 18, "#6b7280", weight=False)
    lines = []
    for i, key in enumerate(keys):
        pts = [(x1 - (x1 - x0) * (now - t) / HISTORY_SECONDS, y1 - (y1 - y0) * fraction(key, val))
               for t, val in _history.get(key, ())]
        if len(pts) >= 2:
            lines.append((i, pts))
    if lines and lines[0][0] == 0:   # soft fill under the first line, behind everything
        pts = lines[0][1]
        c.poly(pts + [(pts[-1][0], y1), (pts[0][0], y1)], mix(cfg["background"], palette[0], 0.15))
    for i, pts in reversed(lines):
        c.line(pts, palette[i], 4)


_SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
             "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": ""}


def _seven_segment(c, x, y, w, h, char, on, off):
    t = w * 0.2         # segment thickness
    g = t * 0.18        # gap between segments
    slant = h * 0.07    # italic lean

    def lean(pts):
        return [(px + slant * (1 - (py - y) / h), py) for px, py in pts]

    def hseg(yc):
        a, b = x + t / 2 + g, x + w - t / 2 - g
        return lean([(a, yc), (a + t / 2, yc - t / 2), (b - t / 2, yc - t / 2), (b, yc),
                     (b - t / 2, yc + t / 2), (a + t / 2, yc + t / 2)])

    def vseg(xc, ya, yb):
        return lean([(xc, ya), (xc + t / 2, ya + t / 2), (xc + t / 2, yb - t / 2), (xc, yb),
                     (xc - t / 2, yb - t / 2), (xc - t / 2, ya + t / 2)])

    top, mid, bottom = y + t / 2, y + h / 2, y + h - t / 2
    shapes = {"a": hseg(top), "g": hseg(mid), "d": hseg(bottom),
              "f": vseg(x + t / 2, top + g, mid - g), "b": vseg(x + w - t / 2, top + g, mid - g),
              "e": vseg(x + t / 2, mid + g, bottom - g), "c": vseg(x + w - t / 2, mid + g, bottom - g)}
    lit = _SEGMENTS.get(char, "g")
    for name, pts in shapes.items():
        c.poly(pts, on if name in lit else off)


def digital(c, v, cfg):
    """Seven-segment LCD digits with ghosted unlit segments."""
    cols = columns(cfg)
    n, cw = len(cols), W / len(cols)
    base_h = {1: 300, 2: 250, 3: 190}[n]
    lit = []
    for i, (key, sub) in enumerate(cols):
        accent = column_accent(cfg, i)
        colour = status_colour(key, v[key], accent)
        text = fmt(key, v[key], cfg, with_unit=False)
        h = base_h
        w = h * 0.5
        step = w * 1.18
        while len(text) * step > cw - 70:   # shrink long numbers (RPM, watts)
            h *= 0.9
            w, step = h * 0.5, h * 0.5 * 1.18
        total = len(text) * step - (step - w)
        x, y = cw * (i + 0.5) - total / 2 - 12, 130 + (base_h - h) / 2
        c.text((cw * (i + 0.5), 50), label(key, cfg), 40 if n < 3 else 34,
               mix(accent, "#ffffff", 0.3), anchor="mt")
        for j, ch in enumerate(text):
            lit.append((x + j * step, y, w, h, ch, colour))
            _seven_segment(c, x + j * step, y, w, h, ch, colour,
                           mix(cfg["background"], accent, 0.07))
        c.text((x + total + 16, y + 6), unit_suffix(key, cfg), 30, colour)
        if sub != "none":
            c.text((cw * (i + 0.5), 500), f"{label(sub, cfg)}  {fmt(sub, v[sub], cfg)}",
                   30 if n < 3 else 26, mix(accent, "#ffffff", 0.5), anchor="ms")
    c.glow(lambda g: [_seven_segment(g, *args[:5], args[5], "#000000") for args in lit], 12)


def speedometer(c, v, cfg):
    """Car-dashboard needle gauges with green/amber/red zones."""
    import math
    cols = columns(cfg)
    n, cw = len(cols), W / len(cols)
    r = min(215, cw / 2 - 30)
    cy = 300 if n < 3 else 285
    for i, (key, sub) in enumerate(cols):
        m = METRICS[key]
        cx = cw * (i + 0.5)
        box = (cx - r, cy - r, cx + r, cy + r)
        stroke = max(14, int(r * 0.11))
        if m.warn is not None:
            zones = [(0, m.warn / m.max, "#2fbf71"), (m.warn / m.max, m.crit / m.max, WARN),
                     (m.crit / m.max, 1, CRIT)]
        else:
            zones = [(0, 1, column_accent(cfg, i))]
        for a, b, colour in zones:
            c.arc(box, 180 + 180 * a, 180 + 180 * min(b, 1), mix(cfg["background"], colour, 0.75), stroke)
        for k in range(11):   # ticks
            ang = math.radians(180 + 18 * k)
            r0 = r - stroke - (22 if k % 5 == 0 else 12)
            c.line((cx + math.cos(ang) * r0, cy + math.sin(ang) * r0,
                    cx + math.cos(ang) * (r - stroke - 4), cy + math.sin(ang) * (r - stroke - 4)),
                   "#c8ccd4", 4 if k % 5 == 0 else 2)
        ang = math.radians(180 + 180 * fraction(key, v[key]))
        tip = (cx + math.cos(ang) * (r - stroke - 16), cy + math.sin(ang) * (r - stroke - 16))
        c.line((cx, cy, *tip), "#ffffff", 7)
        c.circle((cx, cy), 16, column_accent(cfg, i), outline="#ffffff", width=3)
        c.text((cx, cy + 34), label(key, cfg), 34 if n < 3 else 28,
               mix(column_accent(cfg, i), "#ffffff", 0.3), anchor="mt")
        c.text((cx, cy + (150 if n < 3 else 135)), fmt(key, v[key], cfg), 96 if n < 3 else 80,
               status_colour(key, v[key], "#ffffff"), weight="cond", anchor="ms")
        if sub != "none":
            c.text((cx, H - 14), f"{label(sub, cfg)}  {fmt(sub, v[sub], cfg)}",
                   28 if n < 3 else 24, "#a0a6b2", anchor="ms")


def terminal(c, v, cfg):
    """Retro green console: monospace rows, text bars, scanlines and a blinking cursor."""
    keys = [k for k in (slot(cfg, i) for i in range(5)) if k != "none"] or ["none"]
    fg, dim = cfg["accent"], cfg["accent2"]
    size = int(min(62, (H - 130) / len(keys) * 0.62))
    char_w = c.text_width("0", size, "mono")
    label_w = max(len(label(k, cfg)) for k in keys) + 1
    value_w = max(6, max(len(fmt(k, v[k], cfg)) for k in keys))
    bar_chars = max(4, int((W - 80) / char_w) - label_w - value_w - 4)
    lines = []
    for key in keys:
        filled = round(fraction(key, v[key]) * bar_chars)
        text = (f"{label(key, cfg):<{label_w}}{fmt(key, v[key], cfg):>{value_w}}  "
                f"[{'#' * filled}{'.' * (bar_chars - filled)}]")
        lines.append((text, status_colour(key, v[key], fg)))

    prompt = "tt600@panel:~$ watch sensors"

    def draw(target):
        target.text((40, 30), prompt, 30, dim, weight="mono")
        top, row_h = 100, (H - 150) / len(keys)
        for j, (text, colour) in enumerate(lines):
            target.text((40, top + j * row_h + row_h / 2), text, size, colour, weight="mono",
                        anchor="lm")
        x = 40 + target.text_width(prompt + " ", 30, "mono")   # cursor
        target.rect((x, 32, x + 18, 64), dim)

    draw(c)
    c.glow(draw, 10)
    shade = mix(cfg["background"], "#000000", 0.6)
    for y in range(0, H, 4):   # scanlines
        c.line((0, y, W, y), shade, 1)


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
    "tiles":     {"fn": tiles, "name": "Tiles (iCUE style)",
                  "slots": [f"Tile {i}" for i in range(1, 7)],
                  "accent": "#4f8cff", "accent2": "#c9ced8", "background": "#0c0e13"},
    "history":   {"fn": history, "name": "History graph", "live": True,
                  "slots": ["Line 1", "Line 2", "Line 3"],
                  "accent": "#ff7a45", "accent2": "#76b900", "background": "#0b0d12"},
    "digital":   {"fn": digital, "name": "Digital (7-segment)",
                  "slots": [s.replace("bar", "footer") for s in COLUMN_SLOTS],
                  "accent": "#ff453a", "accent2": "#30d5ff", "background": "#0a0606"},
    "speedometer": {"fn": speedometer, "name": "Speedometer",
                    "slots": [s.replace("bar", "footer") for s in COLUMN_SLOTS],
                    "accent": "#4f8cff", "accent2": "#76b900", "background": "#0d0f14"},
    "terminal":  {"fn": terminal, "name": "Terminal (retro)",
                  "slots": [f"Row {i}" for i in range(1, 6)],
                  "accent": "#33ff66", "accent2": "#1f9d45", "background": "#020a04"},
}


def defaults(name, gpus=None):
    """Default metrics for a template: one column/row per GPU when there are several."""
    gpus = sensors.gpu_count() if gpus is None else gpus
    if "defaults" in TEMPLATES.get(name, {}):
        return list(TEMPLATES[name]["defaults"])
    if name == "single":
        return ["cpu_temp", "cpu_load"]
    if name == "tiles":
        if gpus >= 2:
            return ["cpu_temp", "gpu0_temp", "gpu1_temp", "cpu_load", "gpu0_load", "gpu1_load"]
        return ["cpu_temp", "gpu_temp", "ssd_temp", "cpu_load", "gpu_load", "ram"]
    if name == "history":
        return ["cpu_temp", "gpu0_temp", "gpu1_temp"] if gpus >= 2 else ["cpu_temp", "gpu_temp", "cpu_load"]
    if name == "terminal":
        if gpus >= 2:
            return ["cpu_temp", "cpu_load", "gpu0_temp", "gpu1_temp", "ram"]
        return ["cpu_temp", "cpu_load", "gpu_temp", "gpu_load", "ram"]
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


def frame_key(values, cfg):
    """What a frame shows: if this is unchanged, the previous frame can be re-sent."""
    cfg = resolve(cfg)
    if TEMPLATES[cfg["template"]].get("live"):
        return None
    shown = tuple(None if values.get(k) is None else round(values[k]) for k in cfg["slots"])
    return shown, repr(sorted(cfg.items()))


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
                                    "live": bool(meta.get("live")),
                                    **({"defaults": list(meta["defaults"])} if "defaults" in meta else {})}
        except Exception as exc:
            print(f"tt600: skipping template {path}: {exc}", file=sys.stderr)


load_plugins()
