import json
import tempfile
import unittest
from pathlib import Path

from websockets.asyncio.client import connect

from nxxt_level.group import Member
from nxxt_level.group_service import PersistentGroupService
from nxxt_level.group_store import GroupStore
from nxxt_level.pairing import CredentialStore
from nxxt_level.sync.hub import StateHub
from nxxt_level.sync.websocket_server import serve_sync


class TestWebSocketPairing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = str(Path(self.temp.name) / "state.sqlite3")
        self.store = GroupStore(db_path)
        self.credentials = CredentialStore(db_path)
        self.hub = StateHub()
        self.groups = await PersistentGroupService.open("home", self.store, self.hub)
        token = await self.groups.bootstrap_first_member(
            Member("main-pc", "Main PC", "windows"), self.credentials
        )
        self.assertTrue(self.credentials.authenticate("main-pc", token))
        await self.groups.set_member_online("main-pc", True)
        await self.groups.claim_sudo("main-pc")
        self.invite = await self.groups.create_pairing_invite("main-pc", self.credentials)
        self.server = await serve_sync(
            self.hub, self.credentials, "127.0.0.1", 0,
            command_handler=None, group_service=self.groups,
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        self.temp.cleanup()

    async def test_invitation_handshake_registers_member_and_returns_token(self):
        async with connect(f"ws://127.0.0.1:{self.port}") as ws:
            await ws.send(json.dumps({
                "type": "pair",
                "pairing_code": self.invite,
                "member": {
                    "member_id": "arch-laptop",
                    "display_name": "Arch Laptop",
                    "platform": "linux",
                    "capabilities": ["battery_monitoring"],
                },
            }))
            response = json.loads(await ws.recv())
        self.assertTrue(response["ok"])
        self.assertEqual(response["member_id"], "arch-laptop")
        self.assertTrue(self.credentials.authenticate("arch-laptop", response["token"]))
        self.assertIn("arch-laptop", self.groups.group.members)
        self.assertFalse(self.groups.group.members["arch-laptop"].online)

    async def test_invitation_is_single_use(self):
        async with connect(f"ws://127.0.0.1:{self.port}") as ws:
            await ws.send(json.dumps({
                "type": "pair", "pairing_code": self.invite,
                "member": {
                    "member_id": "first-laptop", "display_name": "First Laptop",
                    "platform": "linux", "capabilities": [],
                },
            }))
            first = json.loads(await ws.recv())
        self.assertTrue(first["ok"])

        async with connect(f"ws://127.0.0.1:{self.port}") as ws:
            await ws.send(json.dumps({
                "type": "pair", "pairing_code": self.invite,
                "member": {
                    "member_id": "second-laptop", "display_name": "Second Laptop",
                    "platform": "linux", "capabilities": [],
                },
            }))
            second = json.loads(await ws.recv())
        self.assertFalse(second["ok"])
