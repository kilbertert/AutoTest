"""Track files the agent writes and feed back any out-of-band user edits.

When the agent writes a file (via `write_file`, `str_replace`, or `apply_patch`)
we record a hash of the resulting on-disk content. Before the next model call we
re-read those files: if the content changed since the agent last saw it — because
the user edited it in their own editor or in the TUI code panel — we inject the
current content as a `<files_changed_by_user>` block so the model continues from
the user's version rather than its stale memory of what it wrote.

The agent's own writes update the recorded hash (in `afterToolUse`), so they
never trigger a spurious injection — only genuine external edits do.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

_TRACKED_TOOLS = {"write_file", "str_replace", "apply_patch"}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _paths_from_tool(name: str, tool_input: Any, tool_result: Any) -> List[str]:
    """Best-effort extraction of the file paths a successful tool touched."""

    if isinstance(tool_result, dict) and tool_result.get("ok") is False:
        return []

    if name in ("write_file", "str_replace"):
        if isinstance(tool_input, dict) and isinstance(tool_input.get("path"), str):
            return [tool_input["path"]]
        return []

    if name == "apply_patch":
        data = tool_result.get("data") if isinstance(tool_result, dict) else None
        changed = data.get("changedFiles") if isinstance(data, dict) else None
        if isinstance(changed, list):
            return [p for p in changed if isinstance(p, str)]
    return []


def create_file_change_tracker():
    """Returns a middleware (beforeModel + afterToolUse) that surfaces user edits."""

    # path -> hash of the content the agent last knows about.
    known: Dict[str, str] = {}

    async def after_tool_use(params):
        tool_use = params.get("toolUse") or {}
        name = tool_use.get("name")
        if name not in _TRACKED_TOOLS:
            return None
        for path in _paths_from_tool(name, tool_use.get("input"), params.get("toolResult")):
            content = _read(path)
            if content is not None:
                known[path] = _hash(content)
        return None

    async def before_model(params):
        changed: List[tuple[str, str]] = []
        for path in list(known.keys()):
            content = _read(path)
            if content is None:
                continue
            digest = _hash(content)
            if digest != known[path]:
                known[path] = digest
                changed.append((path, content))

        if not changed:
            return None

        blocks = [
            "\n<files_changed_by_user>\n"
            "The user manually edited the following file(s) since you last wrote them "
            "(in their own editor or the code panel). This is the current on-disk content "
            "and the source of truth — use it, do not rely on your earlier version.\n"
        ]
        for path, content in changed:
            blocks.append(f'\n<file path="{path}">\n{content}\n</file>\n')
        blocks.append("</files_changed_by_user>\n")

        return {"prompt": params["modelContext"]["prompt"] + "".join(blocks)}

    return SimpleNamespace(beforeModel=before_model, afterToolUse=after_tool_use)
