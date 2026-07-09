"""Tool result handling: per-tool formatting policy, transcript normalization, UI summaries."""

from .policy import ToolResultPolicy, get_tool_result_policy
from .runtime import (
    NormalizedToolError,
    NormalizedToolResult,
    NormalizedToolSuccess,
    ToolErrorKind,
    format_tool_result_for_message,
    infer_tool_error_kind,
    normalize_tool_result,
)
from .summary import summarize_tool_result_text

__all__ = [
    "NormalizedToolError",
    "NormalizedToolResult",
    "NormalizedToolSuccess",
    "ToolErrorKind",
    "ToolResultPolicy",
    "format_tool_result_for_message",
    "get_tool_result_policy",
    "infer_tool_error_kind",
    "normalize_tool_result",
    "summarize_tool_result_text",
]
