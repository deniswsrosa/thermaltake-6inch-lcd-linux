#!/usr/bin/env python3
"""tt600 — Linux control for the Thermaltake 6.0" LCD Panel Kit (View 600 TG).

Device: USB HID 264a:2347, single interface, 1024-byte interrupt IN and OUT,
no report IDs. The panel runs embedded Linux and speaks the "BY" protocol,
recovered from TT RGB Plus 3.0.9 (Device_LCD_BY_6inch + BYProtocol.dll).

Commands are HTTP-like text messages, framed and sent as one 1024-byte report:

  5A | len_be16 | "POST conn 1\\r\\nSeqNumber=112\\r\\n..." | sum8 | 5A

  len  = length of the whole unescaped frame (payload + 5)
  sum8 = sum of the length bytes and payload, mod 256
  then every 5A/5B between the two magic bytes is escaped to 5B 01 / 5B 02.

The panel replies on the IN endpoint with the same framing ("1 200", an
AckNumber and an optional JSON body).

Live frames are a JPEG of exactly 1110x540 (or 540x1110), sent after
`POST realtimeDisplay` as 1024-byte reports of 24-byte header + 1000 B data:

  [5C 03 FD counter total_be16 index_be16 01] + 15 zero bytes + data

The panel falls back to its own screen when frames stop for `timeout`
seconds (5 by default), so a still image has to be re-sent periodically.

hidraw note: usbhid strips a leading 0x00 report-number byte for devices with
no numbered reports, so a 1024-byte report is written as 0x00 + 1024 bytes.
"""

__version__ = "1.0.0"

import argparse
import glob
import io
import json
import os
import select
import sys
import time

VID, PID = 0x264A, 0x2347
WIDTH, HEIGHT = 1110, 540
PACKET = 1024
FRAME_HEADER = 24
FRAME_DATA = PACKET - FRAME_HEADER
MAX_JPEG = 0xC7FFF          # TT RGB Plus refuses larger frames
SEQ = 112                   # SeqNumber TT RGB Plus uses for this panel


def find_device():
    """Return the hidraw node for VID:PID, or None."""
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(path, "device", "uevent")) as fh:
                text = fh.read()
        except OSError:
            continue
        if f"{VID:08X}:{PID:08X}" in text.upper():
            return "/dev/" + os.path.basename(path)
    return None


# ── BYProtocol framing ───────────────────────────────────────────────────────
def frame(payload):
    """Wrap a message in the 5A-delimited, checksummed, escaped frame."""
    total = len(payload) + 5
    body = bytes((total >> 8, total & 0xFF)) + payload
    body += bytes((sum(body) & 0xFF,))
    body = body.replace(b"\x5b", b"\x5b\x02").replace(b"\x5a", b"\x5b\x01")
    return b"\x5a" + body + b"\x5a"


def unframe(data):
    """Inverse of frame(): return the payload of the first frame in data."""
    start = data.index(0x5A)
    end = data.index(0x5A, start + 1)
    body = data[start + 1:end].replace(b"\x5b\x01", b"\x5a").replace(b"\x5b\x02", b"\x5b")
    if (sum(body[:-1]) & 0xFF) != body[-1]:
        raise ValueError("reply checksum mismatch")
    return body[2:-1]


def message(verb, body=""):
    return (f"{verb}\r\nSeqNumber={SEQ}\r\nContentType=json\r\n"
            f"ContentLength={len(body)}\r\n\r\n{body}").encode()


def parse_reply(payload):
    """Split a reply into (status line, JSON body or None)."""
    text = payload.decode(errors="replace")
    head, _, body = text.partition("\r\n\r\n")
    status = head.split("\r\n", 1)[0]
    return status, (json.loads(body) if body.strip() else None)


