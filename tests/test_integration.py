"""Integration tests simulating MTTL-W01 strip network lifecycle and transactions."""

import asyncio
import unittest

from nxxt_level.device.provisioning import provision_strip, validate_provision_params
from nxxt_level.device.server import StripDeviceServer


class TestDeviceIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Create server on localhost with dynamic port
        self.server = StripDeviceServer(bind_host="127.0.0.1", port=0, poll_interval=100.0)
        await self.server.start()
        # Retrieve allocated ephemeral port
        self.server_port = self.server._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.server.stop()

    async def test_full_strip_session_lifecycle(self):
        strip_reader, strip_writer = await asyncio.open_connection("127.0.0.1", self.server_port)

        relay_states = {1: False, 2: False, 3: False, 4: False}

        def build_mock_getinfo() -> str:
            records = []
            for n in range(1, 5):
                relay = "on" if relay_states[n] else "off"
                state = 1 if relay_states[n] else 0
                power = 42000 if relay_states[n] else 0
                records.append(
                    f"{n}:1000;{relay};{state};0;0;{power};00000010;00000000;00000000;0;00;30"
                )
            # Channel 5 aggregate
            tot_p = sum(42000 for r in relay_states.values() if r)
            records.append(f"5:1000;on;1;0;0;{tot_p};00000040;00000000;00000000;0;00;30")
            return "up:getinfo:" + ":".join(records) + "\r\n"

        async def mock_strip_loop():
            try:
                while True:
                    line_bytes = await strip_reader.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode("ascii", errors="replace").strip()
                    if line == "up:getinfo:all":
                        strip_writer.write(build_mock_getinfo().encode("ascii"))
                        await strip_writer.drain()
                    elif line.startswith("up:onoff:"):
                        _, _, ch_s, state_s = line.split(":")
                        ch = int(ch_s)
                        relay_states[ch] = (state_s == "on")
                        ack = f"up:onoff:{ch}:{state_s}\r\n"
                        strip_writer.write(ack.encode("ascii"))
                        await strip_writer.drain()
                    elif line == "up:power_report:1:vol":
                        strip_writer.write(b"up:power_report:1:221000\r\n")
                        await strip_writer.drain()
                    elif line == "up:query:wifirssi":
                        strip_writer.write(b"up:query:-58\r\n")
                        await strip_writer.drain()
            except asyncio.CancelledError:
                pass

        mock_task = asyncio.create_task(mock_strip_loop())

        try:
            # 1. Strip connects and sends bootinfo
            boot_frame = b"up:bootinfo:lgutap;AABBCCDDEEFF;AABBCCDDEEFF;0.1.54-1.0.66;connect\r\n"
            strip_writer.write(boot_frame)
            await strip_writer.drain()

            # Wait briefly for server to process initial boot & auto-query
            await asyncio.sleep(0.3)

            session = self.server.get_session("AABBCCDDEEFF")
            self.assertIsNotNone(session)
            self.assertTrue(session.is_active)
            self.assertEqual(session.state.mac, "AABBCCDDEEFF")
            self.assertEqual(session.state.firmware, "0.1.54-1.0.66")
            self.assertEqual(session.state.voltage_v, 221.0)
            self.assertEqual(session.state.rssi_dbm, -58)

            # 2. Command outlet 2 ON
            ok = await session.set_outlet(2, True, settle_delay=0.1)
            self.assertTrue(ok)
            self.assertTrue(session.state.outlets[2].is_on)
            self.assertTrue(session.state.outlets[2].has_meaningful_load)
            self.assertEqual(session.state.outlets[2].power_w, 42.0)

            # 3. Command ALL outlets OFF
            ok_all = await session.set_all_outlets(False, settle_delay=0.1)
            self.assertTrue(ok_all)
            self.assertFalse(session.state.is_any_outlet_on)

            # 4. Unsolicited physical button event from strip
            strip_writer.write(b"up:event:onoff:3:on\r\n")
            await strip_writer.drain()
            await asyncio.sleep(0.2)
            self.assertTrue(session.state.outlets[3].is_on)

            # Master button press event (turns all on)
            strip_writer.write(b"up:event:onoff:0:on\r\n")
            await strip_writer.drain()
            await asyncio.sleep(0.2)
            self.assertTrue(session.state.all_outlets_on)

        finally:
            mock_task.cancel()
            strip_writer.close()
            await strip_writer.wait_closed()


class TestProvisioningValidation(unittest.TestCase):
    def test_parameter_validation(self):
        # Valid parameters
        validate_provision_params("My24GhzNet", "SuperSecret123", "192.168.1.100")

        # Empty SSID
        with self.assertRaises(ValueError):
            validate_provision_params("", "Pass1234", "192.168.1.100")

        # Forbidden delimiter in SSID
        with self.assertRaises(ValueError):
            validate_provision_params("My:Net", "Pass1234", "192.168.1.100")

        # Forbidden newline in Password
        with self.assertRaises(ValueError):
            validate_provision_params("MyNet", "Pass\n1234", "192.168.1.100")

        # Invalid IP
        with self.assertRaises(ValueError):
            validate_provision_params("MyNet", "Pass1234", "999.999.999.999")

        # Loopback IP rejected
        with self.assertRaises(ValueError):
            validate_provision_params("MyNet", "Pass1234", "127.0.0.1")

    def test_dry_run_execution(self):
        res = provision_strip(
            ssid="ValidSSID",
            password="ValidPassword",
            server_ip="192.168.1.50",
            dry_run=True,
        )
        self.assertEqual(res["status"], "dry_run_success")
        self.assertEqual(res["configured_controller_ip"], "192.168.1.50")
        self.assertEqual(res["configured_wifi_ssid"], "ValidSSID")


if __name__ == "__main__":
    unittest.main()
