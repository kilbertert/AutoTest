"""A TraceSink that republishes span events onto the web EventBroadcaster.

Structurally satisfies ``trendpower.agent.tracing.TraceSink`` (no inheritance
needed — it's a Protocol). Trace events ride the same ``/events`` SSE stream as
everything else, tagged ``type: "trace"`` so the browser can route them to the
live timeline.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .broadcaster import EventBroadcaster


class BroadcasterSink:
    def __init__(self, broadcaster: EventBroadcaster) -> None:
        self._broadcaster = broadcaster
        self.current_top_run_id: Optional[str] = None

    def begin_run(self, run_id: str, *, is_top: bool) -> None:
        if is_top:
            self.current_top_run_id = run_id
        self._broadcaster.publish(
            {"type": "trace", "kind": "begin_run", "run_id": run_id, "is_top": is_top}
        )

    def emit(self, event: Dict[str, Any]) -> None:
        self._broadcaster.publish({"type": "trace", "kind": "span", "event": event})
