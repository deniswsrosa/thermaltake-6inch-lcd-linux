"""Regression coverage for GPUs becoming available after dashboard startup."""

import unittest
from unittest.mock import Mock, patch

import sensors


class GPUDiscoveryTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("_nvml", None), ("_gpu_count", None),
                            ("_gpu_refresh_at", 0.0), ("_gpu_discovery_until", 400.0)):
            patcher = patch.object(sensors, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @patch("sensors.time.monotonic")
    @patch("sensors._NVML")
    def test_late_gpu_is_discovered_without_restart(self, nvml, clock):
        first = Mock()
        first.read.return_value = [[45, 0, 100, 1000, 20]]
        second = Mock()
        second.read.return_value = [[45, 0, 100, 1000, 20], [60, 10, 200, 1000, 80]]
        nvml.side_effect = [first, second]
        clock.return_value = 100
        self.assertEqual(sensors.gpu_count(), 1)
        self.assertIsNone(sensors.read(keys=["gpu1_temp"])["gpu1_temp"])
        clock.return_value = 129
        self.assertEqual(sensors.gpu_count(), 1)
        self.assertEqual(nvml.call_count, 1)
        clock.return_value = 131
        self.assertEqual(sensors.gpu_count(), 2)
        self.assertEqual(sensors.read(keys=["gpu1_temp"])["gpu1_temp"], 60)
        first.close.assert_called_once()
        self.assertIn("gpu1_temp", sensors.available())

    @patch("sensors.subprocess.run", side_effect=OSError("driver unavailable"))
    @patch("sensors.time.monotonic")
    @patch("sensors._NVML")
    def test_failed_initialization_is_retried(self, nvml, clock, run):
        recovered = Mock()
        recovered.read.return_value = [[45, 0, 100, 1000, 20]]
        nvml.side_effect = [OSError("not ready"), recovered]
        clock.return_value = 100
        self.assertEqual(sensors.gpu_count(), 0)
        clock.return_value = 131
        self.assertEqual(sensors.gpu_count(), 1)
        self.assertEqual(sensors.read(keys=["gpu0_temp"])["gpu0_temp"], 45)

    @patch("sensors.time.monotonic")
    @patch("sensors._NVML")
    def test_discovery_stops_after_five_minutes_but_sampling_continues(self, nvml, clock):
        reader = nvml.return_value
        reader.read.return_value = [[45, 0, 100, 1000, 20]]
        for second in range(100, 401, 30):
            clock.return_value = second
            self.assertEqual(sensors.gpu_count(), 1)
        self.assertEqual(nvml.call_count, 11)
        self.assertEqual(reader.close.call_count, 10)
        reader.read.return_value = [[55, 0, 100, 1000, 20]]
        for second in (401, 430, 1000, 10000):
            clock.return_value = second
            self.assertEqual(sensors.read(keys=["gpu0_temp"])["gpu0_temp"], 55)
            self.assertEqual(sensors.gpu_count(), 1)
        self.assertEqual(nvml.call_count, 11)
        self.assertEqual(reader.close.call_count, 10)
        clock.reset_mock()
        read_count = reader.read.call_count
        self.assertEqual(sensors.gpu_count(), 1)
        self.assertEqual(reader.read.call_count, read_count)
        self.assertEqual(sensors.read(keys=["gpu0_temp"])["gpu0_temp"], 55)
        clock.assert_not_called()

    @patch("sensors.subprocess.run", side_effect=OSError("driver unavailable"))
    @patch("sensors.time.monotonic")
    @patch("sensors._NVML", side_effect=OSError("not ready"))
    def test_initialization_retries_also_stop_after_five_minutes(self, nvml, clock, run):
        for second in range(100, 401, 30):
            clock.return_value = second
            self.assertEqual(sensors.gpu_count(), 0)
        for second in (401, 430, 10000):
            clock.return_value = second
            self.assertIsNone(sensors.read(keys=["gpu0_temp"])["gpu0_temp"])
        self.assertEqual(nvml.call_count, 11)

    @patch("sensors.ctypes.CDLL")
    def test_unavailable_handle_does_not_shift_card_indices(self, cdll):
        lib = cdll.return_value
        lib.nvmlInit_v2.return_value = 0

        def count(pointer):
            pointer._obj.value = 2
            return 0

        def handle(index, pointer):
            pointer._obj.value = index + 1
            return 1 if index == 0 else 0

        def temperature(handle, sensor, pointer):
            pointer._obj.value = 60
            return 0

        lib.nvmlDeviceGetCount_v2.side_effect = count
        lib.nvmlDeviceGetHandleByIndex_v2.side_effect = handle
        lib.nvmlDeviceGetTemperature.side_effect = temperature
        reader = sensors._NVML()
        rows = reader.read()
        self.assertEqual(rows[0], [None] * 5)
        self.assertEqual(rows[1][0], 60)


if __name__ == "__main__":
    unittest.main()
