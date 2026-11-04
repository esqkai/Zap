"""Member-authenticated LAN WebSocket transport for StateHub."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from nxxt_level.pairing import CredentialStore
from nxxt_level.sync.hub import StateHub


async def serve_sync(hub: StateHub, credentials: CredentialStore,
                     host: str = "127.0.0.1", port: int = 10087) -> Any:
    """Start a read-only event stream authenticated per paired member."""
    from websockets.asyncio.server import serve

    async def handle(ws: Any) -> None:
        member_id = None
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            auth = json.loads(raw)
            if not isinstance(auth, dict) or auth.get("type") != "auth":
                raise ValueError("Invalid authentication message")
            candidate_id, token = auth.get("member_id"), auth.get("token")
            if not isinstance(candidate_id, str) or not isinstance(token, str):
                raise ValueError("Member identity and token are required")
            if not await asyncio.to_thread(credentials.authenticate, candidate_id, token):
                await ws.close(code=1008, reason="Unauthorized")
                return
            member_id = candidate_id
        except (asyncio.TimeoutError, ValueError, TypeError):
            await ws.close(code=1008, reason="Invalid authentication")
            return

        subscriber = await hub.subscribe()
        try:
            while True:
                event = await subscriber.queue.get()
                await ws.send(json.dumps(event, separators=(",", ":")))
                if event["type"] == "resync_required":
                    await ws.close(code=1013, reason="Client fell behind")
                    break
        finally:
            await hub.unsubscribe(subscriber)

    return await serve(handle, host, port, max_size=1024 * 1024)