class Panel:
    def __init__(self, node, verbose=True):
        self.verbose = verbose
        self.fd = os.open(node, os.O_RDWR)
        self.counter = 0

    def close(self):
        os.close(self.fd)

    def _write(self, report):
        if len(report) != PACKET:
            raise ValueError(f"report is {len(report)} bytes, expected {PACKET}")
        os.write(self.fd, b"\x00" + report)

    def command(self, verb, body="", timeout=3.0):
        """Send one command, return (status, json) from the panel's reply."""
        packet = frame(message(verb, body))
        if len(packet) > PACKET:
            raise ValueError("command does not fit in one report")
        self._write(packet.ljust(PACKET, b"\x00"))
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            raise TimeoutError(f"no reply to {verb!r}")
        status, data = parse_reply(unframe(os.read(self.fd, PACKET + 1)))
        if not status.endswith(" 200"):
            raise RuntimeError(f"{verb!r} failed: {status}")
        return status, data

    # ── commands ─────────────────────────────────────────────────────────────
    def connect(self):
        """Handshake; returns the panel's status (versions, brightness, …)."""
        return self.command("POST conn 1")[1]

    def realtime(self, enable=True):
        self.command("POST realtimeDisplay 1", json.dumps({"enable": enable}))

    def brightness(self, value):
        self.command("POST brightness 1", json.dumps({"value": max(0, min(100, value))}))

    def rotate(self, degree):
        self.command("POST rotate 1", json.dumps({"degree": degree}))

    # ── frames ───────────────────────────────────────────────────────────────
    def send_jpeg(self, jpeg):
        """Send one realtime frame. Returns the number of reports written."""
        if not 0 < len(jpeg) <= MAX_JPEG:
            raise ValueError(f"JPEG is {len(jpeg)} bytes, limit {MAX_JPEG}")
        total = -(-len(jpeg) // FRAME_DATA)
        for idx in range(total):
            head = bytes((0x5C, 0x03, 0xFD, self.counter,
                          total >> 8, total & 0xFF, idx >> 8, idx & 0xFF, 0x01))
            chunk = jpeg[idx * FRAME_DATA:(idx + 1) * FRAME_DATA]
            self._write((head.ljust(FRAME_HEADER, b"\x00") + chunk).ljust(PACKET, b"\x00"))
        self.counter = (self.counter + 1) % 60
        return total


def to_jpeg(img, quality=85):
    """Fit a PIL image to the panel and return baseline JPEG bytes."""
    from PIL import Image
    img = img.convert("RGB")
    if img.size != (WIDTH, HEIGHT):
        img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def test_pattern():
    """Corner-marked image, so orientation and cropping are visible."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (WIDTH, HEIGHT), "#202020")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline="#00ff88", width=8)
    for (x, y), colour, label in (
        ((0, 0), "#ff3333", "TL"), ((WIDTH - 180, 0), "#33ff33", "TR"),
        ((0, HEIGHT - 120), "#3333ff", "BL"), ((WIDTH - 180, HEIGHT - 120), "#ffff33", "BR"),
    ):
        d.rectangle([x + 16, y + 16, x + 164, y + 104], fill=colour)
        d.text((x + 80, y + 52), label, fill="#000000")
    d.text((WIDTH // 2 - 40, HEIGHT // 2), f"{WIDTH}x{HEIGHT}", fill="#ffffff")
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("status", "testpattern", "image", "brightness", "rotate"))
    ap.add_argument("arg", nargs="?", help="image file, brightness 0-100, or rotation degrees")
    ap.add_argument("--hold", type=float, default=0,
                    help="seconds to keep a still image up (default: until Ctrl-C)")
    ap.add_argument("--fps", type=float, default=2, help="re-send rate for a still image")
    ap.add_argument("--quality", type=int, default=85, help="JPEG quality")
    args = ap.parse_args()

    node = find_device()
    if not node:
        print(f"No hidraw node for {VID:04x}:{PID:04x} — is the panel connected?")
        return 1
    if not os.access(node, os.W_OK):
        print(f"{node} is not writable. Install the udev rule first:\n"
              "  sudo cp 99-thermaltake-lcd.rules /etc/udev/rules.d/\n"
              "  sudo udevadm control --reload-rules && sudo udevadm trigger")
        return 2

    panel = Panel(node)
    try:
        status = panel.connect()
        if args.action == "status":
            print(json.dumps(status, indent=2))
        elif args.action == "brightness":
            panel.brightness(int(args.arg))
        elif args.action == "rotate":
            panel.rotate(int(args.arg))
        else:
            from PIL import Image
            if args.action == "image":
                if not args.arg:
                    ap.error("the 'image' action needs a file")
                img = Image.open(args.arg)
            else:
                img = test_pattern()
            jpeg = to_jpeg(img, args.quality)
            panel.realtime(True)
            print(f"{node}: streaming {len(jpeg)} B JPEG at {args.fps} fps "
                  f"({'Ctrl-C to stop' if not args.hold else f'{args.hold}s'})")
            end = time.monotonic() + args.hold if args.hold else None
            try:
                while end is None or time.monotonic() < end:
                    panel.send_jpeg(jpeg)
                    time.sleep(1 / args.fps)
            except KeyboardInterrupt:
                pass
    finally:
        panel.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
