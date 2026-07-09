"""read_file tool — read a file by absolute path, with optional line-range slicing."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result
from .tool_utils import ensure_absolute_path, truncate_text

_DEFAULT_MAX_CHARS = 12000


class _ReadFileParams(BaseModel):
    description: str = Field(
        description="Explain why you want to read the file. Always place `description` as the first parameter."
    )
    path: str = Field(description="The absolute path to the file to read.")
    startLine: Optional[int] = Field(default=None, description="1-based starting line to read.", ge=1)
    endLine: Optional[int] = Field(default=None, description="1-based ending line to read, inclusive.", ge=1)
    maxChars: Optional[int] = Field(default=None, description="Maximum characters to return from the selected range.", ge=1)


async def _invoke(params: _ReadFileParams) -> Union[str, dict]:
    absolute = ensure_absolute_path(params.path)
    if not absolute["ok"]:
        return error_tool_result(absolute["error"], "INVALID_PATH", {"path": params.path})

    if params.startLine is not None and params.endLine is not None and params.startLine > params.endLine:
        return error_tool_result(
            "startLine must be less than or equal to endLine.",
            "INVALID_RANGE",
            {"path": params.path, "startLine": params.startLine, "endLine": params.endLine},
        )

    p = Path(params.path)
    if not p.exists():
        return error_tool_result(f"File {params.path} does not exist.", "FILE_NOT_FOUND", {"path": params.path})

    text = p.read_text(encoding="utf-8")
    lines = text.split("\n")
    start = (params.startLine - 1) if params.startLine else 0
    end = min(params.endLine, len(lines)) if params.endLine else len(lines)

    if start < 0 or start >= len(lines):
        return error_tool_result(
            f"startLine {params.startLine} is out of range for file {params.path}.",
            "START_LINE_OUT_OF_RANGE",
            {"path": params.path, "startLine": params.startLine, "totalLines": len(lines)},
        )

    selected = lines[start:end]
    numbered = "\n".join(f"{start + i + 1}: {line}" for i, line in enumerate(selected))
    limited = truncate_text(numbered, params.maxChars or _DEFAULT_MAX_CHARS)
    is_whole_file_read = not params.startLine and not params.endLine

    return text if (is_whole_file_read and not limited["truncated"]) else limited["text"]


read_file_tool = define_tool(
    name="read_file",
    description="Read a file from an absolute path. Supports optional line-range reads for large files.",
    parameters=_ReadFileParams,
    invoke=_invoke,
)
