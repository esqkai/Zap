"""Allow-listed authenticated group commands; no arbitrary remote execution."""
from __future__ import annotations

from typing import Any

from nxxt_level.group import GroupError, Strip


class CommandError(ValueError):
    pass


class GroupCommandHandler:
    def __init__(self, group_service: Any, device_server: Any, credentials: Any = None) -> None:
        self.groups = group_service
        self.devices = device_server
        self.credentials = credentials

    async def handle(self, member_id: str, message: dict) -> dict:
        if not isinstance(message, dict):
            raise CommandError("Command must be an object")
        command = message.get("command")
        group = self.groups.group

        if command == "create_pairing_invite":
            self._require_sudo(member_id)
            if self.credentials is None:
                raise CommandError("Pairing credentials are unavailable")
            ttl = message.get("ttl_seconds", 300)
            if isinstance(ttl, bool) or not isinstance(ttl, int):
                raise CommandError("ttl_seconds must be an integer")
            code = await self.groups.create_pairing_invite(member_id, self.credentials, ttl)
            return {"ok": True, "pairing_code": code, "expires_in": ttl}

        if command == "claim_sudo":
            try:
                await self.groups.claim_sudo(member_id)
            except GroupError as exc:
                raise CommandError(str(exc)) from exc
            return {"ok": True, "result": "sudo_claimed"}

        if command == "release_sudo":
            try:
                await self.groups.release_sudo(member_id)
            except GroupError as exc:
                raise CommandError(str(exc)) from exc
            return {"ok": True, "result": "sudo_released"}

        if command == "register_strip":
            self._require_sudo(member_id)
            strip_id = self._string(message, "strip_id")
            name = self._string(message, "name")
            await self.groups.add_strip(Strip(strip_id, name))
            return {"ok": True, "result": "strip_registered"}

        if command == "bind_strip_device":
            self._require_sudo(member_id)
            await self.groups.bind_strip_device(
                member_id, self._string(message, "strip_id"),
                self._string(message, "device_mac"),
            )
            return {"ok": True, "result": "strip_device_bound"}

        if command == "rename_strip":
            self._require_sudo(member_id)
            await self.groups.rename_strip(
                self._string(message, "strip_id"), self._string(message, "name")
            )
            return {"ok": True, "result": "strip_renamed"}

        if command == "rename_outlet":
            self._require_sudo(member_id)
            channel = message.get("channel")
            if isinstance(channel, bool) or not isinstance(channel, int):
                raise CommandError("channel must be an integer")
            await self.groups.rename_outlet(
                self._string(message, "strip_id"), channel,
                self._string(message, "name"),
            )
            return {"ok": True, "result": "outlet_renamed"}

        if command == "assign_charger":
            self._require_sudo(member_id)
            channel = message.get("channel")
            if isinstance(channel, bool) or not isinstance(channel, int):
                raise CommandError("channel must be an integer")
            await self.groups.assign_charger(
                self._string(message, "member_id"),
                self._string(message, "strip_id"), channel,
            )
            return {"ok": True, "result": "charger_assigned"}

        if command == "unassign_charger":
            self._require_sudo(member_id)
            await self.groups.unassign_charger(
                self._string(message, "member_id"),
                self._string(message, "strip_id"),
            )
            return {"ok": True, "result": "charger_unassigned"}

        if command == "set_push_notifications":
            self._require_sudo(member_id)
            enabled = message.get("enabled")
            if not isinstance(enabled, bool):
                raise CommandError("enabled must be a boolean")
            await self.groups.set_push_notifications(enabled, member_id)
            return {"ok": True, "result": "push_notifications_updated"}

        if command == "set_outlet":
            strip_id = self._string(message, "strip_id")
            channel = message.get("channel")
            enabled = message.get("on")
            if isinstance(channel, bool) or not isinstance(channel, int) or channel not in (1, 2, 3, 4):
                raise CommandError("channel must be an integer from 1 to 4")
            if not isinstance(enabled, bool):
                raise CommandError("on must be a boolean")
            try:
                allowed = group.can_control_outlet(member_id, strip_id, channel)
            except GroupError as exc:
                raise CommandError(str(exc)) from exc
            if not allowed:
                raise CommandError("This member is not assigned to that outlet")
            strip = group.strips[strip_id]
            if not strip.device_mac:
                raise CommandError("This strip has not been bound to physical hardware")
            session = self.devices.get_session(strip.device_mac)
            if session is None or not session.is_active:
                raise CommandError("The requested strip is offline")
            confirmed = await session.set_outlet(channel, enabled)
            if not confirmed:
                raise CommandError("The strip did not confirm the requested relay state")
            return {"ok": True, "result": "outlet_state_confirmed",
                    "strip_id": strip_id, "channel": channel, "on": enabled}

        raise CommandError("Unsupported command")

    def _require_sudo(self, member_id: str) -> None:
        if self.groups.group.sudo_member_id != member_id:
            raise CommandError("Only current Sudo can perform this operation")

    @staticmethod
    def _string(message: dict, key: str) -> str:
        value = message.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise CommandError(key + " must be a non-empty string (max 128 characters)")
        return value.strip()
