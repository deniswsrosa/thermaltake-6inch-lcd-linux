#!/usr/bin/env python3
"""tt600-tray — tray icon to control the Thermaltake 6.0" LCD panel dashboard.

Quick switches for template, temperature unit and brightness in the tray
menu, plus a Customize window with a live preview. Changes are written to
~/.config/tt600/config.json, which the tt600d service picks up immediately.

Needs GTK 3 and Ayatana AppIndicator (python3-gi, gir1.2-ayatanaappindicator3-0.1).
On GNOME the AppIndicator extension must be enabled (Ubuntu enables it by default).
"""

import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

import psutil  # noqa: E402

import config  # noqa: E402
import sensors  # noqa: E402
import templates  # noqa: E402

APP_ID = "io.github.deniswsrosa.tt600"
ICON = "video-display-symbolic"
PREVIEW_W = 555
INTERVALS = (0.5, 1.0, 2.0, 4.0)
BRIGHTNESS_STEPS = (25, 50, 75, 100)


def pil_to_pixbuf(img, width):
    img = img.convert("RGB").resize((width, width * img.height // img.width))
    data = GLib.Bytes.new(img.tobytes())
    return GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB, False, 8,
                                           img.width, img.height, img.width * 3)


def hex_to_rgba(colour):
    rgba = Gdk.RGBA()
    rgba.parse(colour)
    return rgba


def rgba_to_hex(rgba):
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue)))


