"""list_files tool — list directory entries with optional recursion."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result, ok_tool_result
from .tool_utils import ensure_directory_path, truncate_text

_DEFAULT_LIMIT = 200
_DEFAULT_MAX_CHARS = 12000


def _walk(dir_path: Path, max_depth: int, prefix: str = "", depth: int = 0, entries: Optional[List[str]] = None) -> List[str]:
    if entries is None:
        entries = []
    items = sorted(dir_path.iterdir(), key=lambda p: p.name)
    for item in items:
        relative_path = f"{prefix}/{item.name}" if prefix else item.name
        entries.append(f"{relative_path}/" if item.is_dir() else relative_path)
        if item.is_dir() and depth < max_depth:
            _walk(item, max_depth, relative_path, depth + 1, entries)
    return entries


class _ListFilesParams(BaseModel):
    description: str = Field(
        description="Explain why you want to inspect the directory. Always place `description` as the first parameter."
    )
    path: str = Field(description="The absolute directory path to inspect.")
    recursive: Optional[bool] = Field(default=None, description="Whether to recurse into subdirectories.")
    maxDepth: Optional[int] = Field(default=None, ge=0, description="Maximum recursion depth when recursive=true.")
    limit: Optional[int] = Field(default=None, ge=1, description="Maximum number of entries to return.")
    maxChars: Optional[int] = Field(default=None, ge=1, description="Maximum characters to return.")


async def _invoke(params: _ListFilesParams) -> dict:
    dir_check = ensure_directory_path(params.path)
    if not dir_check["ok"]:
        return error_tool_result(dir_check["error"], "INVALID_DIRECTORY", {"path": params.path})

    max_depth = (params.maxDepth if params.maxDepth is not None else 3) if params.recursive else 0
    entries = _walk(Path(params.path), max_depth)
    capped = entries[: (params.limit or _DEFAULT_LIMIT)]
    limited = truncate_text("\n".join(capped), params.maxChars or _DEFAULT_MAX_CHARS)

    return ok_tool_result(
        f"Listed {len(capped)} entries under {params.path}",
        {
            "path": params.path,
            "totalEntries": len(entries),
            "shownEntries": len(capped),
            "truncated": limited["truncated"] or len(capped) < len(entries),
            "entries": capped,
            "content": limited["text"],
        },
    )


list_files_tool = define_tool(
    name="list_files",
    description="List files and directories from an absolute path, with optional recursion.",
    parameters=_ListFilesParams,
    invoke=_invoke,
)
