"""Generate original, freely reusable GIF loops for the pump LCD designer."""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PRESET_DIR = Path(__file__).resolve().parent / "assets" / "pump-gifs"
PRESETS = {
    "orbit": ("Neon orbit", "orbit.gif"),
    "radar": ("Radar sweep", "radar.gif"),
    "rain": ("Pixel rain", "pixel-rain.gif"),
    "sunset": ("Synthwave sunset", "synthwave-sunset.gif"),
    "matrix": ("Matrix-style code rain", "code-rain.gif"),
    "stars": ("Warp starfield", "starfield.gif"),
    "cat": ("Pixel cat", "pixel-cat.gif"),
    "equalizer": ("Neon equalizer", "equalizer.gif"),
}


def _orbit(i: int) -> Image.Image:
    image = Image.new("RGB", (240, 240), "#070f23")
    d = ImageDraw.Draw(image)
    for radius, color in ((94, "#133d66"), (67, "#19447a"), (37, "#294c75")):
        d.ellipse((120-radius, 120-radius, 120+radius, 120+radius), outline=color, width=3)
    for offset, radius, color in ((0, 94, "#5fe5ff"), (8, 67, "#ff86b7"), (16, 37, "#ffe782")):
        angle = (i + offset) * math.tau / 24
        x, y = 120 + radius * math.cos(angle), 120 + radius * math.sin(angle)
        d.ellipse((x-11, y-11, x+11, y+11), fill=color)
    d.ellipse((105, 105, 135, 135), fill="#ecfaff")
    return image


def _radar(i: int) -> Image.Image:
    image = Image.new("RGB", (240, 240), "#041b1a")
    d = ImageDraw.Draw(image)
    for radius in (36, 66, 96):
        d.ellipse((120-radius, 120-radius, 120+radius, 120+radius), outline="#17665a", width=2)
    d.line((24, 120, 216, 120), fill="#145548", width=2)
    d.line((120, 24, 120, 216), fill="#145548", width=2)
    angle = i * math.tau / 24
    for trail in range(7, -1, -1):
        a = angle - trail * .095
        x, y = 120 + 96 * math.sin(a), 120 - 96 * math.cos(a)
        shade = int(68 + 20 * (7 - trail))
        d.line((120, 120, x, y), fill=(15, shade, 85), width=3)
    for x, y in ((74, 98), (174, 151), (112, 185)):
        d.ellipse((x-4, y-4, x+4, y+4), fill="#91ffd9")
    return image


def _rain(i: int) -> Image.Image:
    image = Image.new("RGB", (240, 240), "#071422")
    d = ImageDraw.Draw(image)
    rng = random.Random(42)
    for col in range(18):
        x = 13 + col * 13
        offset = rng.randrange(240)
        speed = 3 + col % 4
        for tail in range(6):
            y = (offset + i * speed * 3 - tail * 16) % 256 - 8
            green = max(40, 220 - tail * 28)
            d.rounded_rectangle((x, y, x+7, y+11), radius=2, fill=(14, green, 185-tail*20))
    return image


