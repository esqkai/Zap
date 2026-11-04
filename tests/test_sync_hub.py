"""Transport-independent real-time state hub tests."""
import asyncio
import unittest

from nxxt_level.sync.hub import StateHub


class TestStateHub(unittest.IsolatedAsyncioTestCase):
    async def test_two_clients_receive_same_revisions(self):
        hub = StateHub()
        win = await hub.subscribe()
        linux = await hub.subscribe()
        self.assertEqual((await win.queue.get())["revision"], 0)
        self.assertEqual((await linux.queue.get())["revision"], 0)
        await hub.publish("devices", "strip1", {"outlet_1": True})
        a, b = await win.queue.get(), await linux.queue.get()
        self.assertEqual(a, b)
        self.assertEqual(a["revision"], 1)
        self.assertTrue(a["value"]["outlet_1"])

    async def test_reconnect_receives_latest_snapshot(self):
        hub = StateHub()
        old = await hub.subscribe()
        await old.queue.get()
        await hub.publish("devices", "strip1", {"online": True})
        await hub.unsubscribe(old)
        new = await hub.subscribe()
        snapshot = await new.queue.get()
        self.assertEqual(snapshot["revision"], 1)
        self.assertTrue(snapshot["state"]["devices"]["strip1"]["online"])

    async def test_external_mutation_cannot_modify_state(self):
        hub = StateHub()
        payload = {"outlets": [True]}
        await hub.publish("devices", "strip1", payload)
        payload["outlets"][0] = False
        snapshot = await hub.snapshot()
        self.assertTrue(snapshot["state"]["devices"]["strip1"]["outlets"][0])

    async def test_revisions_are_monotonic_under_concurrency(self):
        hub = StateHub()
        await asyncio.gather(*(hub.publish("devices", str(i), i) for i in range(25)))
        self.assertEqual((await hub.snapshot())["revision"], 25)
