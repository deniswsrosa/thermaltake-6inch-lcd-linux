"""Example user template: one hero value on the left, a list on the right.

Copy this file to ~/.config/tt600/templates/ and pick "Split (example)" in the
tray. The file name (without .py) is the template's id.

A template module defines TEMPLATE and draw(). Coordinates are panel pixels
(1110x540). The helpers in templates.py (fmt, label, status_colour, bar,
fraction, mix, slot) keep the look consistent with the built-in templates.
"""

from templates import H, W, bar, fmt, fraction, label, mix, slot, status_colour

TEMPLATE = {
    "name": "Split (example)",
    "slots": ["Hero", "List 1", "List 2", "List 3"],
    "defaults": ["cpu_temp", "gpu0_temp", "gpu1_temp", "ram"],
    "accent": "#ffcc00",
    "accent2": "#e6e9ef",
    "background": "#101014",
}


def draw(c, values, cfg):
    hero = slot(cfg, 0)
    colour = status_colour(hero, values[hero], cfg["accent"])
    c.text((250, 70), label(hero, cfg), 48, mix(cfg["accent"], "#ffffff", 0.3), anchor="mt")
    c.text((250, 360), fmt(hero, values[hero], cfg), 200, colour, weight="cond", anchor="ms")
    bar(c, (60, 420, 440, 456), fraction(hero, values[hero]), colour,
        mix(cfg["background"], "#ffffff", 0.12))

    c.line((500, 60, 500, H - 60), mix(cfg["background"], "#ffffff", 0.15), 3)
    rows = [k for k in (slot(cfg, i) for i in range(1, 4)) if k != "none"]
    for i, key in enumerate(rows):
        y = 150 + i * 150
        c.text((550, y), label(key, cfg), 40, mix(cfg["accent2"], "#000000", 0.3), anchor="ls")
        c.text((W - 50, y), fmt(key, values[key], cfg), 96,
               status_colour(key, values[key], cfg["accent2"]), weight="cond", anchor="rs")
