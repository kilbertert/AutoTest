"""Helpers for building StructuredToolResult ok/error payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional, TypeVar

T = TypeVar("T")


def ok_tool_result(summary: str, data: T) -> Dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data}


def error_tool_result(
    error: str,
    code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "summary": error, "error": error}
    if code:
        out["code"] = code
    if details:
        out["details"] = details
    return out
