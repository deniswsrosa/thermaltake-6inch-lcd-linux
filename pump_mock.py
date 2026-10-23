#!/usr/bin/env python3
"""Renderer and editor for the ID-COOLING pump LCD."""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import os
import random
import time
from pathlib import Path

import gi
import sensors

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageSequence  # noqa: E402

from pump_presets import PRESETS, PRESET_DIR, ensure_presets  # noqa: E402

SIZE = 480
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tt600"
CONFIG_PATH = CONFIG_DIR / "pump.json"
DRAFT_PATH = CONFIG_DIR / "pump-mock.json"
STATUS_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tt600-pump-status.json"
METRICS = {
    "cpu_temp": "CPU temperature", "gpu_temp": "GPU temperature",
    "cpu_load": "CPU usage", "gpu_load": "GPU usage",
    "ram": "RAM usage", "gpu_vram": "GPU memory", "fan": "Pump speed",
}
PALETTES = {
    "arctic": ("Arctic", "#0a1622", "#63e0f5", "#ffa96b"),
    "ember": ("Ember", "#20100f", "#ffb36a", "#ff6e88"),
    "violet": ("Violet", "#160f25", "#ce9dff", "#67e2dc"),
    "lime": ("Circuit", "#0b180f", "#a3f36c", "#69d7e5"),
}
LAYOUTS = {
    "event_horizon": "Event horizon", "aurora": "Aurora flow",
    "arcade": "Pixel arcade",
    "hero": "Concentric", "dual": "Clean dual", "quad": "Monitor tiles",
    "rings": "Single bar", "fade_fill": "Fade fill",
    "fan_sensor": "Fan sensor", "cyberpunk": "Cyberpunk",
    "gif_only": "GIF only", "gif_overlay": "GIF + one stat",
    "gif_stat": "GIF + four stats", "clock": "Clockface",
}
GIF_STYLES = {
    "big": "Big number", "balanced": "Balanced",
    "left": "Left aligned", "right": "Right aligned",
    "quiet": "Small caption", "mono": "Monospace",
    "number_only": "Number only", "disc": "Circle readout",
}
GIF_POSITIONS = {"top": "Top", "center": "Center", "bottom": "Bottom",
                 "left": "Left", "right": "Right"}
SLOTS = ("top", "left", "right", "bottom")
LAYOUT_SLOTS = {
    "event_horizon": ("top", "bottom"), "aurora": ("top", "bottom"),
    "arcade": ("top", "bottom"), "hero": SLOTS, "dual": SLOTS,
    "quad": SLOTS, "rings": ("top", "bottom"),
    "fade_fill": ("top", "bottom"), "fan_sensor": ("top", "bottom"),
    "cyberpunk": ("top", "left", "right"), "gif_only": (),
    "gif_overlay": ("top",), "gif_stat": SLOTS,
    "clock": ("left", "right", "bottom"),
}
DEFAULTS = {
    "palette": "arctic", "layout": "event_horizon", "animation": "matrix", "custom_gif": None,
    "rotation": 0, "brightness": 75, "gif_size": 400,
    "gif_style": "left", "gif_position": "bottom",
    "top": "cpu_temp", "left": "cpu_load", "right": "gpu_load",
    "bottom": "gpu_temp",
}


def clean(data: dict) -> dict:
    result = dict(DEFAULTS)
    if isinstance(data, dict):
        result.update({k: v for k, v in data.items() if k in result})
    if result["palette"] not in PALETTES:
        result["palette"] = DEFAULTS["palette"]
    if result["layout"] not in LAYOUTS:
        result["layout"] = DEFAULTS["layout"]
    if result["animation"] not in ("none", "custom", *PRESETS):
        result["animation"] = DEFAULTS["animation"]
    old_styles = {"halo": "balanced", "spotlight": "balanced",
                  "outline": "big", "pixel": "number_only", "neon": "number_only",
                  "editorial": "big", "badge": "disc", "inline": "left"}
    result["gif_style"] = old_styles.get(result["gif_style"], result["gif_style"])
    if result["gif_style"] not in GIF_STYLES:
        result["gif_style"] = DEFAULTS["gif_style"]
    if result["gif_position"] not in GIF_POSITIONS:
        result["gif_position"] = DEFAULTS["gif_position"]
    for slot in SLOTS:
        if result[slot] not in (*METRICS, "none"):
            result[slot] = DEFAULTS[slot]
    result["rotation"] = int(result["rotation"]) if str(result["rotation"]).isdigit() else 0
    if result["rotation"] not in (0, 90, 180, 270):
        result["rotation"] = 0
    try:
        result["brightness"] = max(20, min(100, int(result["brightness"])))
        result["gif_size"] = max(280, min(440, int(result["gif_size"])))
    except (TypeError, ValueError):
        result["brightness"] = DEFAULTS["brightness"]
        result["gif_size"] = DEFAULTS["gif_size"]
    result["custom_gif"] = str(result["custom_gif"]) if result["custom_gif"] else None
    return result


def load(path: Path = CONFIG_PATH) -> dict:
    try:
        return clean(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def save(settings: dict, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean(settings), indent=2))
    temporary.replace(path)


