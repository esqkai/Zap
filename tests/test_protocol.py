"""Unit tests for protocol parsing, serialization, and hardware quirks."""

import unittest

from nxxt_level.device.protocol import (
    BootInfo,
    ButtonEvent,
    OutletAck,
    OutletReading,
    PowerReport,
    SignalReport,
    build_getinfo_all,
    build_outlet_command,
    build_provision_connect_command,
    build_provision_ip_command,
    build_rssi_query,
    build_voltage_query,
    clean_raw_line,
    parse_bootinfo,
    parse_button_event,
    parse_getinfo,
    parse_line,
    parse_onoff_ack,
    parse_power_report,
    parse_rssi_query,
)


class TestProtocolCleanRawLine(unittest.TestCase):
    def test_null_byte_stripping(self):
        raw = b"\x00\x00up:query:-55\r\n\x00"
        self.assertEqual(clean_raw_line(raw), "up:query:-55")

    def test_string_cleaning(self):
        text = "  \x00up:onoff:1:on\r\n  "
        self.assertEqual(clean_raw_line(text), "up:onoff:1:on")

    def test_utf8_replacement(self):
        bad_bytes = b"up:test:\xff\xfe\r\n"
        cleaned = clean_raw_line(bad_bytes)
        self.assertTrue(cleaned.startswith("up:test:"))


class TestProtocolBuilders(unittest.TestCase):
    def test_build_outlet_command_valid(self):
        self.assertEqual(build_outlet_command(1, True), b"up:onoff:1:on\r\n")
        self.assertEqual(build_outlet_command(4, False), b"up:onoff:4:off\r\n")

    def test_build_outlet_command_invalid(self):
        with self.assertRaises(ValueError):
            build_outlet_command(0, True)
        with self.assertRaises(ValueError):
            build_outlet_command(5, False)

    def test_queries(self):
        self.assertEqual(build_getinfo_all(), b"up:getinfo:all\r\n")
        self.assertEqual(build_voltage_query(), b"up:power_report:1:vol\r\n")
        self.assertEqual(build_rssi_query(), b"up:query:wifirssi\r\n")

    def test_build_provision_ip_command(self):
        self.assertEqual(build_provision_ip_command("192.168.1.50"), b"up:ip:192.168.1.50\r\n")
        with self.assertRaises(ValueError):
            build_provision_ip_command("not_an_ip")

    def test_build_provision_connect_command(self):
        cmd = build_provision_connect_command("HomeWiFi", "SecretPass")
        self.assertEqual(cmd, b"up:connect:HomeWiFi:SecretPass\r\n")

    def test_build_provision_connect_command_invalid(self):
        with self.assertRaises(ValueError):
            build_provision_connect_command("WiFi:Bad", "Pass")
        with self.assertRaises(ValueError):
            build_provision_connect_command("WiFi", "Pass\nNewline")


class TestProtocolParsers(unittest.TestCase):
    def test_parse_bootinfo(self):
        line = "up:bootinfo:lgutap;88D0391C0C4C;88D0391C0C4C;0.1.54-1.0.66;connect"
        res = parse_bootinfo(line)
        self.assertIsNotNone(res)
        self.assertEqual(res.model, "lgutap")
        self.assertEqual(res.primary_mac, "88D0391C0C4C")
        self.assertEqual(res.firmware_version, "0.1.54-1.0.66")

    def test_parse_bootinfo_invalid(self):
        self.assertIsNone(parse_bootinfo("up:bootinfo:malformed;connect"))

    def test_parse_getinfo(self):
        # Sample synthetic getinfo string representing 4 outlets and 1 aggregate
        line = (
            "up:getinfo:"
            "1:1234;on;1;0;0;5300;0000000A;00000000;00000000;0;00;31:"
            "2:5678;off;0;0;0;0;00000000;00000000;00000000;0;00;29:"
            "3:9012;on;1;0;0;125000;00000100;00000000;00000000;0;00;35:"
            "4:3456;off;0;0;0;0;00000005;00000000;00000000;0;00;28:"
            "5:9999;on;1;0;0;130300;0000010F;00000000;00000000;0;00;31"
        )
        readings = parse_getinfo(line)
        self.assertEqual(len(readings), 5)

        # Channel 1 checks
        r1 = readings[0]
        self.assertEqual(r1.channel, 1)
        self.assertTrue(r1.is_on)
        self.assertEqual(r1.power_w, 5.30)
        self.assertEqual(r1.energy_kwh, 0.010)
        self.assertEqual(r1.temp_c, 31)
        self.assertFalse(r1.is_aggregate)

        # Channel 2 checks
        r2 = readings[1]
        self.assertEqual(r2.channel, 2)
        self.assertFalse(r2.is_on)
        self.assertEqual(r2.power_w, 0.0)

        # Channel 3 checks
        r3 = readings[2]
        self.assertEqual(r3.channel, 3)
        self.assertEqual(r3.power_w, 125.0)
        self.assertEqual(r3.energy_kwh, 0.256)

        # Channel 5 aggregate check
        r5 = readings[4]
        self.assertEqual(r5.channel, 5)
        self.assertTrue(r5.is_aggregate)

    def test_parse_power_report_voltage(self):
        line = "up:power_report:1:224500"
        rep = parse_power_report(line)
        self.assertIsNotNone(rep)
        self.assertEqual(rep.voltage_v, 224.5)
        self.assertIsNone(rep.current_ma)

    def test_parse_power_report_current(self):
        line = "up:power_report:2:450"
        rep = parse_power_report(line)
        self.assertIsNotNone(rep)
        self.assertIsNone(rep.voltage_v)
        self.assertEqual(rep.current_ma, 450)

    def test_parse_button_events(self):
        # Master button
        master_evt = parse_button_event("up:event:onoff:0:on")
        self.assertIsNotNone(master_evt)
        self.assertEqual(master_evt.channel, 0)
        self.assertTrue(master_evt.is_master_button)
        self.assertTrue(master_evt.is_on)

        # Outlet button
        o2_evt = parse_button_event("up:event:onoff:2:off")
        self.assertIsNotNone(o2_evt)
        self.assertEqual(o2_evt.channel, 2)
        self.assertFalse(o2_evt.is_master_button)
        self.assertFalse(o2_evt.is_on)

    def test_parse_rssi_query(self):
        res = parse_rssi_query("up:query:-68")
        self.assertIsNotNone(res)
        self.assertEqual(res.rssi_dbm, -68)

    def test_parse_onoff_ack(self):
        ack = parse_onoff_ack("up:onoff:3:on")
        self.assertIsNotNone(ack)
        self.assertEqual(ack.channel, 3)
        self.assertTrue(ack.is_on)

    def test_parse_line_dispatcher_resilience(self):
        # Malformed or unrecognized lines must return None without raising exceptions
        self.assertIsNone(parse_line(""))
        self.assertIsNone(parse_line("random gibberish"))
        self.assertIsNone(parse_line("up:unknown:protocol:stuff"))
        self.assertIsNone(parse_line(b"\x00\x00"))

        # Valid lines with null bytes handled cleanly
        msg = parse_line(b"\x00\x00up:event:onoff:1:on\r\n")
        self.assertIsInstance(msg, ButtonEvent)


if __name__ == "__main__":
    unittest.main()
