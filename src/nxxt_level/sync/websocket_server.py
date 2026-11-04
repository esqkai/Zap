"""LAN WebSocket transport for StateHub.

Install optional dependency: pip install websockets>=12.
Use a randomly generated pairing token; never expose this port to the internet.
"""
from __future__ import annotations

import asyncio
import hmac
import json
from typing import Any

from nxxt_level.sync.hub import StateHub


async def serve_sync(hub: StateHub, token: str, host: str = "127.0.0.1",
                     port: int = 10087) -> Any:
    """Start a WebSocket event server. Returns a closable server object.

    This is a read-only stream; command handling will be added only after
    device acknowledgements and authorization are integrated.
    """
    if len(token) < 32:
        raise ValueError("Pairing token must contain at least 32 characters")
    from websockets.asyncio.server import serve

    async def handle(ws: Any) -> None:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            auth = json.loads(raw)
            if (not isinstance(auth, dict)
                    or auth.get("type") != "auth"
                    or not isinstance(auth.get("token"), str)
                    or not hmac.compare_digest(auth["token"], token)):
                await ws.close(code=1008, reason="Unauthorized")
                return
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

    return await serve(handle, host, port, max_size=16384)
