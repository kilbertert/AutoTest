"""TraceEvent shapes and constructors.

A trace is a flat append-only stream of these dicts; a viewer reconstructs the
tree by matching ``start``/``end`` events on ``(span, id)``. Emitting flat +
incremental (rather than building one nested object at the end) is deliberate:
the agent loop has no ``onAbort`` hook, so a run cancelled with Ctrl+C never
reaches ``afterAgentRun``. With per-event emission the partial trace still
survives on disk, and an unclosed ``run`` span is read back as "aborted".
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Literal, Optional

SpanKind = Literal["run", "step", "llm", "tool", "compaction"]
EventType = Literal["start", "end", "event"]


def new_span_id(prefix: str = "sp") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def span_start(kind: SpanKind, span_id: str, parent: Optional[str], **attrs: Any) -> Dict[str, Any]:
    return {"t": "start", "span": kind, "id": span_id, "parent": parent, "ts": time.time(), **attrs}


def span_end(kind: SpanKind, span_id: str, **attrs: Any) -> Dict[str, Any]:
    return {"t": "end", "span": kind, "id": span_id, "ts": time.time(), **attrs}


def point_event(kind: SpanKind, parent: Optional[str], **attrs: Any) -> Dict[str, Any]:
    """A zero-duration event (e.g. compaction) with no separate end."""
    return {
        "t": "event",
        "span": kind,
        "id": new_span_id(kind),
        "parent": parent,
        "ts": time.time(),
        **attrs,
    }
