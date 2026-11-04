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


@dataclass
class Strip:
    strip_id: str
    display_name: str
    outlet_names: Dict[int, str] = field(default_factory=lambda: {
        channel: f"Outlet {channel}" for channel in range(1, 5)
    })


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
