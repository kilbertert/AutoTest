"""Derive the set of files the agent has written/edited from the transcript.

Mirrors the shape of `todo_view.build_todo_view_state`: a pure function over the
message list that the app calls whenever the transcript changes. The code panel
uses the result to list every file touched in the conversation; it reads the
actual content from disk (so it always reflects the latest, including user edits).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FileEntry:
    path: str  # absolute path on disk
    display: str  # path relative to cwd when possible, for the list label


_MUTATING_TOOLS = {"write_file", "str_replace", "apply_patch"}


def _normalize_patch_path(raw: str) -> str:
    raw = raw.strip()
    # Strip a trailing "\t<timestamp>" some diff tools emit.
    raw = raw.split("\t", 1)[0].strip()
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return raw


def _paths_from_tool_use(content: dict[str, Any]) -> list[str]:
    name = content.get("name")
    tool_input = content.get("input")
    if not isinstance(tool_input, dict):
        return []

    if name in ("write_file", "str_replace"):
        path = tool_input.get("path")
        return [path] if isinstance(path, str) and path else []

    if name == "apply_patch":
        patch = tool_input.get("patch")
        if not isinstance(patch, str):
            return []
        paths: list[str] = []
        for line in patch.replace("\r\n", "\n").split("\n"):
            if line.startswith("+++ "):
                target = _normalize_patch_path(line[4:])
                if target and target != "/dev/null":
                    paths.append(target)
        return paths

    return []


def build_file_entries(messages: list[dict[str, Any]], cwd: str) -> list[FileEntry]:
    """Ordered, de-duplicated list of files touched by mutating tool calls.

    Order is by first appearance, so the list is stable as the conversation grows.
    Only absolute paths are kept (the coding tools require absolute paths).
    """

    seen: set[str] = set()
    entries: list[FileEntry] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for content in message.get("content") or []:
            if not isinstance(content, dict) or content.get("type") != "tool_use":
                continue
            if content.get("name") not in _MUTATING_TOOLS:
                continue
            for path in _paths_from_tool_use(content):
                if not os.path.isabs(path) or path in seen:
                    continue
                seen.add(path)
                try:
                    display = os.path.relpath(path, cwd)
                except ValueError:
                    display = path
                if display.startswith(".."):
                    display = path
                entries.append(FileEntry(path=path, display=display))
    return entries
