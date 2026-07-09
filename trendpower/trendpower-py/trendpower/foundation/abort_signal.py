"""Lightweight AbortSignal/AbortController-like primitive for cooperative cancellation.

Mirrors the contract used by the TS source (`AbortSignal` from the web platform):
- `.aborted: bool` — current state
- `.reason: Any` — optional reason set when aborted
- `.throw_if_aborted()` — raises AbortError if already aborted
- `add_listener(cb)` — register a callback fired on abort (once)
- `wait()` — async; returns when aborted (for races)
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable


class AbortError(Exception):
    """Raised when an operation is aborted."""


class AbortSignal:
    def __init__(self) -> None:
        self._aborted = False
        self._reason: Any = None
        self._event = asyncio.Event()
        self._listeners: list[Callable[[], Any]] = []

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> Any:
        return self._reason

    def throw_if_aborted(self) -> None:
        if self._aborted:
            raise self._reason if isinstance(self._reason, BaseException) else AbortError(str(self._reason or "Aborted"))

    def add_listener(self, callback: Callable[[], Any]) -> Callable[[], None]:
        """Register a callback fired on abort (once). Returns a function to remove it."""
        if self._aborted:
            try:
                callback()
            except Exception:
                pass
            return lambda: None
        self._listeners.append(callback)

        def remove() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

        return remove

    async def wait(self) -> None:
        await self._event.wait()

    def _abort(self, reason: Any = None) -> None:
        if self._aborted:
            return
        self._aborted = True
        self._reason = reason if reason is not None else AbortError("Aborted")
        self._event.set()
        listeners = list(self._listeners)
        self._listeners.clear()
        for cb in listeners:
            try:
                cb()
            except Exception:
                pass


class AbortController:
    """Companion to AbortSignal. Holds a signal and exposes abort()."""

    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self, reason: Any = None) -> None:
        self.signal._abort(reason)
