"""Group membership, manual Sudo ownership, and shared strip labels.

This module is a domain model only. Persistence and authenticated network
commands are deliberately separate so a disconnected client cannot claim Sudo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set
import re


class GroupError(ValueError):
    """Invalid group operation."""


@dataclass
class Member:
    member_id: str
    display_name: str
    platform: str
    capabilities: Set[str] = field(default_factory=set)
    online: bool = False
    assigned_outlets: Dict[str, Set[int]] = field(default_factory=dict)
    charger_assignments: Dict[str, int] = field(default_factory=dict)


@dataclass
class Strip:
    strip_id: str
    display_name: str
    outlet_names: Dict[int, str] = field(default_factory=lambda: {
        channel: f"Outlet {channel}" for channel in range(1, 5)
    })
    device_mac: Optional[str] = None


class GroupRegistry:
    """In-memory source of truth for one Nxxt group."""

    def __init__(self, group_id: str) -> None:
        if not group_id.strip():
            raise GroupError("group_id cannot be empty")
        self.group_id = group_id
        self.members: Dict[str, Member] = {}
        self.strips: Dict[str, Strip] = {}
        self.sudo_member_id: Optional[str] = None
        self.revision = 0
        self.push_notifications_enabled = True

    def _changed(self) -> None:
        self.revision += 1

    def add_member(self, member: Member) -> None:
        if not member.member_id or member.member_id in self.members:
            raise GroupError("member ID is empty or already registered")
        self.members[member.member_id] = member
        self._changed()

    def set_member_online(self, member_id: str, online: bool) -> None:
        self._require_member(member_id).online = bool(online)
        self._changed()

    def remove_member(self, member_id: str) -> None:
        self._require_member(member_id)
        if self.sudo_member_id == member_id:
            raise GroupError("Sudo must be explicitly released before removal")
        del self.members[member_id]
        self._changed()

    def claim_sudo(self, member_id: str) -> None:
        member = self._require_member(member_id)
        if not member.online:
            raise GroupError("Only an online member can claim Sudo")
        if self.sudo_member_id not in (None, member_id):
            raise GroupError("Sudo is already held; release or transfer it explicitly")
        self.sudo_member_id = member_id
        self._changed()

    def release_sudo(self, member_id: str) -> None:
        if self.sudo_member_id != member_id:
            raise GroupError("Only the current Sudo can release this role")
        self.sudo_member_id = None
        self._changed()

    def add_strip(self, strip: Strip) -> None:
        if not strip.strip_id or strip.strip_id in self.strips:
            raise GroupError("Strip ID is empty or already registered")
        self.strips[strip.strip_id] = strip
        self._changed()

    def rename_strip(self, strip_id: str, name: str) -> None:
        self._require_name(name)
        self._require_strip(strip_id).display_name = name.strip()
        self._changed()

    def rename_outlet(self, strip_id: str, channel: int, name: str) -> None:
        if channel not in range(1, 5):
            raise GroupError("Outlet channel must be between 1 and 4")
        self._require_name(name)
        self._require_strip(strip_id).outlet_names[channel] = name.strip()
        self._changed()

    def assign_charger(self, member_id: str, strip_id: str, channel: int) -> None:
        """Pair one member laptop with the physical outlet used by its charger."""
        member = self._require_member(member_id)
        if strip_id not in self.strips or channel not in range(1, 5):
            raise GroupError("Unknown strip or invalid outlet channel")
        for other_id, other in self.members.items():
            if other_id != member_id and other.charger_assignments.get(strip_id) == channel:
                raise GroupError("This outlet is already assigned to another device")
        member.charger_assignments[strip_id] = channel
        self._changed()

    def unassign_charger(self, member_id: str, strip_id: str) -> None:
        member = self._require_member(member_id)
        if strip_id not in member.charger_assignments:
            raise GroupError("No charger assignment exists for this member and strip")
        del member.charger_assignments[strip_id]
        self._changed()

    def set_push_notifications(self, enabled: bool, actor_member_id: str) -> None:
        """Only current Sudo may change the group notification setting."""
        if actor_member_id != self.sudo_member_id:
            raise GroupError("Only Sudo can change push notification settings")
        self.push_notifications_enabled = bool(enabled)
        self._changed()

    def notification_recipients(self) -> list:
        """Push notifications are delivered only to the current Sudo."""
        if not self.push_notifications_enabled or self.sudo_member_id is None:
            return []
        return [self.sudo_member_id]

    def build_battery_event(self, member_id: str, strip_id: str, battery_percent: int,
                            action: str) -> dict:
        """Build a truthful automation event using the member/outlet pairing.

        action is "charger_on" or "charger_off"; the caller must invoke this
        only after the corresponding relay state has been confirmed.
        """
        member = self._require_member(member_id)
        if "battery_monitoring" not in member.capabilities:
            raise GroupError("Battery monitoring is not available for this member")
        if strip_id not in member.charger_assignments:
            raise GroupError("No charger outlet is assigned to this member")
        if isinstance(battery_percent, bool) or not 0 <= battery_percent <= 100:
            raise GroupError("Battery percentage must be between 0 and 100")
        if action not in ("charger_on", "charger_off"):
            raise GroupError("Unsupported battery automation action")
        channel = member.charger_assignments[strip_id]
        strip = self._require_strip(strip_id)
        outlet_name = strip.outlet_names[channel]
        laptop_name = member.display_name
        verb = "switched on" if action == "charger_on" else "switched off"
        return {
            "type": "battery_automation",
            "member_id": member_id,
            "strip_id": strip_id,
            "strip_name": strip.display_name,
            "outlet": channel,
            "outlet_name": outlet_name,
            "battery_percent": battery_percent,
            "action": action,
            "message": (f"{laptop_name} battery is at {battery_percent}%. "
                        f"Automated assistant {verb} {outlet_name} on {strip.display_name}."),
            "recipients": self.notification_recipients(),
        }

    def can_control_outlet(self, member_id: str, strip_id: str, channel: int) -> bool:
        member = self._require_member(member_id)
        if strip_id not in self.strips or channel not in range(1, 5):
            return False
        if member_id == self.sudo_member_id:
            return True
        return channel in member.assigned_outlets.get(strip_id, set())

    def _require_member(self, member_id: str) -> Member:
        try:
            return self.members[member_id]
        except KeyError as exc:
            raise GroupError("Unknown group member") from exc

    def _require_strip(self, strip_id: str) -> Strip:
        try:
            return self.strips[strip_id]
        except KeyError as exc:
            raise GroupError("Unknown strip") from exc

    @staticmethod
    def _require_name(name: str) -> None:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 64:
            raise GroupError("Names must contain 1 to 64 characters")
