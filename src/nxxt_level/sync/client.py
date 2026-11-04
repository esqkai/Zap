"""Read-only real-time client used by Windows and Linux frontends."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict


async def watch_controller(uri: str, token: str) -> AsyncIterator[Dict[str, Any]]:
    """Yield initial snapshot then ordered state events.

    Reconnect with exponential backoff; request a fresh snapshot on every
    connection. Callers should treat data as stale while disconnected.
    """
    from websockets.asyncio.client import connect

    if not uri.startswith(("ws://", "wss://")):
        raise ValueError("Expected a WebSocket URL")
    if len(token) < 32:
        raise ValueError("Pairing token must contain at least 32 characters")
    delay = 1.0
    while True:
        try:
            async with connect(uri, open_timeout=5, max_size=1024 * 1024) as ws:
                await ws.send(json.dumps({"type": "auth", "token": token}))
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
                            break  # Lost events; reconnect for full snapshot.
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
