"""Minimal Turing revision C transport for the SL360 XE's CT21INCH panel.

Adapted from Denis WS Rosa's sl360xe/driver.py (2026), whose protocol code
was adapted from mathoudebine/turing-smart-screen-python.
Only the 480x480, three-byte BGR partial-update path is implemented.

SPDX-License-Identifier: GPL-3.0-or-later. See licenses/GPL-3.0.txt.
"""

from __future__ import annotations

import time
import logging

import serial
from PIL import Image, ImageChops
import pump_detect

SIZE = 480
LOG = logging.getLogger("sl360xe.driver")


def _device(awake: bool) -> str | None:
    port = pump_detect.awake_port() if awake else pump_detect.sleeping_port()
    return port.device if port else None


def _packet(data: bytes) -> bytes:
    return data + bytes((-len(data)) % 250)


class Panel:
    def __init__(self, brightness: int = 40, flipped: bool = False, rotation: int = 0,
                 reset_on_start: bool = True):
        if not 0 <= brightness <= 100:
            raise ValueError("brightness must be 0..100")
        if rotation not in (0, 90, 180, 270):
            raise ValueError("rotation must be 0, 90, 180, or 270 degrees")
        self.brightness = brightness
        self.flipped = flipped
        self.rotation = rotation
        self.reset_on_start = reset_on_start
        self.port: serial.Serial | None = None
        self.last: Image.Image | None = None
        self.counter = 0

    def __enter__(self) -> "Panel":
        for _ in range(15):
            awake = _device(True)
            if awake:
                try:
                    self.port = serial.Serial(awake, 115200, timeout=1, write_timeout=5, rtscts=True, exclusive=True)
                    break
                except serial.SerialException as error:
                    raise RuntimeError(f"Cannot open {awake}: {error}. Check udev permissions and other LCD services.") from error
            sleeping = _device(False)
            if sleeping:
                try:
                    with serial.Serial(sleeping, 115200, timeout=1, rtscts=True):
                        pass
                except serial.SerialException as error:
                    raise RuntimeError(f"Cannot wake {sleeping}: {error}. Install the udev rule first.") from error
            time.sleep(1)
        if self.port is None:
            raise RuntimeError("CT21INCH panel was not found. Check lsusb and the USB connection.")
        if self.reset_on_start:
            self._reset_and_reopen()
        response = b""
        for _ in range(15):
            self.port.reset_input_buffer()
            self._send(bytes.fromhex("01 ef 69 00 00 00 01 00 00 00 c5 d3"))
            response = self.port.read(23)
            if b"chs_" in response:
                break
            time.sleep(1)
        if b"chs_" not in response:
            self.close()
            raise RuntimeError(f"Unexpected panel handshake: {response!r}")
        self._send(bytes.fromhex("79 ef 69 00 00 00 01"))  # stop video
        self._send(bytes.fromhex("96 ef 69 00 00 00 01"))  # stop media
        self.port.read(1024)
        self._send(bytes.fromhex("7b ef 69 00 00 00 01 00 00 00") + bytes([round(brightness_to_byte(self.brightness))]))
        self._send(bytes.fromhex("7d ef 69 00 00 00 05 00 00 00 2d 00 00 00 00"))
        return self

    def _reset_and_reopen(self) -> None:
        """Return firmware to bitmap mode before starting a new process.

        Rev C re-enumerates its USB serial port on RESTART. Without this step,
        later processes can write successfully while the screen holds its old
        image. The upstream driver performs the same reset on startup.
        """
        LOG.info("Resetting display and waiting for USB reconnect")
        self._send(bytes.fromhex("84 ef 69 00 00 00 01"))
        self.close()
        vanished = False
        for _ in range(30):
            if _device(True) is None:
                vanished = True
                break
            time.sleep(0.5)
        if not vanished:
            raise RuntimeError("Display did not disconnect after reset")
        for _ in range(30):
            awake = _device(True)
            if awake:
                try:
                    self.port = serial.Serial(awake, 115200, timeout=1, write_timeout=5,
                                              rtscts=True, exclusive=True)
                    # USB enumeration completes before the firmware is ready
                    # to answer HELLO.
                    time.sleep(2)
                    LOG.info("Display reconnected on %s", awake)
                    return
                except serial.SerialException:
                    pass
            time.sleep(0.5)
        raise RuntimeError("Display did not reconnect after reset")

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.port:
            self.port.close()
            self.port = None

    def _send(self, data: bytes) -> None:
        assert self.port is not None
        self.port.write(_packet(data))

    def _update(self, image: Image.Image, x: int, y: int) -> None:
        assert self.port is not None
        # Rev C portrait mapping; the LCD's address space is rotated 90 degrees.
        image = image.rotate(90, expand=True).convert("RGB")
        x0 = SIZE - x - image.height
        y0 = y
        bgr = image.tobytes("raw", "BGR")
        rows = bytearray()
        stride = image.width * 3
        for row in range(image.height):
            rows.extend(((x0 + row) * SIZE + y0).to_bytes(3, "big"))
            rows.extend(image.width.to_bytes(2, "big"))
            rows.extend(bgr[row * stride:(row + 1) * stride])
        size = len(rows) + 2
        header = bytes.fromhex("cc ef 69 00") + size.to_bytes(3, "big") + b"\0\0\0" + self.counter.to_bytes(4, "big")
        self._send(header)
        chunks = [bytes(rows[i:i + 249]) for i in range(0, len(rows), 249)]
        self._send(b"\0".join(chunks) + b"\xef\x69")
        self._send(bytes.fromhex("cf ef 69 00 00 00 01"))
        self.port.read(1024)
        self.counter = (self.counter + 1) & 0xFFFFFFFF

    def show(self, frame: Image.Image) -> bool:
        if frame.size != (SIZE, SIZE):
            raise ValueError("frame must be 480x480")
        frame = frame.convert("RGB")
        if self.flipped or self.rotation:
            frame = frame.rotate((180 if self.flipped else 0) + self.rotation)
        box = ImageChops.difference(self.last, frame).getbbox() if self.last else (0, 0, SIZE, SIZE)
        if box is None:
            return False
        # Splitting a full-screen update keeps both transfers on the 3-byte BGR path.
        if box == (0, 0, SIZE, SIZE):
            self._update(frame.crop((0, 0, SIZE, SIZE // 2)), 0, 0)
            self._update(frame.crop((0, SIZE // 2, SIZE, SIZE)), 0, SIZE // 2)
        else:
            self._update(frame.crop(box), box[0], box[1])
        self.last = frame.copy()
        return True


def brightness_to_byte(percent: int) -> int:
    return int(percent * 255 / 100)
