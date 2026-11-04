import asyncio

import pytest

from nxxt_level.group import Member, Strip
from nxxt_level.group_service import PersistentGroupService
from nxxt_level.group_store import GroupStore
from nxxt_level.sync.hub import StateHub


@pytest.mark.asyncio
async def test_group_mutations_are_persisted_before_live_broadcast(tmp_path):
    store = GroupStore(str(tmp_path / "groups.sqlite3"))
    hub = StateHub()
    service = await PersistentGroupService.open("home", store, hub)
    subscriber = await hub.subscribe()
    initial = await subscriber.queue.get()
    assert initial["state"]["groups"]["home"]["strips"] == {}

    await service.add_member(Member("laptop", "Arch Laptop", "linux"))
    await service.add_strip(Strip("strip-1", "Office Strip"))
    await service.rename_outlet("strip-1", 2, "Laptop Charger")

    # Every mutation publishes a complete group snapshot.
    events = [await subscriber.queue.get() for _ in range(3)]
    assert all(event["section"] == "groups" for event in events)
    assert events[-1]["value"]["strips"]["strip-1"]["outlet_names"][2] == "Laptop Charger"

    # A fresh service instance sees the committed state after restart.
    restored = await PersistentGroupService.open("home", store, StateHub())
    assert restored.group.strips["strip-1"].outlet_names[2] == "Laptop Charger"
    assert "laptop" in restored.group.members


@pytest.mark.asyncio
async def test_group_changes_are_not_broadcast_if_database_save_fails(tmp_path, monkeypatch):
    store = GroupStore(str(tmp_path / "groups.sqlite3"))
    hub = StateHub()
    service = await PersistentGroupService.open("home", store, hub)
    subscriber = await hub.subscribe()
    await subscriber.queue.get()  # initial snapshot

    def fail_save(group):
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "save", fail_save)
    with pytest.raises(OSError):
        await service.add_member(Member("laptop", "Arch Laptop", "linux"))

    assert "laptop" not in service.group.members
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(subscriber.queue.get(), timeout=0.01)
