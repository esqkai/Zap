"""Per-member authenticated WebSocket state stream and allow-listed commands."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from nxxt_level.pairing import CredentialStore
from nxxt_level.sync.hub import StateHub


async def serve_sync(hub: StateHub, credentials: CredentialStore,
                     host: str = "127.0.0.1", port: int = 10087,
                     command_handler: Optional[Any] = None,
                     group_service: Optional[Any] = None) -> Any:
    """Serve snapshots and optional authorized commands over WebSocket."""
    from websockets.asyncio.server import serve

    presence_counts: dict[str, int] = {}
    presence_lock = asyncio.Lock()

    async def handle(ws: Any) -> None:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            auth = json.loads(raw)
            if not isinstance(auth, dict):
                raise ValueError("Invalid handshake message")
            if auth.get("type") == "pair":
                if group_service is None:
                    raise ValueError("Pairing is unavailable")
                profile = auth.get("member")
                if not isinstance(profile, dict):
                    raise ValueError("Member profile is required")
                member_id = profile.get("member_id")
                display_name = profile.get("display_name")
                platform = profile.get("platform")
                capabilities = profile.get("capabilities", [])
                if not isinstance(member_id, str) or not member_id.strip() or len(member_id) > 128:
                    raise ValueError("Invalid member ID")
                if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 64:
                    raise ValueError("Invalid display name")
                if platform not in ("windows", "linux", "macos"):
                    raise ValueError("Unsupported platform")
                if not isinstance(capabilities, list) or any(
                    item not in ("battery_monitoring",) for item in capabilities
                ):
                    raise ValueError("Unsupported member capability")
                code = auth.get("pairing_code")
                if not isinstance(code, str):
                    raise ValueError("Pairing code is required")
                paired_member = Member(member_id.strip(), display_name.strip(), platform,
                                       capabilities=set(capabilities))
                paired_token = await group_service.redeem_pairing_invite(
                    code, paired_member, credentials
                )
                await ws.send(json.dumps({
                    "type": "pairing_result", "ok": True,
                    "member_id": paired_member.member_id, "token": paired_token,
                }, separators=(",", ":")))
                await ws.close(code=1000, reason="Pairing complete")
                return
            if auth.get("type") != "auth":
                raise ValueError("Invalid authentication message")
            member_id, token = auth.get("member_id"), auth.get("token")
            if not isinstance(member_id, str) or not isinstance(token, str):
                raise ValueError("Member identity and token are required")
            if not await asyncio.to_thread(credentials.authenticate, member_id, token):
                await ws.close(code=1008, reason="Unauthorized")
                return
            if group_service is not None:
                if member_id not in group_service.group.members:
                    await ws.close(code=1008, reason="Unknown group member")
                    return
                async with presence_lock:
                    count = presence_counts.get(member_id, 0)
                    presence_counts[member_id] = count + 1
                    if count == 0:
                        await group_service.set_member_online(member_id, True)
        except (asyncio.TimeoutError, ValueError, TypeError):
            await ws.close(code=1008, reason="Invalid authentication")
            return

        subscriber = await hub.subscribe()

        async def send_events() -> None:
            while True:
                event = await subscriber.queue.get()
                await ws.send(json.dumps(event, separators=(",", ":")))
                if event["type"] == "resync_required":
                    await ws.close(code=1013, reason="Client fell behind")
                    return

        async def receive_commands() -> None:
            async for raw_command in ws:
                request = {}
                try:
                    request = json.loads(raw_command)
                    if not isinstance(request, dict) or request.get("type") != "command":
                        raise ValueError("Expected command message")
                    request_id = request.get("request_id")
                    if not isinstance(request_id, str) or len(request_id) > 80:
                        raise ValueError("Invalid request_id")
                    # Re-check credentials so revocation applies to existing sessions.
                    if not await asyncio.to_thread(credentials.authenticate, member_id, token):
                        await ws.close(code=1008, reason="Credential revoked")
                        return
                    if command_handler is None:
                        raise ValueError("Controller commands are not enabled")
                    result = await command_handler.handle(member_id, request.get("payload"))
                    response = {"type": "command_result", "request_id": request_id,
                                "ok": True, "result": result}
                except Exception as exc:
                    response = {"type": "command_result",
                                "request_id": request.get("request_id") if isinstance(request, dict) else None,
                                "ok": False, "error": str(exc)[:240]}
                await ws.send(json.dumps(response, separators=(",", ":")))

        sender = asyncio.create_task(send_events())
        receiver = asyncio.create_task(receive_commands())
        try:
            done, pending = await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if not task.cancelled() and task.exception():
                    raise task.exception()
        finally:
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
            await hub.unsubscribe(subscriber)
            if group_service is not None and member_id in group_service.group.members:
                try:
                    async with presence_lock:
                        count = presence_counts.get(member_id, 0) - 1
                        if count <= 0:
                            presence_counts.pop(member_id, None)
                            await group_service.set_member_online(member_id, False)
                        else:
                            presence_counts[member_id] = count
                except Exception:
                    pass

    return await serve(handle, host, port, max_size=16384)
