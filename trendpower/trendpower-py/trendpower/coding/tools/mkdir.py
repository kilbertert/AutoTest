"""mkdir tool — create a directory at an absolute path."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result, ok_tool_result
from .tool_utils import ensure_absolute_path


class _MkdirParams(BaseModel):
    description: str = Field(
        description="Explain why you want to create the directory. Always place `description` as the first parameter."
    )
    path: str = Field(description="The absolute directory path to create.")
    recursive: Optional[bool] = Field(default=None, description="Whether to create parent directories recursively.")


async def _invoke(params: _MkdirParams) -> dict:
    absolute = ensure_absolute_path(params.path)
    if not absolute["ok"]:
        return error_tool_result(absolute["error"], "INVALID_PATH", {"path": params.path})

    recursive = params.recursive if params.recursive is not None else True
    try:
        Path(params.path).mkdir(parents=recursive, exist_ok=recursive)
        return ok_tool_result(
            f"Created directory: {params.path}",
            {"path": params.path, "recursive": recursive},
        )
    except Exception as e:
        return error_tool_result(
            f"Failed to create directory: {params.path}",
            "MKDIR_FAILED",
            {"path": params.path, "message": str(e)},
        )


mkdir_tool = define_tool(
    name="mkdir",
    description="Create a directory at an absolute path.",
    parameters=_MkdirParams,
    invoke=_invoke,
)
