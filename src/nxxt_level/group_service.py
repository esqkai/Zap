"""Persist group changes before publishing them to connected clients."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from nxxt_level.group import GroupRegistry
from nxxt_level.group_store import GroupStore
from nxxt_level.sync.hub import StateHub


class PersistentGroupService:
    """Single-writer service coordinating group model, SQLite and live snapshots.

    All public mutation methods commit to SQLite before publishing. If the
    database write fails, clients are not told that the change succeeded.
    """

    def __init__(self, group: GroupRegistry, store: GroupStore, hub: StateHub) -> None:
        self.group = group
        self.store = store
        self.hub = hub
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, group_id: str, store: GroupStore, hub: StateHub):
        group = await asyncio.to_thread(store.load, group_id)
        if group is None:
            group = GroupRegistry(group_id)
            await asyncio.to_thread(store.save, group)
        service = cls(group, store, hub)
        await hub.publish("groups", group_id, service.snapshot())
        return service

    def snapshot(self) -> dict:
        group = self.group
        return {
            "group_id": group.group_id,
            "revision": group.revision,
            "sudo_member_id": group.sudo_member_id,
            "push_notifications_enabled": group.push_notifications_enabled,
            "members": {
                member_id: {
                    "display_name": member.display_name,
                    "platform": member.platform,
                    "capabilities": sorted(member.capabilities),
                    "online": member.online,
                    "assigned_outlets": {
                        strip_id: sorted(channels)
                        for strip_id, channels in member.assigned_outlets.items()
                    },
                    "charger_assignments": dict(member.charger_assignments),
                }
                for member_id, member in group.members.items()
            },
            "strips": {
                strip_id: {
                    "display_name": strip.display_name,
                    "outlet_names": dict(strip.outlet_names),
                }
                for strip_id, strip in group.strips.items()
            },
        }

    async def _mutate(self, operation: Callable[..., Any], *args: Any) -> dict:
        async with self._lock:
            # Save a rollback copy so failed persistence cannot leave memory ahead.
            import copy
            previous = copy.deepcopy(self.group)
            operation(*args)
            try:
                await asyncio.to_thread(self.store.save, self.group)
            except Exception:
                self.group = previous
                raise
            await self.hub.publish("groups", self.group.group_id, self.snapshot())
            return self.snapshot()

    async def add_member(self, member) -> dict:
        return await self._mutate(self.group.add_member, member)

    async def set_member_online(self, member_id: str, online: bool) -> dict:
        return await self._mutate(self.group.set_member_online, member_id, online)

    async def remove_member(self, member_id: str) -> dict:
        return await self._mutate(self.group.remove_member, member_id)

    async def claim_sudo(self, member_id: str) -> dict:
        return await self._mutate(self.group.claim_sudo, member_id)

    async def release_sudo(self, member_id: str) -> dict:
        return await self._mutate(self.group.release_sudo, member_id)

    async def add_strip(self, strip) -> dict:
        return await self._mutate(self.group.add_strip, strip)

    async def rename_strip(self, strip_id: str, name: str) -> dict:
        return await self._mutate(self.group.rename_strip, strip_id, name)

    async def rename_outlet(self, strip_id: str, channel: int, name: str) -> dict:
        return await self._mutate(self.group.rename_outlet, strip_id, channel, name)

    async def assign_charger(self, member_id: str, strip_id: str, channel: int) -> dict:
        return await self._mutate(self.group.assign_charger, member_id, strip_id, channel)

    async def unassign_charger(self, member_id: str, strip_id: str) -> dict:
        return await self._mutate(self.group.unassign_charger, member_id, strip_id)

    async def set_push_notifications(self, enabled: bool, actor_member_id: str) -> dict:
        return await self._mutate(
            self.group.set_push_notifications, enabled, actor_member_id
        )
