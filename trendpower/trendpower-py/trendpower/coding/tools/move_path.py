"""move_path tool — move or rename a file or directory."""

from __future__ import annotations

import shutil

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result, ok_tool_result
from .tool_utils import ensure_absolute_path


class _MovePathParams(BaseModel):
    description: str = Field(
        description="Explain why you want to move the path. Always place `description` as the first parameter."
    )
    from_: str = Field(alias="from", description="The absolute source path.")
    to: str = Field(description="The absolute target path.")

    model_config = {"populate_by_name": True}


async def _invoke(params: _MovePathParams) -> dict:
    source = ensure_absolute_path(params.from_)
    if not source["ok"]:
        return error_tool_result(source["error"], "INVALID_SOURCE_PATH", {"from": params.from_, "to": params.to})

    target = ensure_absolute_path(params.to)
    if not target["ok"]:
        return error_tool_result(target["error"], "INVALID_TARGET_PATH", {"from": params.from_, "to": params.to})

    try:
        shutil.move(params.from_, params.to)
        return ok_tool_result(
            f"Moved path from {params.from_} to {params.to}",
            {"from": params.from_, "to": params.to},
        )
    except Exception as e:
        return error_tool_result(
            f"Failed to move path from {params.from_} to {params.to}",
            "MOVE_FAILED",
            {"from": params.from_, "to": params.to, "message": str(e)},
        )


move_path_tool = define_tool(
    name="move_path",
    description="Move or rename a file or directory between absolute paths.",
    parameters=_MovePathParams,
    invoke=_invoke,
)
