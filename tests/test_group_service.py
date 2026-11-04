import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nxxt_level.group import Member, Strip
from nxxt_level.group_service import PersistentGroupService
from nxxt_level.group_store import GroupStore
from nxxt_level.pairing import CredentialStore
from nxxt_level.sync.hub import StateHub


class TestPersistentGroupService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "groups.sqlite3")
        self.store = GroupStore(self.db_path)
        self.credentials = CredentialStore(self.db_path)
        self.hub = StateHub()
        self.service = await PersistentGroupService.open("home", self.store, self.hub)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_group_mutations_persist_before_live_broadcast(self):
        subscriber = await self.hub.subscribe()
        initial = await subscriber.queue.get()
        self.assertEqual(initial["state"]["groups"]["home"]["strips"], {})

        await self.service.add_member(Member("laptop", "Arch Laptop", "linux"))
        await self.service.add_strip(Strip("strip-1", "Office Strip"))
        await self.service.rename_outlet("strip-1", 2, "Laptop Charger")

        events = [await subscriber.queue.get() for _ in range(3)]
        self.assertTrue(all(event["section"] == "groups" for event in events))
        self.assertEqual(
            events[-1]["value"]["strips"]["strip-1"]["outlet_names"][2],
            "Laptop Charger",
        )

        restored = await PersistentGroupService.open("home", self.store, StateHub())
        self.assertEqual(
            restored.group.strips["strip-1"].outlet_names[2], "Laptop Charger"
        )
        self.assertIn("laptop", restored.group.members)


    async def test_only_sudo_can_invite_and_new_member_is_persisted(self):
        from nxxt_level.group import Member
        await self.service.add_member(Member("sudo", "Main PC", "windows"))
        await self.service.set_member_online("sudo", True)
        await self.service.claim_sudo("sudo")
        invite = await self.service.create_pairing_invite("sudo", self.credentials)
        token = await self.service.redeem_pairing_invite(
            invite, Member("laptop", "Arch Laptop", "linux",
                           capabilities={"battery_monitoring"}),
            self.credentials,
        )
        self.assertTrue(self.credentials.authenticate("laptop", token))
        restored = await PersistentGroupService.open("home", self.store, StateHub())
        self.assertIn("laptop", restored.group.members)
        self.assertFalse(restored.group.members["laptop"].online)

    async def test_endpoint_cannot_issue_pairing_invitation(self):
        from nxxt_level.group import Member
        await self.service.add_member(Member("endpoint", "Laptop", "linux"))
        await self.service.set_member_online("endpoint", True)
        with self.assertRaises(ValueError):
            await self.service.create_pairing_invite("endpoint", self.credentials)

    async def test_failed_database_write_rolls_back_and_is_not_broadcast(self):
        subscriber = await self.hub.subscribe()
        await subscriber.queue.get()

        with patch.object(self.store, "save", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                await self.service.add_member(Member("laptop", "Arch Laptop", "linux"))

        self.assertNotIn("laptop", self.service.group.members)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(subscriber.queue.get(), timeout=0.01)
