"""Fan-out async event bus for SSE subscribers."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, AsyncIterator, Dict, Set


class EventBroadcaster:
    """Per-subscriber asyncio.Queue with drop-on-full publish.

    Zero subscribers => publish is a no-op, so the agent runs fine with no
    browser attached. Slow consumers lose events instead of blocking the loop.
    """

    def __init__(self, queue_size: int = 1024) -> None:
        self._subscribers: Set[asyncio.Queue[Dict[str, Any]]] = set()
        self._queue_size = queue_size
        self._sequence = 0
        self._history: list[Dict[str, Any]] = []
        self._history_cap = 2000

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Dict[str, Any]]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        # Prime the new subscriber with everything published so far, so a tab
        # opened mid-conversation still gets the full backlog.
        for event in self._history:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                break
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def publish(self, event: Dict[str, Any]) -> None:
        self._sequence += 1
        stamped: Dict[str, Any] = {"seq": self._sequence, "ts": time.time(), **event}
        self._history.append(stamped)
        if len(self._history) > self._history_cap:
            self._history = self._history[-self._history_cap :]
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(stamped)
            except asyncio.QueueFull:
                # Drop for this slow consumer; others keep up.
                pass
