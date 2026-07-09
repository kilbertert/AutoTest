"""write_file tool — write to a file at an absolute path."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result, ok_tool_result
from .tool_utils import ensure_absolute_path


class _WriteFileParams(BaseModel):
    description: str = Field(
        description="Explain why you want to write to the file. Always place `description` as the first parameter."
    )
    path: str = Field(description="The absolute path to the file to write to.")
    content: str = Field(description="The content to write to the file.")


async def _invoke(params: _WriteFileParams) -> dict:
    absolute = ensure_absolute_path(params.path)
    if not absolute["ok"]:
        return error_tool_result(absolute["error"], "INVALID_PATH", {"path": params.path})

    try:
        p = Path(params.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(params.content, encoding="utf-8")
        return ok_tool_result(
            f"Successfully wrote {len(params.content)} chars to {params.path}",
            {"path": params.path, "bytes": len(params.content)},
        )
    except Exception as e:
        return error_tool_result(
            f"Failed to write file: {params.path}",
            "WRITE_FAILED",
            {"path": params.path, "message": str(e)},
        )


write_file_tool = define_tool(
    name="write_file",
    description="Write to a file at an absolute path. Creates parent directories if they do not exist.",
    parameters=_WriteFileParams,
    invoke=_invoke,
)