def read_status() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text())
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=96)
def font(size: int, bold: bool = False, mono: bool = False, serif: bool = False):
    name = (("DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf") if serif else
            (("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf") if mono else
             ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")))
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(path, size) if path.exists() else ImageFont.load_default()


def sample_values(now: float) -> dict[str, str]:
    return {
        "cpu_temp": f"{65 + 4 * math.sin(now / 5):.0f}",
        "gpu_temp": f"{60 + 7 * math.sin(now / 7):.0f}",
        "cpu_load": f"{35 + 18 * math.sin(now / 3):.0f}%",
        "gpu_load": f"{54 + 26 * math.sin(now / 4):.0f}%",
        "ram": f"{42 + 2 * math.sin(now / 9):.0f}%",
        "gpu_vram": f"{59 + 4 * math.sin(now / 11):.0f}%",
        "fan": f"{2450 + 90 * math.sin(now / 6):.0f}",
    }


def format_values(raw: dict[str, float | None]) -> dict[str, str]:
    """Format readings from the shared sensor collector for this LCD."""
    result = {}
    for key in METRICS:
        value = raw.get(key)
        if value is None:
            result[key] = "--"
        elif key in ("cpu_load", "gpu_load", "ram", "gpu_vram"):
            result[key] = f"{value:.0f}%"
        else:
            result[key] = f"{value:.0f}"
    return result


def load_gif(path: Path) -> list[Image.Image]:
    if path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("Please choose a GIF smaller than 25 MB for the mock preview")
    frames = []
    with Image.open(path) as gif:
        if gif.format != "GIF":
            raise ValueError("Choose a GIF file")
        for frame in ImageSequence.Iterator(gif):
            frames.append(frame.convert("RGB"))
            if len(frames) >= 120:
                break
    if not frames:
        raise ValueError("The GIF contains no frames")
    return frames


@lru_cache(maxsize=1)
def arcade_frames() -> tuple[Image.Image, ...]:
    try:
        return tuple(load_gif(PRESET_DIR / PRESETS["cat"][1]))
    except (OSError, ValueError):
        return ()


def render(settings: dict, frame: Image.Image | None = None, now: float | None = None,
           readings: dict[str, str] | None = None) -> Image.Image:
    """Draw the 480×480 LCD image; this function never opens a device."""
    settings = clean(settings)
    now = time.monotonic() if now is None else now
    values = sample_values(now) if readings is None else readings
    _, background, accent, accent2 = PALETTES[settings["palette"]]
    layout = settings["layout"]
    style_backgrounds = {
        "event_horizon": "#070714", "aurora": "#100d28", "arcade": "#17122c",
        "hero": "#06080d", "dual": "#050608", "quad": "#edf2f4",
        "rings": "#0b0b1a", "fade_fill": "#080e1b", "fan_sensor": "#101216",
        "cyberpunk": "#160c09", "gif_stat": "#030506", "gif_only": "#030506",
        "gif_overlay": "#030506",
        "clock": "#f1eee5",
    }
    background = style_backgrounds.get(layout, background)
    style_accents = {
        "event_horizon": ("#ffbd69", "#be83ff"),
        "aurora": ("#a7f4e0", "#ec9af7"),
        "arcade": ("#ffdc74", "#f799c9"),
        "hero": ("#70e2f4", "#ffb66e"), "dual": ("#f6f8fb", "#a7d9ed"),
        "quad": ("#16758f", "#b65f31"), "rings": ("#d66cff", "#4be7f6"),
        "fade_fill": ("#1176c1", "#e1f5ff"), "fan_sensor": ("#fafafa", "#f7a55d"),
        "cyberpunk": ("#ffca3b", "#f25738"), "gif_stat": ("#ffdb75", "#f7f9fa"),
        "gif_only": ("#f7f9fa", "#f7f9fa"),
        "gif_overlay": ("#e4faff", "#a5f5ff"), "clock": ("#20334b", "#bc513a"),
    }
    accent, accent2 = style_accents.get(layout, (accent, accent2))
    foreground = "#152431" if layout in ("quad", "clock") else "#f5fbff"
    image = Image.new("RGB", (SIZE, SIZE), background)
    draw = ImageDraw.Draw(image)

    def text(x: int, y: int, value: str, size: int, color: str | None = None,
             bold: bool = True, anchor: str = "mt", stroke: int = 0,
             max_width: int | None = None, mono: bool = False, serif: bool = False,
             stroke_color: str | None = None):
        # Fit actual glyph bounds, including stroke, inside the circular safe
        # area. Recompute after each size change: RPM readings are much wider
        # than temperatures, and their height shrinks along with their width.
        while True:
            face = font(size, bold, mono or layout == "cyberpunk", serif)
            bounds = draw.textbbox((x, y), value, font=face, anchor=anchor,
                                   stroke_width=stroke)
            corners = ((px, py) for px in (bounds[0], bounds[2])
                       for py in (bounds[1], bounds[3]))
            fits_circle = all((px - 240) ** 2 + (py - 240) ** 2 <= 224 ** 2
                              for px, py in corners)
            fits_width = max_width is None or bounds[2] - bounds[0] <= max_width
            if (fits_circle and fits_width) or size <= 10:
                break
            size -= 1
        draw.text((x, y), value, font=face, anchor=anchor,
                  fill=color or foreground,
                  stroke_width=stroke, stroke_fill=stroke_color or background)

    def metric(slot: str, x: int, y: int, value_size: int, color: str,
               label_size: int = 19, max_width: int | None = None, compact: bool = False):
        key = settings[slot]
        if key == "none":
            return
        label = METRICS[key].upper().replace(" TEMPERATURE", " TEMP").replace(" USAGE", " USE")
        if compact:
            label = {"cpu_temp": "CPU TEMP", "gpu_temp": "GPU TEMP", "cpu_load": "CPU %",
                     "gpu_load": "GPU %", "ram": "RAM %", "gpu_vram": "VRAM %",
                     "fan": "RPM"}[key]
        text(x, y, label, label_size, color, stroke=2 if layout == "gif_stat" else 0,
             max_width=max_width)
        text(x, y + label_size + 7, values[key], value_size,
             stroke=0 if layout in ("quad", "clock") else 2, max_width=max_width)

    def circle_art(side: int, border: bool = True):
        nonlocal draw
        if frame is None:
            draw.ellipse((240-side//2, 240-side//2, 240+side//2, 240+side//2),
                         outline=accent, width=5)
            text(240, 216, "CHOOSE A GIF", 22, accent)
            return
        art = ImageOps.fit(frame.convert("RGB"), (side, side), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (side, side), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, side - 1, side - 1), fill=255)
        image.paste(art, (240 - side // 2, 240 - side // 2), mask)
        draw = ImageDraw.Draw(image)
        if border:
            draw.ellipse((240-side//2-2, 240-side//2-2, 240+side//2+1, 240+side//2+1),
                         outline=accent, width=3)

    if layout == "event_horizon":
        stars = random.Random(19)
        for _ in range(56):
            angle = stars.random() * math.tau
            radius = stars.uniform(177, 224)
            x = 240 + radius * math.cos(angle)
            y = 240 + radius * math.sin(angle)
            size = stars.choice((1, 1, 2))
            draw.ellipse((x-size, y-size, x+size, y+size), fill="#74739a")
        draw.ellipse((56, 56, 423, 423), outline="#6d3976", width=7)
        draw.arc((35, 35, 444, 444), -67, 165, fill=accent, width=17)
        draw.arc((49, 49, 430, 430), 132, 288, fill=accent2, width=7)
        draw.ellipse((91, 91, 389, 389), fill="#080a17", outline="#b65c94", width=2)
        text(240, 128, "CORE TELEMETRY", 17, accent)
        metric("top", 240, 168, 106, accent, 23, 278)
        metric("bottom", 240, 315, 37, accent2, 16)
    elif layout == "aurora":
        for y in range(SIZE):
            blend = y / SIZE
            draw.line((0, y, SIZE, y), fill=(int(15 + 20 * blend), int(12 + 8 * blend),
                                            int(38 + 34 * blend)))
        for layer, base, color in ((0, 361, "#502e75"), (1, 391, "#2c7691"),
                                   (2, 419, "#4db5a6")):
            points = [(x, base + int(13 * math.sin(x / 36 + now / 3 + layer)))
                      for x in range(0, 481, 8)]
            draw.polygon(points + [(480, 480), (0, 480)], fill=color)
        draw.arc((12, 12, 467, 467), 200, 340, fill=accent2, width=5)
        text(240, 72, "AURORA / LIVE", 21, accent)
        metric("top", 240, 116, 108, accent, 23)
        draw.line((143, 271, 337, 271), fill="#7595ac", width=2)
        metric("bottom", 240, 287, 46, accent2, 18)
    elif layout == "arcade":
        for index in range(48):
            angle = index * math.tau / 48
            x = 240 + 220 * math.cos(angle)
            y = 240 + 220 * math.sin(angle)
            draw.rectangle((x-3, y-3, x+3, y+3), fill=accent if index % 3 else accent2)
        draw.rounded_rectangle((146, 70, 334, 252), radius=18, fill="#2b2048",
                               outline=accent2, width=3)
        frames = arcade_frames()
        if frames:
            sprite = ImageOps.fit(frames[int(now * 7) % len(frames)], (166, 166))
            image.paste(sprite, (157, 79))
            draw = ImageDraw.Draw(image)
        text(240, 31, "PIXEL / MODE", 20, accent)
        metric("top", 240, 267, 68, accent, 20)
        metric("bottom", 240, 379, 34, accent2, 16)
    elif layout == "hero":
        # Concentric temperature preset: one reading dominates, two rings carry context.
        draw.ellipse((18, 18, 461, 461), outline="#20252d", width=20)
        draw.arc((18, 18, 461, 461), -90, 134, fill=accent, width=20)
        draw.ellipse((48, 48, 431, 431), outline="#222b36", width=8)
        draw.arc((48, 48, 431, 431), 95, 236, fill=accent2, width=8)
        metric("top", 240, 159, 110, accent, 24, 340)
        draw.line((132, 319, 348, 319), fill="#596676", width=2)
        metric("bottom", 240, 335, 50, accent2, 18)
        metric("left", 180, 93, 28, accent, 15, 104, compact=True)
        metric("right", 300, 93, 28, accent2, 15, 104, compact=True)
    elif layout == "dual":
        # Clean dual infographic: no decorative cards, just two oversized values.
        draw.ellipse((7, 7, 472, 472), outline="#d7dce1", width=4)
        text(240, 63, "SYSTEM MONITOR", 22, "#d7dce1")
        draw.line((240, 128, 240, 339), fill="#65707c", width=3)
        metric("top", 133, 151, 79, accent, 22, 182)
        metric("bottom", 347, 151, 79, accent2, 22, 182)
        draw.line((96, 350, 384, 350), fill="#65707c", width=2)
        metric("left", 149, 362, 38, accent, 16, 150)
        metric("right", 331, 362, 38, accent2, 16, 150)
    elif layout == "quad":
        # A bright monitor face, intentionally unlike the dark GIF and gauge screens.
        draw.ellipse((7, 7, 472, 472), outline="#cdd9df", width=3)
        for box in ((75, 83, 229, 225), (251, 83, 405, 225),
                    (75, 255, 229, 397), (251, 255, 405, 397)):
            draw.rounded_rectangle(box, radius=27, fill="#ffffff", outline="#d5e0e6", width=2)
        for slot, x, y, color in (("top", 152, 107, accent), ("left", 328, 107, accent2),
                                   ("right", 152, 279, accent2), ("bottom", 328, 279, accent)):
            metric(slot, x, y, 50, color, 17, 142)
    elif layout == "rings":
        # Single-bar screen type, with a large numeric readout above the fill.
        draw.ellipse((8, 8, 471, 471), outline="#32324b", width=4)
        text(240, 67, "LIVE READING", 22, accent)
        metric("top", 240, 112, 106, accent, 22)
        draw.rounded_rectangle((70, 278, 410, 320), radius=20, fill="#26263e")
        key = settings["top"]
        raw = values.get(key, "0").replace("°", "").replace("%", "")
        try:
            proportion = min(1.0, max(0.0, float(raw) / (3000 if key == "fan" else 100)))
        except ValueError:
            proportion = 0.5
        draw.rounded_rectangle((70, 278, 70 + int(340 * proportion), 320), radius=20, fill=accent)
        metric("bottom", 240, 352, 45, accent2, 18)
    elif layout == "fade_fill":
        # Color rises like a liquid fill behind a single bold temperature.
        fill = Image.new("RGB", (SIZE, SIZE), background)
        liquid = ImageDraw.Draw(fill)
        level = 300 + int(12 * math.sin(now / 3))
        liquid.polygon([(x, level + int(8 * math.sin(x / 27 + now))) for x in range(0, 481, 8)]
                       + [(480, 480), (0, 480)], fill=accent)
        mask = Image.new("L", (SIZE, SIZE), 0)
        ImageDraw.Draw(mask).ellipse((9, 9, 471, 471), fill=255)
        image.paste(fill, (0, 0), mask)
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 471, 471), outline=accent2, width=5)
        text(240, 92, "LIQUID / LIVE", 21, accent2)
        metric("top", 240, 131, 112, accent2, 23)
        metric("bottom", 240, 339, 39, "#ffffff", 17)
    elif layout == "fan_sensor":
        # Minimal full-circle sensor tile, like small LCD fan readouts.
        draw.ellipse((10, 10, 469, 469), outline="#f1f3f5", width=7)
        draw.arc((28, 28, 451, 451), -90, 75, fill=accent, width=9)
        text(240, 87, "SENSOR", 22, "#aeb6c2")
        metric("top", 240, 154, 126, accent, 25)
        draw.line((132, 346, 348, 346), fill="#6c7680", width=2)
        metric("bottom", 240, 365, 40, accent2, 17)
    elif layout == "cyberpunk":
        # Angular high-contrast heads-up display, without any brand artwork.
        draw.polygon(((120, 35), (360, 35), (445, 120), (445, 360),
                      (360, 445), (120, 445), (35, 360), (35, 120)),
                     outline=accent, width=5)
        draw.line((72, 112, 408, 112), fill=accent2, width=4)
        draw.line((72, 338, 408, 338), fill=accent2, width=4)
        for x in range(83, 399, 20):
            draw.line((x, 44, x + 8, 44), fill=accent2, width=2)
        text(240, 63, "SYSTEM / LIVE", 20, accent)
        metric("top", 240, 145, 95, accent, 22)
        metric("left", 142, 355, 37, accent2, 17, 160)
        metric("right", 338, 355, 37, accent2, 17, 160)
    elif layout == "gif_stat":
        # The GIF owns the center; all readings stay in the clear outer lanes.
        draw.ellipse((9, 9, 470, 470), outline="#354556", width=3)
        side = int(settings["gif_size"] * 0.6)
        circle_art(side)
        metric("top", 240, 41, 49, accent, 18, 225)
        metric("left", 64, 210, 28, accent, 15, 86, compact=True)
        metric("right", 416, 210, 28, accent2, 15, 86, compact=True)
        metric("bottom", 240, 382, 42, accent2, 17, 230)
    elif layout == "gif_only":
        side = min(460, settings["gif_size"] + 60) if frame is not None else 430
        circle_art(side)
        draw.ellipse((6, 6, 473, 473), outline=accent, width=5)
    elif layout == "gif_overlay":
        # A single reading floats over the animation. The soft local vignette
        # preserves contrast without hiding the GIF under a full-width bar.
        side = min(460, settings["gif_size"] + 60) if frame is not None else 430
        circle_art(side, border=False)
        draw.ellipse((6, 6, 473, 473), outline="#bdedfa", width=3)
        slot = settings["top"]
        if slot != "none":
            x, y = {"top": (240, 112), "center": (240, 240),
                    "bottom": (240, 365), "left": (140, 240),
                    "right": (340, 240)}[settings["gif_position"]]
            style = settings["gif_style"]
            label = METRICS[slot].upper().replace(" TEMPERATURE", " TEMP").replace(" USAGE", " USE")
            value = values[slot]

            def fitted(value: str, size: int, max_width: int, mono: bool = False):
                while True:
                    face = font(size, True, mono)
                    bounds = draw.textbbox((0, 0), value, font=face, stroke_width=2)
                    if bounds[2] - bounds[0] <= max_width or size <= 12:
                        return face, bounds
                    size -= 1

            def exact(anchor_x: float, top: float, value: str, face, bounds,
                      color: str = "#ffffff", alignment: str = "center"):
                # Position by visible glyph bounds, not the font's baseline.
                if alignment == "left":
                    px = round(anchor_x - bounds[0])
                elif alignment == "right":
                    px = round(anchor_x - bounds[2])
                else:
                    px = round(anchor_x - (bounds[0] + bounds[2]) / 2)
                py = round(top - bounds[1])
                draw.text((px, py), value, font=face, fill=color,
                          stroke_width=2, stroke_fill="#061018")

            if style == "disc":
                draw.ellipse((x-84, y-84, x+84, y+84), fill="#071621",
                             outline="#d7edf1", width=2)
                max_width = 145
            else:
                # A small, blurred shadow only behind this readout keeps bright
                # GIF frames legible without introducing a rectangular bar.
                shade = Image.new("L", (SIZE, SIZE), 0)
                half_height = 52 if style == "quiet" else 69
                ImageDraw.Draw(shade).ellipse((x-116, y-half_height,
                                               x+116, y+half_height), fill=225)
                image.paste("#02070d", (0, 0, SIZE, SIZE),
                            shade.filter(ImageFilter.GaussianBlur(20)))
                draw = ImageDraw.Draw(image)
                max_width = 210

            if style == "number_only":
                value_face, value_box = fitted(value, 104, max_width)
                value_h = value_box[3] - value_box[1]
                exact(x, y-value_h/2, value, value_face, value_box)
            else:
                label_size = {"big": 16, "balanced": 18, "left": 17,
                              "right": 17, "quiet": 15, "mono": 16,
                              "disc": 16}[style]
                value_size = {"big": 94, "balanced": 75, "left": 88,
                              "right": 88, "quiet": 51, "mono": 73,
                              "disc": 63}[style]
                label_face, label_box = fitted(label, label_size, max_width,
                                               style == "mono")
                value_face, value_box = fitted(value, value_size, max_width,
                                               style == "mono")
                label_h = label_box[3] - label_box[1]
                value_h = value_box[3] - value_box[1]
                gap = 7 if style != "disc" else 5
                total_h = label_h + gap + value_h
                top = y - total_h / 2
                block_width = max(label_box[2]-label_box[0],
                                  value_box[2]-value_box[0])
                alignment = ("left" if style in ("left", "mono") else
                             "right" if style == "right" else "center")
                anchor_x = (x-block_width/2 if alignment == "left" else
                            x+block_width/2 if alignment == "right" else x)
                if style == "big":
                    exact(anchor_x, top, value, value_face, value_box)
                    exact(anchor_x, top+value_h+gap, label, label_face,
                          label_box, "#d0e6ea")
                else:
                    exact(anchor_x, top, label, label_face, label_box,
                          "#d0e6ea", alignment)
                    exact(anchor_x, top+label_h+gap, value, value_face,
                          value_box, alignment=alignment)
    elif layout == "clock":
        draw.ellipse((13, 13, 466, 466), outline=accent, width=5)
        clock_y = 240
        draw.ellipse((116, 116, 364, 364), outline="#345366", width=3)
        for index in range(12):
            angle = index * math.tau / 12 - math.pi / 2
            x1, y1 = 240 + 108 * math.cos(angle), clock_y + 108 * math.sin(angle)
            x2, y2 = 240 + 121 * math.cos(angle), clock_y + 121 * math.sin(angle)
            draw.line((x1, y1, x2, y2), fill=accent, width=4)
        wall = time.localtime()
        minute_angle = (wall.tm_min + wall.tm_sec / 60) * math.tau / 60 - math.pi / 2
        hour_angle = ((wall.tm_hour % 12) + wall.tm_min / 60) * math.tau / 12 - math.pi / 2
        second_angle = wall.tm_sec * math.tau / 60 - math.pi / 2
        for angle, length, color, width in ((hour_angle, 68, "#20334b", 9),
                                             (minute_angle, 99, accent, 6),
                                             (second_angle, 107, accent2, 2)):
            draw.line((240, clock_y, 240 + length * math.cos(angle),
                       clock_y + length * math.sin(angle)), fill=color, width=width)
        draw.ellipse((230, clock_y-10, 250, clock_y+10), fill=accent2)
        metric("left", 163, 66, 29, accent, 15, 126)
        metric("right", 317, 66, 29, accent2, 15, 126)
        metric("bottom", 240, 382, 31, accent2, 16, 230)
    if settings["rotation"]:
        image = image.rotate(settings["rotation"])
    image = ImageEnhance.Brightness(image).enhance(settings["brightness"] / 100)
    circle = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(circle).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    preview = Image.new("RGB", (SIZE, SIZE), "#000000")
    preview.paste(image, (0, 0), circle)
    return preview


def pixbuf(image: Image.Image, side: int = 450):
    image = image.resize((side, side), Image.Resampling.LANCZOS).convert("RGB")
    data = GLib.Bytes.new(image.tobytes())
    return GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB, False, 8,
                                           side, side, side * 3)


class PumpDesigner(Gtk.Box):
    def __init__(self, live: bool = False):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        ensure_presets()
        self.live = live
        self.live_values = format_values({}) if live else None
        self.next_stats = 0.0
        self.settings = load(CONFIG_PATH if live else DRAFT_PATH)
        self.frames: list[Image.Image] = []
        self.frame_index = 0
        self.layout_buttons = {}
        self.layout_thumbnails = {}
        self.gif_buttons = {}
        self.load_animation()
        self.set_border_width(18)
        root = self

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.pack_start(left, False, False, 0)
        title = Gtk.Label()
        title.set_markup("<span size='x-large' weight='bold'>ID-COOLING pump LCD</span>")
        title.set_xalign(0)
        left.pack_start(title, False, False, 0)
        self.preview = Gtk.Image()
        left.pack_start(self.preview, False, False, 0)
        mock_note = Gtk.Label(label=("LIVE SENSORS  •  save to apply to the pump" if live else
                                     "MOCK PREVIEW  •  sample readings  •  no USB writes"), xalign=0)
        mock_note.get_style_context().add_class("dim-label")
        left.pack_start(mock_note, False, False, 0)
        self.device_status = Gtk.Label(xalign=0, wrap=True)
        if live:
            left.pack_start(self.device_status, False, False, 0)
        self.message = Gtk.Label(xalign=0, wrap=True)
        left.pack_start(self.message, False, False, 0)
        buttons = Gtk.Box(spacing=8)
        left.pack_start(buttons, False, False, 0)
        for label, action in ((("Save and apply" if live else "Save draft"), self.save_draft),
                              ("Export PNG", self.export)):
            button = Gtk.Button(label=label)
            button.connect("clicked", action)
            buttons.pack_start(button, True, True, 0)

        notebook = Gtk.Notebook()
        root.pack_start(notebook, True, True, 0)
        notebook.append_page(self.design_tab(), Gtk.Label(label="Design"))
        notebook.append_page(self.stats_tab(), Gtk.Label(label="Stats"))
        notebook.append_page(self.animation_tab(), Gtk.Label(label="GIFs"))
        self.refresh()
        self.tick_id = GLib.timeout_add(100, self.tick)
        self.connect("destroy", self.stop_ticker)
        self.show_all()

    def row(self, parent: Gtk.Box, label: str, widget):
        row = Gtk.Box(spacing=10)
        title = Gtk.Label(label=label, xalign=0)
        title.set_size_request(140, -1)
        row.pack_start(title, False, False, 0)
        row.pack_start(widget, True, True, 0)
        parent.pack_start(row, False, False, 0)

    def combo(self, options: list[tuple[str, str]], active, on_change):
        box = Gtk.ComboBoxText()
        for key, label in options:
            box.append(str(key), label)
        if active is not None:
            box.set_active_id(str(active))
        box.connect("changed", lambda item: on_change(item.get_active_id()) if item.get_active_id() else None)
        return box

    def tab_box(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15, margin=18)
        return box

    def design_tab(self):
        box = self.tab_box()
        note = Gtk.Label(label="Choose a screen design", xalign=0)
        note.get_style_context().add_class("heading")
        box.pack_start(note, False, False, 0)
        gallery = Gtk.Grid(column_spacing=7, row_spacing=7)
        for index, (key, label) in enumerate(LAYOUTS.items()):
            button = Gtk.Button()
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            thumb = Gtk.Image()
            content.pack_start(thumb, False, False, 0)
            caption = Gtk.Label(label=label)
            content.pack_start(caption, False, False, 0)
            button.add(content)
            button.connect("clicked", lambda _button, key=key: self.change(layout=key))
            gallery.attach(button, index % 3, index // 3, 1, 1)
            self.layout_buttons[key] = button
            self.layout_thumbnails[key] = thumb
        box.pack_start(gallery, False, False, 0)
        self.row(box, "Rotation", self.combo([(str(k), f"{k}°") for k in (0, 90, 180, 270)],
                                              self.settings["rotation"], lambda v: self.change(rotation=int(v))))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 20, 100, 5)
        scale.set_value(self.settings["brightness"])
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.connect("value-changed", lambda s: self.change(brightness=int(s.get_value())))
        self.row(box, "Brightness", scale)
        note = Gtk.Label(label=("Edits update the preview. Save and apply to update the pump." if self.live else
                                "These controls change this preview only."),
                         xalign=0, wrap=True, max_width_chars=45)
        note.get_style_context().add_class("dim-label")
        box.pack_start(note, False, False, 10)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(box)
        self.refresh_galleries()
        return scroller

    def stats_tab(self):
        box = self.tab_box()
        note = Gtk.Label(label="Choose readings for the design's primary, secondary, and detail positions. GIF + one stat uses Primary; GIF only hides all readings.",
                         xalign=0, wrap=True)
        box.pack_start(note, False, False, 0)
        options = [("none", "Hidden")] + list(METRICS.items())
        self.stat_combos = {}
        for slot, label in (("top", "Primary"), ("bottom", "Secondary"),
                            ("left", "Detail A"), ("right", "Detail B")):
            combo = self.combo(options, self.settings[slot],
                               lambda value, slot=slot: self.change(**{slot: value}))
            self.stat_combos[slot] = combo
            self.row(box, label, combo)
        note = Gtk.Label(label=("Values come from the same sensors as the Thermaltake panel." if self.live else
                                "Values are animated examples in this standalone preview."),
                         xalign=0, wrap=True, max_width_chars=45)
        note.get_style_context().add_class("dim-label")
        box.pack_start(note, False, False, 10)
        return box

    def animation_tab(self):
        box = self.tab_box()
        intro = Gtk.Label(label="Choose an animation, then decide whether to show it alone or with readings.",
                          xalign=0, wrap=True, max_width_chars=46)
        box.pack_start(intro, False, False, 0)
        gif_modes = [("gif_only", "GIF only — no stats"),
                     ("gif_overlay", "GIF + one stat"),
                     ("gif_stat", "GIF + four stats")]
        active_mode = self.settings["layout"] if self.settings["layout"] in dict(gif_modes) else None
        self.gif_mode_combo = self.combo(gif_modes, active_mode, self.on_gif_mode)
        self.row(box, "Display", self.gif_mode_combo)
        self.gif_style_combo = self.combo(list(GIF_STYLES.items()), self.settings["gif_style"],
                                         lambda value: self.change(gif_style=value))
        self.row(box, "Stat style", self.gif_style_combo)
        self.gif_position_combo = self.combo(list(GIF_POSITIONS.items()), self.settings["gif_position"],
                                            lambda value: self.change(gif_position=value))
        self.row(box, "Stat position", self.gif_position_combo)
        gallery = Gtk.Grid(column_spacing=8, row_spacing=8)
        all_gifs = [("none", "No GIF", None)] + [
            (key, label, PRESET_DIR / filename) for key, (label, filename) in PRESETS.items()
        ]
        for index, (key, label, path) in enumerate(all_gifs):
            button = Gtk.Button()
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            if path is None:
                thumbnail = Image.new("RGB", (100, 100), "#142534")
                ImageDraw.Draw(thumbnail).text((50, 50), "OFF", anchor="mm", font=font(22, True),
                                               fill="#d0e2e9")
            else:
                with Image.open(path) as gif:
                    thumbnail = ImageOps.fit(gif.convert("RGB"), (100, 100))
            content.pack_start(Gtk.Image.new_from_pixbuf(pixbuf(thumbnail, 96)), False, False, 0)
            caption = Gtk.Label(label=label, wrap=True, max_width_chars=14, lines=2)
            content.pack_start(caption, False, False, 0)
            button.add(content)
            button.connect("clicked", lambda _button, key=key: self.select_animation(key))
            gallery.attach(button, index % 3, index // 3, 1, 1)
            self.gif_buttons[key] = button
        box.pack_start(gallery, False, False, 0)
        options = [("none", "No GIF")] + [(k, v[0]) for k, v in PRESETS.items()] + [("custom", "My GIF")]
        self.animation_combo = self.combo(options, self.settings["animation"], self.on_animation_combo)
        self.row(box, "Selected GIF", self.animation_combo)
        chooser = Gtk.FileChooserButton(title="Choose your own GIF", action=Gtk.FileChooserAction.OPEN)
        filter_ = Gtk.FileFilter()
        filter_.set_name("GIF animation")
        filter_.add_pattern("*.gif")
        filter_.add_pattern("*.GIF")
        chooser.add_filter(filter_)
        if self.settings["custom_gif"] and Path(self.settings["custom_gif"]).is_file():
            chooser.set_filename(self.settings["custom_gif"])
        chooser.connect("file-set", self.choose_gif)
        self.row(box, "Your GIF", chooser)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 280, 440, 20)
        scale.set_value(self.settings["gif_size"])
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.connect("value-changed", lambda s: self.change(gif_size=int(s.get_value())))
        self.row(box, "GIF size", scale)
        note = Gtk.Label(label="The one-stat style uses the Primary reading from the Stats tab. GIF only fills the circle. Full-screen GIFs may update slowly over the pump's USB connection.",
                         xalign=0, wrap=True, max_width_chars=45)
        note.get_style_context().add_class("dim-label")
        box.pack_start(note, False, False, 10)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(box)
        self.refresh_galleries()
        return scroller

    def change(self, **changes):
        self.settings = clean({**self.settings, **changes})
        self.refresh_galleries()
        self.refresh()

    def select_animation(self, key: str):
        if key != "none" and self.settings["layout"] not in ("gif_stat", "gif_only", "gif_overlay"):
            self.settings["layout"] = "gif_only"
        elif key == "none" and self.settings["layout"] in ("gif_stat", "gif_only", "gif_overlay"):
            self.settings["layout"] = "hero"
        self.settings["animation"] = key
        if hasattr(self, "animation_combo") and self.animation_combo.get_active_id() != key:
            self.animation_combo.set_active_id(key)
        self.load_animation()
        self.refresh_galleries()
        self.refresh()

    def on_animation_combo(self, key: str):
        if self.settings["animation"] != key:
            self.select_animation(key)

    def on_gif_mode(self, key: str):
        if self.settings["layout"] != key:
            self.change(layout=key)

    def choose_gif(self, chooser):
        path = chooser.get_filename()
        if not path:
            return
        self.settings["custom_gif"] = path
        self.select_animation("custom")

    def load_animation(self):
        key = self.settings["animation"]
        path = PRESET_DIR / PRESETS[key][1] if key in PRESETS else Path(self.settings["custom_gif"] or "")
        try:
            self.frames = load_gif(path) if key != "none" else []
            self.frame_index = 0
            if hasattr(self, "message"):
                self.message.set_text("")
        except (OSError, ValueError) as exc:
            self.frames = []
            if hasattr(self, "message"):
                self.message.set_text(str(exc))

    def current_frame(self):
        return self.frames[self.frame_index % len(self.frames)] if self.frames else None

    def refresh(self):
        self.preview.set_from_pixbuf(pixbuf(render(self.settings, self.current_frame(),
                                                readings=self.live_values)))

    def refresh_galleries(self):
        frame = self.current_frame()
        if hasattr(self, "stat_combos"):
            active_slots = LAYOUT_SLOTS[self.settings["layout"]]
            for slot, combo in self.stat_combos.items():
                combo.set_sensitive(slot in active_slots)
        if hasattr(self, "gif_mode_combo"):
            layout = self.settings["layout"]
            if layout in ("gif_only", "gif_overlay", "gif_stat"):
                if self.gif_mode_combo.get_active_id() != layout:
                    self.gif_mode_combo.set_active_id(layout)
            else:
                self.gif_mode_combo.set_active(-1)
            one_stat = layout == "gif_overlay"
            self.gif_style_combo.set_sensitive(one_stat)
            self.gif_position_combo.set_sensitive(one_stat)
        for key, button in self.layout_buttons.items():
            style = button.get_style_context()
            (style.add_class if key == self.settings["layout"] else style.remove_class)("suggested-action")
            self.layout_thumbnails[key].set_from_pixbuf(
                pixbuf(render({**self.settings, "layout": key}, frame, now=12), 116))
        for key, button in self.gif_buttons.items():
            style = button.get_style_context()
            (style.add_class if key == self.settings["animation"] else style.remove_class)("suggested-action")

    def tick(self):
        if not self.get_mapped():
            return True
        if self.live and time.monotonic() >= self.next_stats:
            keys = {self.settings[slot] for slot in SLOTS if self.settings[slot] != "none"}
            self.live_values = format_values(sensors.read(keys=keys))
            status = read_status()
            self.device_status.set_text(
                "Pump LCD connected" if status.get("connected") else
                status.get("error", "Pump detected; service is waiting for the display"))
            self.next_stats = time.monotonic() + 1
        if self.frames:
            self.frame_index = (self.frame_index + 1) % len(self.frames)
        self.refresh()
        return True

    def stop_ticker(self, *_):
        if self.tick_id:
            GLib.source_remove(self.tick_id)
            self.tick_id = None

    def save_draft(self, *_):
        path = CONFIG_PATH if self.live else DRAFT_PATH
        save(self.settings, path)
        self.message.set_text(("Saved. The pump service will apply this design when connected." if self.live else
                               f"Mock draft saved to {DRAFT_PATH}. No display settings changed."))

    def export(self, *_):
        chooser = Gtk.FileChooserDialog(title="Export pump preview", parent=self.get_toplevel(),
                                        action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                            Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        chooser.set_current_name("pump-lcd-preview.png")
        chooser.set_do_overwrite_confirmation(True)
        if chooser.run() == Gtk.ResponseType.OK:
            path = Path(chooser.get_filename())
            render(self.settings, self.current_frame(), readings=self.live_values).save(path)
            self.message.set_text(f"Saved preview to {path}")
        chooser.destroy()


class PumpMock(Gtk.Window):
    """Standalone designer for previewing without the Thermaltake tray app."""

    def __init__(self):
        super().__init__(title="Pump LCD Designer — Mock Preview")
        self.set_default_size(1070, 750)
        self.designer = PumpDesigner()
        self.add(self.designer)
        self.show_all()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, help="save one mock PNG without opening GTK")
    args = parser.parse_args()
    ensure_presets()
    if args.preview:
        settings = load(DRAFT_PATH)
        key = settings["animation"]
        path = PRESET_DIR / PRESETS[key][1] if key in PRESETS else Path(settings["custom_gif"] or "")
        try:
            frames = load_gif(path) if key != "none" else []
        except (OSError, ValueError):
            frames = []
        render(settings, frames[0] if frames else None).save(args.preview)
        return
    window = PumpMock()
    window.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
