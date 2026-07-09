"""Where trace events go. The middleware is sink-agnostic; the frontend picks.

``begin_run`` lets a sink react to a new top-level run (e.g. rotate to a fresh
file). Sub-agent runs reuse the *same* sink instance and call ``begin_run`` with
``is_top=False`` so all their spans land in the parent's file/stream; the
``current_top_run_id`` they read back becomes their ``parent_run_id``.

Sinks must never raise into the agent loop — emission is best-effort.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

_log = logging.getLogger("trendpower.tracing")


@runtime_checkable
class TraceSink(Protocol):
    current_top_run_id: Optional[str]

    def begin_run(self, run_id: str, *, is_top: bool) -> None: ...

    def emit(self, event: Dict[str, Any]) -> None: ...


class _BaseSink:
    def __init__(self) -> None:
        self.current_top_run_id: Optional[str] = None

    def begin_run(self, run_id: str, *, is_top: bool) -> None:
        if is_top:
            self.current_top_run_id = run_id

    def emit(self, event: Dict[str, Any]) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class JsonlSink(_BaseSink):
    """Append-per-event JSONL, one ``<run_id>.jsonl`` file per top-level run."""

    def __init__(self, directory: "str | os.PathLike[str]") -> None:
        super().__init__()
        self._dir = Path(directory)
        self._path: Optional[Path] = None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def begin_run(self, run_id: str, *, is_top: bool) -> None:
        super().begin_run(run_id, is_top=is_top)
        if not is_top:
            return  # sub-agent: keep writing into the parent's open file
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path = self._dir / f"{run_id}.jsonl"
        except OSError as exc:
            _log.warning("trace: could not open trace dir %s: %s", self._dir, exc)
            self._path = None

    def emit(self, event: Dict[str, Any]) -> None:
        if self._path is None:
            return
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            _log.warning("trace: write failed: %s", exc)


class MultiSink(_BaseSink):
    """Fan an event stream out to several sinks (e.g. file + live browser)."""

    def __init__(self, sinks: List[TraceSink]) -> None:
        super().__init__()
        self._sinks = list(sinks)

    def begin_run(self, run_id: str, *, is_top: bool) -> None:
        super().begin_run(run_id, is_top=is_top)
        for sink in self._sinks:
            try:
                sink.begin_run(run_id, is_top=is_top)
            except Exception as exc:  # noqa: BLE001 - never break the run
                _log.warning("trace: sink begin_run failed: %s", exc)

    def emit(self, event: Dict[str, Any]) -> None:
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception as exc:  # noqa: BLE001
                _log.warning("trace: sink emit failed: %s", exc)
