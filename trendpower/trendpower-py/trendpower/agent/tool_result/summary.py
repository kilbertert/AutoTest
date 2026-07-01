"""Summarize a tool result payload into a one-line UI string (or None)."""

from __future__ import annotations

import json
from typing import Optional


def summarize_tool_result_text(content: str) -> Optional[str]:
    if content.startswith("Error:"):
        return content

    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(parsed, dict):
        return None

    if parsed.get("ok") is True and isinstance(parsed.get("summary"), str):
        return parsed["summary"]

    if parsed.get("ok") is False:
        message = (
            parsed["summary"]
            if isinstance(parsed.get("summary"), str)
            else parsed["error"]
            if isinstance(parsed.get("error"), str)
            else content
        )
        code = parsed["code"] if isinstance(parsed.get("code"), str) else None
        return f"Error [{code}]: {message}" if code else f"Error: {message}"

    return None
