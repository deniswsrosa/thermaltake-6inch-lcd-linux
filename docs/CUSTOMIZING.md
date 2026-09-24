# Customizing the dashboard

Everything below can be set from the tray's **Customize** window, or by
editing `~/.config/tt600/config.json` by hand (the service reloads it on save).

## Any sensor your system has

Besides the built-in metrics, every temperature and fan that `sensors`/hwmon
exposes shows up in the metric picker, tagged "Hardware sensors". That covers
Intel CPUs (`coretemp`), AMD GPUs (`amdgpu`), motherboard and liquid-cooling
sensors, and so on.

## Custom metrics from a command

Any command that prints a number can become a metric. Add it to
`custom_metrics` in the config file:

```json
"custom_metrics": [
  {"id": "coolant", "label": "Coolant", "unit": "temp", "max": 60, "warn": 40, "crit": 50,
   "command": "liquidctl status --json | jq '.[0].status[0].value'", "every": 5},
  {"id": "uptime", "label": "Uptime", "unit": "h", "max": 48,
   "command": "awk '{print $1/3600}' /proc/uptime"}
]
```

- `unit`: `temp` (shown in °C or °F), `%`, or any short text.
- `max`: full scale for gauges and bars. `warn`/`crit` turn the value amber/red.
- `every`: seconds between runs (default 5).

The first number in the command's output is used. The metrics then appear in
the picker as "Custom".

## Labels, colours, background image, font

- **Labels**: rename any metric on the panel, e.g. `GPU 1` → `TOP 3090`, with the
  box next to each metric in the Layout tab (`"labels": {"gpu0_temp": "TOP 3090"}`).
- **Colours**: two accents and a background per template.
- **Background image**: any picture, cover-fitted to the panel. *Image
  dimming* (0–95) blends it toward the background colour so the numbers stay
  readable.
- **Font**: any `.ttf`/`.otf` file.

## Your own templates

Drop a Python file in `~/.config/tt600/templates/`. It defines `TEMPLATE` (name,
slot names, optional default metrics and colours) and `draw(canvas, values, cfg)`,
which draws in panel pixels (1110×540). See
[`examples/templates/split.py`](../examples/templates/split.py):

```sh
mkdir -p ~/.config/tt600/templates
cp examples/templates/split.py ~/.config/tt600/templates/
```

Then use **Advanced → Reload templates and restart dashboard** in the tray.
A template that raises an error shows the message on the panel instead of
crashing the service.

Built-in templates live in `templates.py` and follow the same shape.

## Command-line tools

```sh
python3 tt600d.py                       # the dashboard daemon, in the foreground
python3 tt600d.py --preview out.png     # render one frame with the current settings
python3 tt600-tray.py                   # the tray app
python3 tt600.py status                 # handshake and print the panel's status JSON
python3 tt600.py image photo.png        # show an image (until Ctrl-C, or --hold N)
python3 tt600.py testpattern            # corner-marked frame for checking orientation
python3 tt600.py brightness 60
python3 tt600.py rotate 270
python3 tt_probe.py                     # read-only: identify, decode descriptor, listen
```

## Resource use

The service is built to be left running. It uses about **0.2% of one CPU
core and ~35 MB of memory**, and the idle tray icon uses even less. It
achieves this by:

- reading NVIDIA GPUs through NVML in-process instead of spawning `nvidia-smi`
  (it falls back to `nvidia-smi` if NVML is missing)
- sampling only the sensors that are on screen
- re-rendering only when a displayed number changes; otherwise it re-sends the
  last frame every 2 s to keep the panel from falling back to its own screen
- rendering with cached backgrounds and low-resolution glow, then returning
  image buffers to the OS

The update interval ("Update every" in the tray) can go up to 10 s. The panel
stays live either way.