def _sunset(i: int) -> Image.Image:
    image = Image.new("RGB", (240, 240), "#130e2c")
    d = ImageDraw.Draw(image)
    for y in range(240):
        if y < 120:
            d.line((0, y, 239, y), fill=(18 + y // 5, 13 + y // 8, 50 + y // 3))
    d.ellipse((62, 35, 178, 151), fill="#ff9a73")
    for j in range(6):
        y = 99 + j * 10
        d.rectangle((57, y, 183, y+3+j), fill="#362044")
    d.polygon(((0, 161), (42, 108), (74, 163)), fill="#1a1433")
    d.polygon(((126, 162), (191, 96), (240, 160)), fill="#221541")
    d.rectangle((0, 160, 240, 240), fill="#100f2e")
    horizon = 171
    for j in range(1, 8):
        y = horizon + int((j + i / 24) ** 1.65 * 4)
        if y < 240:
            d.line((0, y, 240, y), fill="#de4aa8", width=2)
    for x in range(-180, 430, 37):
        d.line((120, horizon, x, 240), fill="#7e3f9f", width=2)
    return image


def _matrix(i: int) -> Image.Image:
    image = Image.new("RGB", (240, 240), "#020904")
    draw = ImageDraw.Draw(image)
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
    face = ImageFont.truetype(font_path, 17) if font_path.exists() else ImageFont.load_default()
    glyphs = "01ZXCV<>/+=*"
    for col in range(14):
        rng = random.Random(400 + col)
        x = 3 + col * 17
        head = (rng.randrange(15) + i * (1 + col % 3)) % 19
        for tail in range(10):
            row = (head - tail) % 19
            y = row * 14 - 12
            if y < 0 or y > 236:
                continue
            char = glyphs[(col * 7 + row * 5 + i // 3) % len(glyphs)]
            color = "#d9ffdb" if tail == 0 else (15, max(25, 210 - tail * 21), 50)
            draw.text((x, y), char, font=face, fill=color)
    return image


def _stars(i: int) -> Image.Image:
    image = Image.new("RGB", (240, 240), "#050b20")
    draw = ImageDraw.Draw(image)
    rng = random.Random(89)
    for _ in range(95):
        angle = rng.random() * math.tau
        depth = rng.random()
        radius = 6 + ((depth + i / 24) % 1) ** 2 * 170
        x, y = 120 + radius * math.cos(angle), 120 + radius * math.sin(angle)
        if 0 <= x < 240 and 0 <= y < 240:
            length = 2 + int(radius / 18)
            before = radius - length
            color = (125 + int(radius / 3), 170 + int(radius / 5), 255)
            draw.line((120 + before * math.cos(angle), 120 + before * math.sin(angle), x, y),
                      fill=color, width=max(1, int(radius / 55)))
    draw.ellipse((116, 116, 124, 124), fill="#d4f5ff")
    return image


def _cat(i: int) -> Image.Image:
    image = Image.new("RGB", (240, 240), "#201637")
    d = ImageDraw.Draw(image)
    # Deliberately simple original pixel character, sized for a small LCD.
    d.rectangle((43, 62, 197, 180), fill="#efa9c2")
    d.polygon(((43, 89), (43, 35), (89, 67)), fill="#efa9c2")
    d.polygon(((197, 89), (197, 35), (151, 67)), fill="#efa9c2")
    d.polygon(((53, 67), (54, 48), (77, 69)), fill="#a94f80")
    d.polygon(((187, 67), (186, 48), (163, 69)), fill="#a94f80")
    blink = i in (6, 7, 8, 20)
    if blink:
        d.line((76, 119, 100, 119), fill="#302141", width=5)
        d.line((140, 119, 164, 119), fill="#302141", width=5)
    else:
        d.rectangle((80, 103, 96, 129), fill="#302141")
        d.rectangle((144, 103, 160, 129), fill="#302141")
    d.polygon(((112, 140), (128, 140), (120, 149)), fill="#7e3d69")
    d.line((120, 149, 120, 155), fill="#7e3d69", width=3)
    d.arc((106, 146, 122, 164), 0, 130, fill="#7e3d69", width=3)
    d.arc((118, 146, 134, 164), 50, 180, fill="#7e3d69", width=3)
    for y in (140, 150):
        d.line((56, y, 100, y + 3), fill="#fbe7ec", width=2)
        d.line((140, y + 3, 184, y), fill="#fbe7ec", width=2)
    d.rectangle((85, 181, 155, 202), fill="#efa9c2")
    tail_x = 178 + int(12 * math.sin(i * math.tau / 24))
    d.line((154, 187, tail_x, 196, tail_x + 8, 171), fill="#efa9c2", width=15)
    return image


def _equalizer(i: int) -> Image.Image:
    image = Image.new("RGB", (240, 240), "#100b24")
    d = ImageDraw.Draw(image)
    colors = ("#5be7ff", "#7ea9ff", "#bf83ff", "#ff7bc6")
    for bar in range(14):
        x = 14 + bar * 16
        height = 28 + int(125 * abs(math.sin(i * .27 + bar * .48)))
        for y in range(195, 195 - height, -13):
            d.rounded_rectangle((x, y - 8, x + 10, y), radius=2,
                                fill=colors[(bar // 4) % len(colors)])
    d.line((10, 207, 230, 207), fill="#725aaa", width=2)
    return image


DRAWERS = {"orbit": _orbit, "radar": _radar, "rain": _rain, "sunset": _sunset,
           "matrix": _matrix, "stars": _stars, "cat": _cat, "equalizer": _equalizer}


def ensure_presets() -> None:
    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    for key, (_, filename) in PRESETS.items():
        path = PRESET_DIR / filename
        if path.exists():
            continue
        frames = [DRAWERS[key](i) for i in range(24)]
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=100,
                       loop=0, optimize=False)


if __name__ == "__main__":
    ensure_presets()
