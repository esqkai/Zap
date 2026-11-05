"""Tests for the outlet cover/glow mapping (no physical plug detection)."""
import unittest

from nxxt_level.device.socket_appearance import SocketAppearance, socket_appearance


class TestSocketAppearance(unittest.TestCase):
    def test_off_is_uncovered_without_glow_even_with_stale_watts(self):
        self.assertEqual(socket_appearance({"on": False, "power_w": 40}, online=True), SocketAppearance.OFF)

    def test_on_idle_is_uncovered_with_glow(self):
        self.assertEqual(socket_appearance({"on": True, "power_w": 0}, online=True), SocketAppearance.ON_IDLE)
        self.assertEqual(socket_appearance({"on": True, "power_w": 1.9}, online=True), SocketAppearance.ON_IDLE)

    def test_on_loaded_is_covered_with_glow(self):
        self.assertEqual(socket_appearance({"on": True, "power_w": 2}, online=True), SocketAppearance.ON_LOADED)
        self.assertEqual(socket_appearance({"on": True, "power_w": 45}, online=True), SocketAppearance.ON_LOADED)

    def test_unknown_never_implies_a_plug(self):
        for reading, online in [
            (None, True), ({}, True), ({"on": True}, True),
            ({"on": True, "power_w": float("nan")}, True),
            ({"on": True, "power_w": 45}, False),
        ]:
            self.assertEqual(socket_appearance(reading, online=online), SocketAppearance.UNKNOWN)

    def test_configurable_threshold(self):
        self.assertEqual(socket_appearance({"on": True, "power_w": 0.6}, online=True, threshold_w=0.5), SocketAppearance.ON_LOADED)
        with self.assertRaises(ValueError):
            socket_appearance({"on": True, "power_w": 1}, online=True, threshold_w=-1)


if __name__ == "__main__":
    unittest.main()
