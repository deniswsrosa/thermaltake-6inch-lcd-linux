#!/usr/bin/env python3
"""Read-only probe for the Thermaltake 6.0" LCD Panel Kit (264a:2347).

Finds the hidraw node by VID:PID, reports what the kernel knows about it,
and listens for unsolicited input reports. Writes nothing to the panel.
"""
import glob
import os
import select
import sys
import time

VID, PID = 0x264A, 0x2347


def find_hidraw(vid=VID, pid=PID):
    """Return (node_path, sysfs_dir) for the first matching hidraw device."""
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent = os.path.join(path, "device", "uevent")
        try:
            with open(uevent) as fh:
                fields = dict(
                    line.strip().split("=", 1)
                    for line in fh
                    if "=" in line
                )
        except OSError:
            continue
        # HID_ID looks like 0003:0000264A:00002347
        hid_id = fields.get("HID_ID", "")
        parts = hid_id.split(":")
        if len(parts) == 3 and int(parts[1], 16) == vid and int(parts[2], 16) == pid:
            node = "/dev/" + os.path.basename(path)
            return node, os.path.realpath(os.path.join(path, "device"))
    return None, None


def decode_report_descriptor(raw):
    """Minimal HID item walker: enough to show report sizes/counts and IDs."""
    names = {
        0x04: "Usage Page", 0x08: "Usage", 0x14: "Logical Min", 0x24: "Logical Max",
        0x74: "Report Size", 0x94: "Report Count", 0x84: "Report ID",
        0x80: "Input", 0x90: "Output", 0xB0: "Feature",
        0xA0: "Collection", 0xC0: "End Collection",
    }
    out, i = [], 0
    while i < len(raw):
        b = raw[i]
        size = b & 0x03
        size = 4 if size == 3 else size
        tag = b & 0xFC
        val = int.from_bytes(raw[i + 1:i + 1 + size], "little") if size else None
        label = names.get(tag, f"tag 0x{tag:02X}")
        out.append(f"  {label}" + (f" = {val}" if val is not None else ""))
        i += 1 + size
    return "\n".join(out)


def main():
    node, sysfs = find_hidraw()
    if not node:
        print(f"No hidraw device for {VID:04x}:{PID:04x} — is the panel plugged in?")
        return 1

    print(f"device node : {node}")
    print(f"sysfs       : {sysfs}")
    st = os.stat(node)
    print(f"permissions : {oct(st.st_mode & 0o777)} uid={st.st_uid} gid={st.st_gid}")
    print(f"writable    : {os.access(node, os.W_OK)}")

    desc_path = os.path.join(sysfs, "report_descriptor")
    try:
        with open(desc_path, "rb") as fh:
            raw = fh.read()
        print(f"\nreport descriptor ({len(raw)} bytes): {raw.hex(' ')}")
        print(decode_report_descriptor(raw))
    except OSError as exc:
        print(f"\ncould not read report descriptor: {exc}")

    if not os.access(node, os.R_OK):
        print(f"\nCannot open {node} for reading — install the udev rule first:")
        print("  sudo cp 99-thermaltake-lcd.rules /etc/udev/rules.d/")
        print("  sudo udevadm control --reload-rules && sudo udevadm trigger")
        return 2

    print("\nlistening 3s for unsolicited input reports (no writes sent)...")
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    try:
        deadline = time.time() + 3.0
        seen = 0
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.25)
            if not ready:
                continue
            data = os.read(fd, 2048)
            seen += 1
            trimmed = data.rstrip(b"\x00")
            print(f"  IN [{len(data)} bytes, {len(trimmed)} non-zero]: "
                  f"{data[:32].hex(' ')}{' ...' if len(data) > 32 else ''}")
        if not seen:
            print("  (silent — panel does not report until it is initialised)")
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
