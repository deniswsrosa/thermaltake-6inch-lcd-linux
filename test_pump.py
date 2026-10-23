"""Pump detection and live rendering regressions without opening USB devices."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pump_mock
import pump_detect


class PumpIntegrationTests(unittest.TestCase):
    def test_detection_requires_the_pump_serial_identity(self):
        other = SimpleNamespace(vid=0x1D6B, pid=0x0121,
                                serial_number="20080411", device="/dev/ttyACM0",
                                location="8-13.1:1.0")
        pump = SimpleNamespace(vid=0x1A86, pid=0xCA21,
                               serial_number="CT21INCH", device="/dev/ttyACM1",
                               location="8-12.2:1.0")
        awake = SimpleNamespace(vid=0x1D6B, pid=0x0121,
                                serial_number="20080411", device="/dev/ttyACM2",
                                location="8-12.2:1.0")
        with TemporaryDirectory() as temp, patch.object(pump_detect, "LOCATION_PATH", Path(temp) / "port"):
            with patch.object(pump_detect, "comports", return_value=[other]):
                self.assertFalse(pump_detect.present())
            with patch.object(pump_detect, "comports", return_value=[other, pump]):
                self.assertTrue(pump_detect.present())
                self.assertIsNone(pump_detect.awake_port())
            with patch.object(pump_detect, "comports", return_value=[other, awake]):
                self.assertTrue(pump_detect.present())
                self.assertEqual(pump_detect.awake_port().device, "/dev/ttyACM2")

    def test_awake_identity_on_sibling_hub_port(self):
        sleeping = SimpleNamespace(vid=0x1A86, pid=0xCA21,
                                   serial_number="CT21INCH", device="/dev/ttyACM1",
                                   location="8-12.2:1.0")
        sibling = SimpleNamespace(vid=0x1D6B, pid=0x0121,
                                  serial_number="20080411", device="/dev/ttyACM0",
                                  location="8-12.1:1.0")
        with TemporaryDirectory() as temp, patch.object(pump_detect, "LOCATION_PATH", Path(temp) / "port"):
            with patch.object(pump_detect, "comports", return_value=[sleeping, sibling]):
                self.assertEqual(pump_detect.awake_port().device, "/dev/ttyACM0")

    def test_live_readings_are_unitless_temperatures(self):
        readings = pump_mock.format_values({"cpu_temp": 62.4, "cpu_load": 41.8,
                                            "fan": 2471})
        self.assertEqual(readings["cpu_temp"], "62")
        self.assertEqual(readings["cpu_load"], "42%")
        self.assertEqual(readings["fan"], "2471")
        self.assertEqual(readings["gpu_temp"], "--")
        image = pump_mock.render({**pump_mock.DEFAULTS, "layout": "gif_overlay"},
                                 readings=readings, now=1)
        self.assertEqual(image.size, (480, 480))


if __name__ == "__main__":
    unittest.main()
