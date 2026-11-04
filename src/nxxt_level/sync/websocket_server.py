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

    async def handle(ws: Any) -> None:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            auth = json.loads(raw)
            if not isinstance(auth, dict) or auth.get("type") != "auth":
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
                    await group_service.set_member_online(member_id, False)
                except Exception:
                    pass

    return await serve(handle, host, port, max_size=16384)
