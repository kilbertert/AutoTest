"""str_replace tool — replace occurrences of a substring in a file."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result, ok_tool_result
from .tool_utils import ensure_absolute_path


class _StrReplaceParams(BaseModel):
    description: str = Field(
        description="Explain why you want to perform this replacement. Always place `description` as the first parameter."
    )
    path: str = Field(description="The absolute path to the file to operate on.")
    old: str = Field(description="The substring to replace.")
    new: str = Field(description="The substring to be replaced with.")
    count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum number of replacements. Omit to replace all occurrences.",
    )


async def _invoke(params: _StrReplaceParams) -> dict:
    absolute = ensure_absolute_path(params.path)
    if not absolute["ok"]:
        return error_tool_result(absolute["error"], "INVALID_PATH", {"path": params.path})

    p = Path(params.path)
    if not p.exists():
        return error_tool_result(f"File {params.path} does not exist.", "FILE_NOT_FOUND", {"path": params.path})

    if len(params.old) == 0:
        return error_tool_result("`old` must be a non-empty string.", "INVALID_ARGUMENT", {"path": params.path})

    text = p.read_text(encoding="utf-8")

    max_replacements = params.count if params.count is not None else math.inf
    if max_replacements == 0:
        return ok_tool_result(
            f"No replacements requested (count=0) in {params.path}",
            {"path": params.path, "replacements": 0, "changed": False},
        )

    # Count actual occurrences up to the limit
    replacements = 0
    idx = 0
    while replacements < max_replacements:
        nxt = text.find(params.old, idx)
        if nxt == -1:
            break
        replacements += 1
        idx = nxt + len(params.old)

    if replacements == 0:
        return error_tool_result(
            f"No occurrences of 'old' found in {params.path}.", "NOT_FOUND", {"path": params.path}
        )

    if params.count is None:
        updated = text.replace(params.old, params.new)
    else:
        updated = text.replace(params.old, params.new, params.count)

    if updated == text:
        return ok_tool_result(
            f"No effective changes in {params.path}",
            {"path": params.path, "replacements": 0, "changed": False},
        )

    try:
        p.write_text(updated, encoding="utf-8")
        return ok_tool_result(
            f"Replaced {replacements} occurrence(s) in {params.path}",
            {"path": params.path, "replacements": replacements, "changed": True},
        )
    except Exception as e:
        return error_tool_result(
            f"Failed to write replacement to {params.path}",
            "WRITE_FAILED",
            {"path": params.path, "message": str(e)},
        )


str_replace_tool = define_tool(
    name="str_replace",
    description="Replace occurrences of a substring in a file. Make sure the `old` is unique in the file.",
    parameters=_StrReplaceParams,
    invoke=_invoke,
)
