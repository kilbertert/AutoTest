"""file_info tool — return metadata about a file or directory."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result, ok_tool_result
from .tool_utils import ensure_absolute_path


class _FileInfoParams(BaseModel):
    description: str = Field(
        description="Explain why you want to inspect the path. Always place `description` as the first parameter."
    )
    path: str = Field(description="The absolute path to inspect.")


async def _invoke(params: _FileInfoParams) -> dict:
    absolute = ensure_absolute_path(params.path)
    if not absolute["ok"]:
        return error_tool_result(absolute["error"], "INVALID_PATH", {"path": params.path})

    try:
        p = Path(params.path)
        info = p.stat()
        if p.is_dir():
            kind = "directory"
        elif p.is_file():
            kind = "file"
        else:
            kind = "other"

        # st_birthtime is not present on all platforms — fall back to st_ctime.
        try:
            birth = info.st_birthtime  # type: ignore[attr-defined]
        except AttributeError:
            birth = info.st_ctime

        return ok_tool_result(
            f"Inspected {kind}: {params.path}",
            {
                "path": params.path,
                "kind": kind,
                "size": info.st_size,
                "modifiedTime": datetime.fromtimestamp(info.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "createdTime": datetime.fromtimestamp(birth, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as e:
        return error_tool_result(
            f"Failed to inspect path: {params.path}",
            "STAT_FAILED",
            {"path": params.path, "message": str(e)},
        )


file_info_tool = define_tool(
    name="file_info",
    description="Return metadata about a file or directory at an absolute path.",
    parameters=_FileInfoParams,
    invoke=_invoke,
)
