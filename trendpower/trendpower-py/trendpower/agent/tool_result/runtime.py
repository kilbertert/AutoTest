"""Normalize and format tool results before they go into the transcript."""

from __future__ import annotations

import json
from typing import Any, Dict, Literal, Optional, TypedDict, Union

from .policy import get_tool_result_policy

ToolErrorKind = Literal[
    "invalid_input",
    "unsupported",
    "not_found",
    "environment_missing",
    "execution_failed",
    "unknown",
]


class NormalizedToolSuccess(TypedDict, total=False):
    ok: bool  # True
    summary: str
    data: Any
    raw: Any


class NormalizedToolError(TypedDict, total=False):
    ok: bool  # False
    summary: str
    error: str
    code: str
    details: Dict[str, Any]
    errorKind: ToolErrorKind
    raw: Any


NormalizedToolResult = Union[NormalizedToolSuccess, NormalizedToolError]


def infer_tool_error_kind(code: Optional[str]) -> ToolErrorKind:
    if not code:
        return "unknown"
    if code.startswith("INVALID_"):
        return "invalid_input"
    if code.endswith("_NOT_SUPPORTED"):
        return "unsupported"
    if code == "RG_NOT_FOUND":
        return "environment_missing"
    if code == "FILE_NOT_FOUND" or code.endswith("_NOT_FOUND"):
        return "not_found"
    if code.endswith("_FAILED"):
        return "execution_failed"
    return "unknown"


def _is_structured_success(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("ok") is True
        and isinstance(value.get("summary"), str)
    )


def _is_structured_error(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("ok") is False
        and isinstance(value.get("summary"), str)
        and isinstance(value.get("error"), str)
    )


def normalize_tool_result(result: Any) -> NormalizedToolResult:
    if _is_structured_success(result):
        out: NormalizedToolSuccess = {"ok": True, "summary": result["summary"], "raw": result}
        if result.get("data") is not None:
            out["data"] = result["data"]
        return out

    if _is_structured_error(result):
        out_err: NormalizedToolError = {
            "ok": False,
            "summary": result["summary"],
            "error": result["error"],
            "errorKind": infer_tool_error_kind(result.get("code")),
            "raw": result,
        }
        if result.get("code"):
            out_err["code"] = result["code"]
        if result.get("details"):
            out_err["details"] = result["details"]
        return out_err

    if isinstance(result, str) and result.startswith("Error:"):
        error = result[len("Error:") :].strip() or "Tool execution failed."
        return {
            "ok": False,
            "summary": error,
            "error": error,
            "errorKind": "unknown",
            "raw": result,
        }

    summary = _stringify_value(result)
    out_succ: NormalizedToolSuccess = {"ok": True, "summary": summary, "raw": result}
    if result is not None:
        out_succ["data"] = result
    return out_succ


def format_tool_result_for_message(tool_name: str, result: Any) -> str:
    if tool_name == "read_file" and isinstance(result, str):
        return result

    normalized = normalize_tool_result(result)
    policy = get_tool_result_policy(tool_name)
    max_len = policy.get("maxStringLength")

    if not normalized["ok"]:
        payload: Dict[str, Any] = {
            "ok": False,
            "summary": normalized["summary"],
            "error": normalized["error"],
        }
        if normalized.get("code"):
            payload["code"] = normalized["code"]
        if normalized.get("details"):
            payload["details"] = normalized["details"]

        fallback: Dict[str, Any] = {
            "ok": False,
            "summary": _truncate_summary(normalized["summary"]),
            "error": _truncate_summary(normalized["error"]),
        }
        if normalized.get("code"):
            fallback["code"] = normalized["code"]
        return _stringify_within_limit(payload, max_len, fallback)

    if policy.get("preferSummaryOnly") or not policy.get("includeData", True):
        return json.dumps({"ok": True, "summary": _truncate_summary(normalized["summary"])})

    payload_ok: Dict[str, Any] = {"ok": True, "summary": normalized["summary"]}
    if normalized.get("data") is not None:
        payload_ok["data"] = normalized["data"]
    fallback_ok: Dict[str, Any] = {"ok": True, "summary": _truncate_summary(normalized["summary"])}
    return _stringify_within_limit(payload_ok, max_len, fallback_ok)


def _stringify_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return "[unserializable object]"
    return str(value)


def _stringify_within_limit(payload: Dict[str, Any], max_length: Optional[int], fallback: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, default=str)
    if not max_length or len(serialized) <= max_length:
        return serialized

    fallback_serialized = json.dumps(fallback, default=str)
    if not max_length or len(fallback_serialized) <= max_length:
        return fallback_serialized

    if fallback.get("ok"):
        return json.dumps({"ok": True, "summary": fallback["summary"][: max(0, max_length - 32)]})

    out: Dict[str, Any] = {
        "ok": False,
        "summary": fallback["summary"][: max(0, max_length - 64)],
        "error": fallback["error"][: max(0, max_length - 64)],
    }
    if fallback.get("code"):
        out["code"] = fallback["code"]
    return json.dumps(out)


def _truncate_summary(value: str, max_length: int = 500) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[:max_length]}... [truncated {len(value) - max_length} chars]"
