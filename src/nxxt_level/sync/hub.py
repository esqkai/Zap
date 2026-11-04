"""Authenticated real-time state hub for desktop clients.

The hub is transport-independent: a WebSocket adapter can call subscribe(),
publish(), and unsubscribe(). All state mutations belong to the controller.
"""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from typing import Any, Dict, Set


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue


class StateHub:
    """Controller-owned versioned snapshots and bounded subscriber streams."""

    def __init__(self, max_queue: int = 128) -> None:
        self._lock = asyncio.Lock()
        self._revision = 0
        self._state: Dict[str, Any] = {"devices": {}, "automation": {}}
        self._subscribers: Set[Subscriber] = set()
        self._max_queue = max_queue

    async def snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            return {"type": "snapshot", "revision": self._revision,
                    "state": copy.deepcopy(self._state)}

    async def subscribe(self) -> Subscriber:
        subscriber = Subscriber(asyncio.Queue(maxsize=self._max_queue))
        async with self._lock:
            subscriber.queue.put_nowait({
                "type": "snapshot", "revision": self._revision,
                "state": copy.deepcopy(self._state),
            })
            self._subscribers.add(subscriber)
        return subscriber

    async def unsubscribe(self, subscriber: Subscriber) -> None:
        async with self._lock:
            self._subscribers.discard(subscriber)

    async def publish(self, section: str, key: str, value: Any) -> int:
        """Replace one controller-owned entry; notify clients in revision order."""
        if section not in ("devices", "automation"):
            raise ValueError("Unknown state section")
        async with self._lock:
            safe_value = copy.deepcopy(value)
            self._state[section][key] = safe_value
            self._revision += 1
            event = {"type": "state_changed", "revision": self._revision,
                     "section": section, "key": key, "value": safe_value}
            for subscriber in list(self._subscribers):
                # Slow clients must resubscribe for a fresh snapshot.
                if subscriber.queue.full():
                    self._subscribers.remove(subscriber)
                    while not subscriber.queue.empty():
                        subscriber.queue.get_nowait()
                    subscriber.queue.put_nowait({"type": "resync_required",
                                                 "revision": self._revision})
                    continue
                subscriber.queue.put_nowait(copy.deepcopy(event))
            return self._revision
