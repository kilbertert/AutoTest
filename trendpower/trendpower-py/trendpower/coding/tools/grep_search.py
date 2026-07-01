"""grep_search tool — search file contents using ripgrep (rg)."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from pydantic import BaseModel, Field

from ...foundation import AbortSignal, define_tool
from .tool_result import error_tool_result, ok_tool_result
from .tool_utils import ensure_directory_path, truncate_text

_DEFAULT_LIMIT = 200
_DEFAULT_MAX_CHARS = 12000


class _GrepSearchParams(BaseModel):
    description: str = Field(
        description="Explain why you want to search file contents. Always place `description` as the first parameter."
    )
    path: str = Field(description="The absolute directory path to search within.")
    pattern: str = Field(description="Text or regex pattern to search for.")
    glob: Optional[str] = Field(default=None, description="Optional glob filter, for example *.ts.")
    caseSensitive: Optional[bool] = Field(default=None, description="Whether the search should be case-sensitive.")
    limit: Optional[int] = Field(default=None, ge=1, description="Maximum number of matches to return.")
    maxChars: Optional[int] = Field(default=None, ge=1, description="Maximum characters to return.")


async def _invoke(params: _GrepSearchParams, signal: Optional[AbortSignal] = None) -> dict:
    dir_check = ensure_directory_path(params.path)
    if not dir_check["ok"]:
        return error_tool_result(
            dir_check["error"],
            "INVALID_DIRECTORY",
            {"path": params.path, "pattern": params.pattern, "glob": params.glob},
        )

    cmd: List[str] = ["rg", "--line-number", "--no-heading"]
    if not params.caseSensitive:
        cmd.append("--ignore-case")
    if params.glob:
        cmd.extend(["--glob", params.glob])
    cmd.extend([params.pattern, params.path])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        return error_tool_result(
            "Failed to run 'rg' (ripgrep). Please ensure ripgrep is installed and available in PATH.",
            "RG_NOT_FOUND",
            {"path": params.path, "pattern": params.pattern, "message": str(e)},
        )
    except Exception as e:
        return error_tool_result(
            "grep_search failed to execute.",
            "GREP_EXEC_FAILED",
            {"path": params.path, "pattern": params.pattern, "message": str(e)},
        )

    remove_listener = None
    if signal is not None:
        def _kill() -> None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

        remove_listener = signal.add_listener(_kill)

    try:
        stdout_bytes, stderr_bytes = await proc.communicate()
    finally:
        if remove_listener is not None:
            remove_listener()

    exit_code = proc.returncode
    if exit_code not in (0, 1):
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return error_tool_result(
            f"grep_search failed with exit code {exit_code}",
            "GREP_FAILED",
            {
                "path": params.path,
                "pattern": params.pattern,
                "glob": params.glob,
                "exitCode": exit_code,
                "stderr": stderr,
            },
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    lines = [ln for ln in stdout.split("\n") if ln]
    capped = lines[: (params.limit or _DEFAULT_LIMIT)]
    limited = truncate_text("\n".join(capped), params.maxChars or _DEFAULT_MAX_CHARS)

    return ok_tool_result(
        f"Found {len(lines)} matches for {params.pattern}",
        {
            "path": params.path,
            "pattern": params.pattern,
            "glob": params.glob,
            "caseSensitive": bool(params.caseSensitive),
            "totalMatches": len(lines),
            "shownMatches": len(capped),
            "truncated": limited["truncated"] or len(capped) < len(lines),
            "matches": capped,
            "content": limited["text"],
        },
    )


grep_search_tool = define_tool(
    name="grep_search",
    description="Search file contents with ripgrep under an absolute directory.",
    parameters=_GrepSearchParams,
    invoke=_invoke,
)
