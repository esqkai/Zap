import tempfile
import unittest
from pathlib import Path

from nxxt_level.group import Member, Strip
from nxxt_level.group_service import PersistentGroupService
from nxxt_level.group_store import GroupStore
from nxxt_level.sync.commands import CommandError, GroupCommandHandler
from nxxt_level.sync.hub import StateHub


class FakeSession:
    is_active = True

    def __init__(self, confirmed=True):
        self.confirmed = confirmed
        self.calls = []

    async def set_outlet(self, channel, on):
        self.calls.append((channel, on))
        return self.confirmed


class FakeDevices:
    def __init__(self, session):
        self.session = session

    def get_session(self, mac):
        return self.session if mac == "AA:BB:CC:DD:EE:FF" else None


class TestGroupCommandHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = GroupStore(str(Path(self.temp.name) / "groups.sqlite3"))
        self.groups = await PersistentGroupService.open("home", self.store, StateHub())
        await self.groups.add_member(Member("pc", "Windows PC", "windows"))
        await self.groups.add_member(Member("laptop", "Arch Laptop", "linux"))
        await self.groups.set_member_online("pc", True)
        await self.groups.set_member_online("laptop", True)
        await self.groups.add_strip(Strip("living-room", "Living Room"))
        await self.groups.claim_sudo("pc")
        self.session = FakeSession()
        self.handler = GroupCommandHandler(self.groups, FakeDevices(self.session))

    async def asyncTearDown(self):
        self.temp.cleanup()


    async def test_sudo_can_register_new_strip_but_endpoint_cannot(self):
        await self.handler.handle("pc", {
            "command": "register_strip", "strip_id": "bedroom", "name": "Bedroom Strip",
        })
        self.assertIn("bedroom", self.groups.group.strips)
        with self.assertRaises(CommandError):
            await self.handler.handle("laptop", {
                "command": "register_strip", "strip_id": "garage", "name": "Garage Strip",
            })

    async def test_sudo_can_bind_strip_and_rename_outlet(self):
        await self.handler.handle("pc", {
            "command": "bind_strip_device", "strip_id": "living-room",
            "device_mac": "AA:BB:CC:DD:EE:FF",
        })
        await self.handler.handle("pc", {
            "command": "rename_outlet", "strip_id": "living-room",
            "channel": 2, "name": "Laptop Charger",
        })
        strip = self.groups.group.strips["living-room"]
        self.assertEqual(strip.device_mac, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(strip.outlet_names[2], "Laptop Charger")

    async def test_endpoint_cannot_rename_or_bind_strip(self):
        with self.assertRaises(CommandError):
            await self.handler.handle("laptop", {
                "command": "rename_strip", "strip_id": "living-room", "name": "Hack",
            })
        with self.assertRaises(CommandError):
            await self.handler.handle("laptop", {
                "command": "bind_strip_device", "strip_id": "living-room",
                "device_mac": "AA:BB:CC:DD:EE:FF",
            })

    async def test_endpoint_can_only_switch_assigned_outlet(self):
        await self.groups._mutate(
            lambda: self.groups.group.members["laptop"].assigned_outlets.update(
                {"living-room": {2}}
            )
        )
        await self.groups._mutate(lambda: self.groups.group.strips["living-room"].__setattr__(
            "device_mac", "AA:BB:CC:DD:EE:FF"
        ))
        result = await self.handler.handle("laptop", {
            "command": "set_outlet", "strip_id": "living-room",
            "channel": 2, "on": True,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(self.session.calls, [(2, True)])
        with self.assertRaises(CommandError):
            await self.handler.handle("laptop", {
                "command": "set_outlet", "strip_id": "living-room",
                "channel": 1, "on": True,
            })

    async def test_relay_timeout_or_missing_binding_is_not_success(self):
        await self.handler.handle("pc", {
            "command": "bind_strip_device", "strip_id": "living-room",
            "device_mac": "AA:BB:CC:DD:EE:FF",
        })
        self.session.confirmed = False
        with self.assertRaises(CommandError):
            await self.handler.handle("pc", {
                "command": "set_outlet", "strip_id": "living-room",
                "channel": 1, "on": True,
            })


    async def test_sudo_can_assign_charger_and_endpoint_can_control_only_that_outlet(self):
        await self.handler.handle("pc", {
            "command": "assign_charger", "member_id": "laptop",
            "strip_id": "living-room", "channel": 3,
        })
        await self.handler.handle("pc", {
            "command": "bind_strip_device", "strip_id": "living-room",
            "device_mac": "AA:BB:CC:DD:EE:FF",
        })
        result = await self.handler.handle("laptop", {
            "command": "set_outlet", "strip_id": "living-room",
            "channel": 3, "on": True,
        })
        self.assertTrue(result["ok"])
        with self.assertRaises(CommandError):
            await self.handler.handle("laptop", {
                "command": "set_outlet", "strip_id": "living-room",
                "channel": 2, "on": True,
            })

    async def test_only_sudo_can_change_notification_preference(self):
        await self.handler.handle("pc", {
            "command": "set_push_notifications", "enabled": False,
        })
        self.assertFalse(self.groups.group.push_notifications_enabled)
        with self.assertRaises(CommandError):
            await self.handler.handle("laptop", {
                "command": "set_push_notifications", "enabled": True,
            })

    async def test_sudo_can_create_pairing_invite_only_when_credentials_available(self):
        from nxxt_level.pairing import CredentialStore
        credentials = CredentialStore(str(Path(self.temp.name) / "credentials.sqlite3"))
        self.handler.credentials = credentials
        result = await self.handler.handle("pc", {"command": "create_pairing_invite"})
        self.assertTrue(result["pairing_code"])
        with self.assertRaises(CommandError):
            await self.handler.handle("laptop", {"command": "create_pairing_invite"})


    async def test_online_endpoint_can_manually_claim_when_previous_sudo_is_offline(self):
        await self.groups.set_member_online("pc", False)
        await self.handler.handle("laptop", {"command": "claim_sudo"})
        self.assertEqual(self.groups.group.sudo_member_id, "laptop")

    async def test_sudo_role_is_exclusive_and_manual(self):
        await self.handler.handle("pc", {"command": "release_sudo"})
        # Once Sudo is vacant, any online Endpoint may explicitly claim it.
        await self.handler.handle("laptop", {"command": "claim_sudo"})
        self.assertEqual(self.groups.group.sudo_member_id, "laptop")
        with self.assertRaises(CommandError):
            await self.handler.handle("pc", {"command": "claim_sudo"})
