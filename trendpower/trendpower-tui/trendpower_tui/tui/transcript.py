"""Render a message transcript to plain text for copy/export.

Pure functions only — no Textual or rich dependency — so they are trivially
unit-testable and reusable by both the `/copy` (clipboard) and `/export` (file)
paths.
"""

from __future__ import annotations

import json
from typing import Any

ROLE_LABELS = {
    "user": "You",
    "assistant": "Trendpower",
    "tool": "Tool",
    "system": "System",
}


def transcript_to_text(messages: list[dict[str, Any]]) -> str:
    """Flatten a transcript into a readable, copy-pastable plain-text block."""
    blocks: list[str] = []
    for message in messages:
        role = message.get("role", "assistant")
        label = ROLE_LABELS.get(role, role.capitalize())
        rendered = _render_content(message.get("content"))
        if not rendered.strip():
            continue
        blocks.append(f"## {label}\n{rendered.rstrip()}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _render_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    lines: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            lines.append(str(part))
            continue
        part_type = part.get("type")
        if part_type == "text":
            lines.append(str(part.get("text") or ""))
        elif part_type == "thinking":
            thinking = str(part.get("thinking") or "").strip()
            if thinking:
                lines.append(f"[thinking] {thinking}")
        elif part_type == "tool_use":
            name = part.get("name") or "tool"
            args = part.get("input")
            lines.append(f"[tool_use: {name}] {_compact_json(args)}")
        elif part_type == "tool_result":
            lines.append(f"[tool_result] {_stringify(part.get('content'))}")
        else:
            lines.append(_stringify(part))
    return "\n".join(line for line in lines if line is not None)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return _compact_json(value)


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)
