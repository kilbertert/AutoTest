"""Terminal viewer for agent run traces written by ``trendpower.agent.tracing``."""

from .viewer import (
    list_trace_files,
    render_trace,
    render_trace_index,
    resolve_trace_path,
    traces_dir,
)

__all__ = [
    "list_trace_files",
    "render_trace",
    "render_trace_index",
    "resolve_trace_path",
    "traces_dir",
]
