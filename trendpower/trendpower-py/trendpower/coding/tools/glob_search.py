"""glob_search tool — find files matching a glob pattern under a directory."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result, ok_tool_result
from .tool_utils import ensure_directory_path, truncate_text

_DEFAULT_LIMIT = 200
_DEFAULT_MAX_CHARS = 12000


class _GlobSearchParams(BaseModel):
    description: str = Field(
        description="Explain why you want to find files. Always place `description` as the first parameter."
    )
    path: str = Field(description="The absolute directory path to search within.")
    pattern: str = Field(description="Glob pattern, for example **/*.ts or src/**/*.tsx.")
    limit: Optional[int] = Field(default=None, ge=1, description="Maximum number of matches to return.")
    maxChars: Optional[int] = Field(default=None, ge=1, description="Maximum characters to return.")


async def _invoke(params: _GlobSearchParams) -> dict:
    dir_check = ensure_directory_path(params.path)
    if not dir_check["ok"]:
        return error_tool_result(
            dir_check["error"], "INVALID_DIRECTORY", {"path": params.path, "pattern": params.pattern}
        )

    matches = []
    limit = params.limit or _DEFAULT_LIMIT
    try:
        root = Path(params.path)
        # pathlib's glob supports **/<pattern>; preserve absolute paths to match TS behaviour.
        for entry in root.glob(params.pattern):
            matches.append(str(entry.resolve()))
            if len(matches) >= limit:
                break
    except Exception as e:
        return error_tool_result(
            f"glob_search failed for pattern {params.pattern}",
            "GLOB_SEARCH_FAILED",
            {"path": params.path, "pattern": params.pattern, "message": str(e)},
        )

    limited = truncate_text("\n".join(matches), params.maxChars or _DEFAULT_MAX_CHARS)
    return ok_tool_result(
        f"Found {len(matches)} files matching {params.pattern}",
        {
            "path": params.path,
            "pattern": params.pattern,
            "matchCount": len(matches),
            "truncated": limited["truncated"],
            "matches": matches,
            "content": limited["text"],
        },
    )


glob_search_tool = define_tool(
    name="glob_search",
    description="Find files matching a glob pattern under an absolute directory.",
    parameters=_GlobSearchParams,
    invoke=_invoke,
)
