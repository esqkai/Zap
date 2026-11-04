"""Read-only real-time client using per-installation member credentials."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict


async def watch_controller(uri: str, member_id: str, token: str) -> AsyncIterator[Dict[str, Any]]:
    """Yield snapshots and ordered updates, reconnecting with backoff."""
    from websockets.asyncio.client import connect

    if not uri.startswith(("ws://", "wss://")):
        raise ValueError("Expected a WebSocket URL")
    if not member_id or len(token) < 32:
        raise ValueError("A member ID and valid pairing token are required")
    delay = 1.0
    while True:
        try:
            async with connect(uri, open_timeout=5, max_size=1024 * 1024) as ws:
                await ws.send(json.dumps({
                    "type": "auth", "member_id": member_id, "token": token,
                }))
                delay = 1.0
                last_revision = -1
                async for raw in ws:
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError("Invalid controller event")
                    kind = message.get("type")
                    revision = message.get("revision")
                    if kind == "resync_required":
                        break
                    if not isinstance(revision, int):
                        raise ValueError("Missing state revision")
                    if kind == "snapshot":
                        last_revision = revision
                    elif kind == "state_changed":
                        if revision != last_revision + 1:
                            break
                        last_revision = revision
                    else:
                        continue
                    yield message
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError, ValueError):
            pass
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30.0)
