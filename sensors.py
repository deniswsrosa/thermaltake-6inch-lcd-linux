"""System metrics for the tt600 dashboard.

read() returns {metric_key: value or None}. METRICS describes each key so
templates can label, scale and colour it without knowing where it came from.
"""

import subprocess
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class Metric:
    label: str
    unit: str          # "temp" is special: rendered in °C or °F
    max: float         # full scale for gauges and bars
    warn: float = None
    crit: float = None


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


def gpu_count():
    return len(_nvidia())


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
    gpus = _nvidia()
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