class Tray(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.cfg = config.load()
        self.cfg_mtime = config.mtime()
        self.window = None
        self.syncing = False
        self.values = {k: None for k in sensors.METRICS}
        self.save_timer = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # keep running with no window open
        psutil.cpu_percent()
        self.indicator = AppIndicator.Indicator.new(
            "tt600", ICON, AppIndicator.IndicatorCategory.HARDWARE)
        self.indicator.set_title("Thermaltake LCD")
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self.build_menu())
        GLib.timeout_add_seconds(2, self.poll)
        self.poll()

    def do_activate(self):
        # Runs on a second launch (e.g. from the app grid): open the window.
        if self.window is not None or self.get_is_remote():
            self.customize()

    # ── settings ─────────────────────────────────────────────────────────────
    def update(self, delay=0, **changes):
        """Change settings; saved right away, or after `delay` ms for sliders."""
        self.cfg = config.clean({**self.cfg, **changes})
        self.sync_menu()
        self.render_preview()
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = None
        if delay:
            self.save_timer = GLib.timeout_add(delay, self._save)
        else:
            self._save()

    def _save(self):
        self.save_timer = None
        self.cfg = config.save(self.cfg)
        self.cfg_mtime = config.mtime()
        return False

    def set_template(self, name):
        t = templates.TEMPLATES[name]
        self.update(template=name, slots=templates.defaults(name),
                    accent=None, accent2=None, background=None)
        if self.window:
            self.fill_window()

    def poll(self):
        """Pick up external config edits and refresh the panel status line."""
        if config.mtime() != self.cfg_mtime and not self.save_timer:
            self.cfg, self.cfg_mtime = config.load(), config.mtime()
            self.sync_menu()
            if self.window:
                self.fill_window()
        status = config.read_status() or {}
        if status.get("connected"):
            text = f"Panel connected (fw {status.get('firmware', '?')})"
        elif status:
            text = "Panel not found"
        else:
            text = "Service not running"
        self.status_item.set_label(text)
        return True

    # ── tray menu ────────────────────────────────────────────────────────────
    def build_menu(self):
        menu = Gtk.Menu()
        self.status_item = Gtk.MenuItem(label="…", sensitive=False)
        menu.append(self.status_item)
        menu.append(Gtk.SeparatorMenuItem())

        self.radios = {}
        for title, key, options in (
            ("Template", "template", [(k, t["name"]) for k, t in templates.TEMPLATES.items()]),
            ("Temperature", "unit", [("C", "°C"), ("F", "°F")]),
            ("Brightness", "brightness", [(b, f"{b}%") for b in BRIGHTNESS_STEPS]),
        ):
            sub, group = Gtk.Menu(), None
            for value, label in options:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
                group = item
                item.connect("toggled", self.on_radio, key, value)
                self.radios[(key, value)] = item
                sub.append(item)
            top = Gtk.MenuItem(label=title)
            top.set_submenu(sub)
            menu.append(top)

        menu.append(Gtk.SeparatorMenuItem())
        item = Gtk.MenuItem(label="Customize…")
        item.connect("activate", lambda *_: self.customize())
        menu.append(item)
        item = Gtk.MenuItem(label="Quit tray icon")
        item.connect("activate", lambda *_: self.quit())
        menu.append(item)
        menu.show_all()
        self.sync_menu()
        return menu

    def sync_menu(self):
        self.syncing = True
        for (key, value), item in self.radios.items():
            item.set_active(self.cfg[key] == value)
        self.syncing = False

    def on_radio(self, item, key, value):
        if self.syncing or not item.get_active():
            return
        if key == "template":
            self.set_template(value)
        else:
            self.update(**{key: value})
            if self.window:
                self.fill_window()

    # ── customize window ─────────────────────────────────────────────────────
    def customize(self):
        if self.window is None:
            self.build_window()
        self.fill_window()
        self.window.present()

    def build_window(self):
        w = Gtk.ApplicationWindow(application=self, title="Thermaltake LCD")
        w.set_default_size(980, 0)
        w.set_border_width(16)
        w.connect("destroy", self.on_window_closed)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        w.add(box)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.preview = Gtk.Image()
        left.pack_start(self.preview, False, False, 0)
        note = Gtk.Label(label="Live preview. Changes apply to the panel immediately.", xalign=0)
        note.get_style_context().add_class("dim-label")
        left.pack_start(note, False, False, 0)
        box.pack_start(left, False, False, 0)

        self.notebook = Gtk.Notebook()
        box.pack_start(self.notebook, True, True, 0)
        self.window = w
        self.preview_timer = GLib.timeout_add(1500, self.live_preview)
        w.show_all()

    def on_window_closed(self, *_):
        GLib.source_remove(self.preview_timer)
        self.window = None

    def fill_window(self):
        """(Re)build the controls from the current settings."""
        self.syncing = True
        page = max(self.notebook.get_current_page(), 0)
        for child in self.notebook.get_children():
            self.notebook.remove(child)
        cfg = templates.resolve(self.cfg)

        def new_page(title):
            grid = Gtk.Grid(column_spacing=12, row_spacing=8, border_width=12)
            self.notebook.append_page(grid, Gtk.Label(label=title))
            return grid

        def add(grid, label, *widgets):
            row = len(grid.get_children()) and max(grid.child_get_property(c, "top-attach")
                                                    for c in grid.get_children()) + 1
            grid.attach(Gtk.Label(label=label, xalign=0, hexpand=True), 0, row, 1, 1)
            for col, widget in enumerate(widgets, 1):
                grid.attach(widget, col, row, 1 if col < len(widgets) else 3 - len(widgets) + 1, 1)

        def combo(options, active, on_change):
            c = Gtk.ComboBoxText()
            for value, label in options:
                c.append(str(value), label)
            c.set_active_id(str(active))
            c.connect("changed", lambda w: self.syncing or on_change(w.get_active_id()))
            return c

        def file_picker(key, title, patterns):
            btn = Gtk.FileChooserButton(title=title, action=Gtk.FileChooserAction.OPEN)
            flt = Gtk.FileFilter()
            for pattern in patterns:
                flt.add_pattern(pattern)
            btn.set_filter(flt)
            if cfg.get(key):
                btn.set_filename(cfg[key])
            btn.connect("file-set", lambda b: self.update(**{key: b.get_filename()}))
            clear = Gtk.Button(label="Clear")
            clear.connect("clicked", lambda *_: (self.update(**{key: None}), self.fill_window()))
            return btn, clear

        # Layout: template, metric per slot, optional label override
        grid = new_page("Layout")
        add(grid, "Template", combo([(k, t["name"]) for k, t in templates.TEMPLATES.items()],
                                    cfg["template"], self.set_template))
        options = []
        for k in sensors.available():
            m = sensors.METRICS[k]
            text = m.label or "(empty)"
            options.append((k, text if m.group in ("System", "GPUs") else f"{text}  · {m.group}"))
        for i, name in enumerate(templates.TEMPLATES[cfg["template"]]["slots"]):
            key = cfg["slots"][i]

            def set_slot(value, i=i):
                slots = list(templates.resolve(self.cfg)["slots"])
                slots[i] = value
                self.update(slots=slots)
                self.fill_window()

            entry = Gtk.Entry(placeholder_text=sensors.METRICS[key].label or "label", width_chars=12)
            entry.set_text((cfg.get("labels") or {}).get(key, ""))
            entry.set_tooltip_text("Rename this metric on the panel (leave empty for the default)")
            entry.set_sensitive(key != "none")

            def set_label(e, key=key):
                labels = dict(self.cfg.get("labels") or {})
                labels[key] = e.get_text().strip()
                self.update(delay=500, labels={k: v for k, v in labels.items() if v})
            entry.connect("changed", lambda e, f=set_label: self.syncing or f(e))
            add(grid, name, combo(options, key, set_slot), entry)

        # Look: colours, background image, font
        grid = new_page("Look")
        for key, label in (("accent", "Accent"), ("accent2", "Second accent"),
                           ("background", "Background colour")):
            btn = Gtk.ColorButton.new_with_rgba(hex_to_rgba(cfg[key]))
            btn.connect("color-set", lambda b, key=key: self.update(**{key: rgba_to_hex(b.get_rgba())}))
            add(grid, label, btn)
        reset = Gtk.Button(label="Reset colours")
        reset.connect("clicked", lambda *_: (self.update(accent=None, accent2=None, background=None),
                                             self.fill_window()))
        add(grid, "", reset)
        add(grid, "Background image",
            *file_picker("background_image", "Background image", ["*.png", "*.jpg", "*.jpeg", "*.webp"]))
        dim = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 95, 5)
        dim.set_value(cfg.get("background_dim", 50))
        dim.set_size_request(180, -1)
        dim.set_tooltip_text("How much the background colour covers the image, so numbers stay readable")
        dim.connect("value-changed",
                    lambda w: self.syncing or self.update(delay=300, background_dim=int(w.get_value())))
        add(grid, "Image dimming", dim)
        add(grid, "Font", *file_picker("font", "Font", ["*.ttf", "*.otf"]))

        # Panel: units, GPU aggregation, brightness, refresh
        grid = new_page("Panel")
        add(grid, "Temperature", combo([("C", "°C"), ("F", "°F")], cfg["unit"],
                                       lambda v: self.update(unit=v)))
        gpus = sensors.gpu_count()
        add(grid, "Combined GPU", combo([("all", "Hottest card" if gpus > 1 else "Auto")]
                                        + [(str(i), f"GPU {i + 1}") for i in range(gpus)],
                                        cfg["gpu"], lambda v: self.update(gpu=v)))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 5)
        scale.set_value(cfg["brightness"])
        scale.set_size_request(180, -1)
        scale.connect("value-changed",
                      lambda w: self.syncing or self.update(delay=400, brightness=int(w.get_value())))
        add(grid, "Brightness", scale)
        add(grid, "Update every", combo([(str(v), f"{v:g} s") for v in INTERVALS],
                                        str(cfg["interval"]), lambda v: self.update(interval=float(v))))

        # Advanced: config file, custom templates, restart
        grid = new_page("Advanced")
        note = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
        note.set_markup("Custom metrics (any command that prints a number) are added to "
                        "<tt>custom_metrics</tt> in the config file. Your own templates go in "
                        "the templates folder. See the README for examples.")
        grid.attach(note, 0, 0, 3, 1)
        for label, action in (("Edit config file", lambda *_: self.open_path(config.CONFIG_PATH)),
                              ("Open templates folder", lambda *_: self.open_path(templates.PLUGIN_DIR, True)),
                              ("Reload templates and restart dashboard", lambda *_: self.reload())):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", action)
            add(grid, "", btn)

        self.notebook.show_all()
        self.notebook.set_current_page(page)
        self.syncing = False
        self.render_preview()

    def open_path(self, path, directory=False):
        if directory:
            path.mkdir(parents=True, exist_ok=True)
        elif not path.exists():
            config.save(self.cfg, path)
        Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)

    def reload(self):
        templates.load_plugins()
        subprocess.run(["systemctl", "--user", "restart", "tt600d"], check=False)
        self.window.destroy()
        self.indicator.set_menu(self.build_menu())
        self.customize()

    def live_preview(self):
        self.values = sensors.read(self.cfg["gpu"])
        self.render_preview()
        return True

    def render_preview(self):
        if self.window:
            self.preview.set_from_pixbuf(
                pil_to_pixbuf(templates.render(self.values, self.cfg), PREVIEW_W))


def main():
    return Tray().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
