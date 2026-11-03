"""Unit tests for device state management, telemetry accumulation, and load detection."""

import unittest

from nxxt_level.device.protocol import (
    BootInfo,
    ButtonEvent,
    OutletAck,
    OutletReading,
    PowerReport,
    SignalReport,
)
from nxxt_level.device.state import OutletState, PowerStripState


class TestOutletState(unittest.TestCase):
    def test_meaningful_load_detection(self):
        outlet = OutletState(channel=1, is_on=False, power_w=0.0)
        self.assertFalse(outlet.has_meaningful_load)

        # On, but power is below 2.0 W threshold (e.g. idle phantom power)
        outlet.is_on = True
        outlet.power_w = 0.5
        self.assertFalse(outlet.has_meaningful_load)

        # On, and power reaches 45.0 W (e.g. active laptop charger load)
        outlet.power_w = 45.0
        self.assertTrue(outlet.has_meaningful_load)

        # Off, even if power reading was residual
        outlet.is_on = False
        self.assertFalse(outlet.has_meaningful_load)


class TestPowerStripState(unittest.TestCase):
    def setUp(self):
        self.state = PowerStripState(mac="88D0391C0C4C")

    def test_bootinfo_application(self):
        boot = BootInfo(
            model="lgutap",
            primary_mac="88D0391C0C4C",
            secondary_mac="88D0391C0C4C",
            firmware_version="0.1.54-1.0.66",
        )
        self.state.apply_bootinfo(boot, "192.168.1.120")
        self.assertTrue(self.state.is_online)
        self.assertEqual(self.state.model, "lgutap")
        self.assertEqual(self.state.firmware, "0.1.54-1.0.66")
        self.assertEqual(self.state.ip_address, "192.168.1.120")

    def test_telemetry_and_totals(self):
        readings = [
            OutletReading(channel=1, is_on=True, runtime_seconds=100, raw_state=1,
                          overload_flag="0", overheat_flag="0", power_w=50.0, energy_kwh=1.2, temp_c=30),
            OutletReading(channel=2, is_on=True, runtime_seconds=200, raw_state=1,
                          overload_flag="0", overheat_flag="0", power_w=150.0, energy_kwh=2.3, temp_c=32),
            OutletReading(channel=3, is_on=False, runtime_seconds=0, raw_state=0,
                          overload_flag="0", overheat_flag="0", power_w=0.0, energy_kwh=0.5, temp_c=28),
            OutletReading(channel=4, is_on=False, runtime_seconds=0, raw_state=0,
                          overload_flag="0", overheat_flag="0", power_w=0.0, energy_kwh=0.1, temp_c=27),
        ]
        self.state.apply_readings(readings)

        self.assertEqual(self.state.total_power_w, 200.0)
        self.assertEqual(self.state.total_energy_kwh, 4.1)
        self.assertTrue(self.state.is_any_outlet_on)
        self.assertFalse(self.state.all_outlets_on)

        # Set voltage and check estimated current: 200W / 220V = 0.91A
        self.state.apply_power_report(PowerReport(channel=1, raw_value=220000, voltage_v=220.0))
        self.assertEqual(self.state.voltage_v, 220.0)
        self.assertEqual(self.state.estimated_current_a, 0.91)

    def test_button_events(self):
        # Individual button press
        self.state.apply_button_event(ButtonEvent(channel=1, is_on=True))
        self.assertTrue(self.state.outlets[1].is_on)
        self.assertFalse(self.state.outlets[2].is_on)

        # Master button press turns all ON
        self.state.apply_button_event(ButtonEvent(channel=0, is_on=True))
        for ch in range(1, 5):
            self.assertTrue(self.state.outlets[ch].is_on)

        # Master button press turns all OFF
        self.state.apply_button_event(ButtonEvent(channel=0, is_on=False))
        for ch in range(1, 5):
            self.assertFalse(self.state.outlets[ch].is_on)

    def test_signal_and_acks(self):
        self.state.apply_signal_report(SignalReport(rssi_dbm=-62))
        self.assertEqual(self.state.rssi_dbm, -62)

        self.state.apply_outlet_ack(OutletAck(channel=3, is_on=True))
        self.assertTrue(self.state.outlets[3].is_on)

    def test_terminal_summary_formatting(self):
        summary = self.state.format_terminal_summary()
        self.assertIn("Zap Strip:", summary)
        self.assertIn("88D0391C0C4C", summary)
        self.assertIn("Relay", summary)


if __name__ == "__main__":
    unittest.main()
