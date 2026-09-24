"""System metrics for the tt600 dashboard.

read() returns {metric_key: value or None}. METRICS describes each key so
templates can label, scale and colour it without knowing where it came from.

Besides the built-in metrics, every hwmon temperature and fan the kernel
exposes is available as "hw:<chip>:<n>" (discover()), and users can add
metrics backed by a shell command in config.json (register_custom()).
"""

import re
import subprocess
import time
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class Metric:
    label: str
    unit: str          # "temp" is special: rendered in °C or °F
    max: float         # full scale for gauges and bars
    warn: float = None
    crit: float = None
    group: str = "System"   # heading in the tray's metric picker


METRICS = {
    "cpu_temp":  Metric("CPU", "temp", 100, 75, 90),
    "cpu_load":  Metric("CPU LOAD", "%", 100),
    "gpu_temp":  Metric("GPU", "temp", 100, 75, 85),
    "gpu_load":  Metric("GPU LOAD", "%", 100),
    "gpu_power": Metric("GPU POWER", "W", 450),
    "gpu_vram":  Metric("VRAM", "%", 100),
    "ram":       Metric("RAM", "%", 100, 85, 95),
    "ssd_temp":  Metric("SSD", "temp", 90, 60, 70),
    "fan":       Metric("FAN", "RPM", 3000),
    "none":      Metric("", "", 1),
}

MAX_GPUS = 4
for _i in range(MAX_GPUS):  # per-card metrics, labelled from 1 for humans
    METRICS[f"gpu{_i}_temp"] = Metric(f"GPU {_i + 1}", "temp", 100, 75, 85, "GPUs")
    METRICS[f"gpu{_i}_load"] = Metric(f"GPU {_i + 1} LOAD", "%", 100, group="GPUs")
    METRICS[f"gpu{_i}_power"] = Metric(f"GPU {_i + 1} POWER", "W", 450, group="GPUs")
    METRICS[f"gpu{_i}_vram"] = Metric(f"GPU {_i + 1} VRAM", "%", 100, group="GPUs")


# ── hwmon sensors ────────────────────────────────────────────────────────────
def _hw_entries():
    """Yield (key, chip, label, current, kind) for every hwmon temp and fan."""
    for kind, readings in (("temp", psutil.sensors_temperatures()), ("fan", psutil.sensors_fans())):
        for chip, entries in readings.items():
            for n, e in enumerate(entries):
                yield f"hw:{kind}:{chip}:{n}", chip, e.label, e.current, kind, e


def discover():
    """Register every hwmon temperature and fan as a selectable metric."""
    for key, chip, label, _, kind, e in _hw_entries():
        name = f"{chip} {label}".strip() if label else f"{chip} #{key.rsplit(':', 1)[1]}"
        if kind == "temp":
            high = e.high if e.high and 30 < e.high < 150 else 100
            crit = e.critical if e.critical and 30 < e.critical < 150 else None
            METRICS[key] = Metric(name.upper(), "temp", high, None if crit is None else high * 0.9,
                                  crit, "Hardware sensors")
        else:
            METRICS[key] = Metric(name.upper(), "RPM", 3000, group="Hardware sensors")


# ── custom command metrics ───────────────────────────────────────────────────
_custom = {}   # key -> {"command", "every", "last", "value"}
_number = re.compile(r"-?\d+(?:\.\d+)?")


def register_custom(specs):
    """Register metrics from config.json's "custom_metrics" list.

    Each spec: {"id", "label", "command", "unit" ("temp", "%", or any text),
    "max", optional "warn", "crit", "every" (seconds between runs, default 5)}.
    """
    for key in [k for k in METRICS if k.startswith("custom:")]:
        del METRICS[key]
    live = set()
    for spec in specs or []:
        try:
            key = f"custom:{spec['id']}"
            METRICS[key] = Metric(str(spec.get("label", spec["id"])).upper(),
                                  str(spec.get("unit", "")), float(spec.get("max", 100)),
                                  spec.get("warn"), spec.get("crit"), "Custom")
            old = _custom.get(key, {})
            _custom[key] = {"command": str(spec["command"]), "every": float(spec.get("every", 5)),
                            "last": old.get("last", 0) if old.get("command") == spec["command"] else 0,
                            "value": old.get("value")}
            live.add(key)
        except (KeyError, TypeError, ValueError):
            continue
    for key in set(_custom) - live:
        del _custom[key]


def _run_custom(key):
    c = _custom[key]
    if time.monotonic() - c["last"] >= c["every"]:
        c["last"] = time.monotonic()
        try:
            out = subprocess.run(c["command"], shell=True, capture_output=True, text=True,
                                 timeout=min(5, c["every"])).stdout
            match = _number.search(out)
            c["value"] = float(match.group()) if match else None
        except (OSError, subprocess.SubprocessError):
            c["value"] = None
    return c["value"]


# ── built-in sources ─────────────────────────────────────────────────────────
def _cpu_temp(temps):
    for chip, label in (("k10temp", "Tctl"), ("coretemp", "Package id 0"), ("zenpower", "Tdie")):
        value = next((e.current for e in temps.get(chip, []) if e.label == label), None)
        if value is not None:
            return value
    return None


def _nvidia():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,"
             "memory.used,memory.total,power.draw", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    def num(v):
        try:
            return float(v)
        except ValueError:
            return None
    return [[num(f) for f in line.split(",")] for line in out.strip().splitlines()]


_gpu_count = None


def gpu_count():
    global _gpu_count
    if _gpu_count is None:
        _gpu_count = len(_nvidia())
    return _gpu_count


def available(gpus=None):
    """Metric keys that make sense on this machine."""
    gpus = gpu_count() if gpus is None else gpus
    return [k for k in METRICS
            if not (k.startswith("gpu") and k[3].isdigit() and int(k[3]) >= gpus)]


def read(gpu="all"):
    """Sample every metric. gpu is an index, or "all" (hottest/busiest, summed power)."""
    temps = psutil.sensors_temperatures()
    mem = psutil.virtual_memory()
    ssd = [e.current for e in temps.get("nvme", []) if e.label == "Composite"]
    fans = [f.current for chip in psutil.sensors_fans().values() for f in chip if f.current]
    values = {
        "cpu_temp": _cpu_temp(temps),
        "cpu_load": psutil.cpu_percent(),
        "ram": mem.percent,
        "ssd_temp": max(ssd) if ssd else None,
        "fan": max(fans) if fans else None,
        "gpu_temp": None, "gpu_load": None, "gpu_power": None, "gpu_vram": None,
        "none": None,
    }
    for key, _, _, current, _, _ in _hw_entries():
        values[key] = current
    for key in list(_custom):
        values[key] = _run_custom(key)

    gpus = _nvidia()
    for i in range(MAX_GPUS):
        temp, util, used, total, power = gpus[i] if i < len(gpus) else (None,) * 5
        values.update({f"gpu{i}_temp": temp, f"gpu{i}_load": util, f"gpu{i}_power": power,
                       f"gpu{i}_vram": 100 * used / total if used is not None and total else None})
    if gpu != "all":
        gpus = gpus[int(gpu):int(gpu) + 1]
    if gpus:
        def pick(i, fn):
            vals = [g[i] for g in gpus if g[i] is not None]
            return fn(vals) if vals else None
        used, total = pick(2, sum), pick(3, sum)
        values.update(gpu_temp=pick(0, max), gpu_load=pick(1, max), gpu_power=pick(4, sum),
                      gpu_vram=100 * used / total if used is not None and total else None)
    return values


discover()
