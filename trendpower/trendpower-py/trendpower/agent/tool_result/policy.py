"""Per-tool result formatting policy."""

from __future__ import annotations

from typing import Optional, TypedDict


class ToolResultPolicy(TypedDict, total=False):
    preferSummaryOnly: bool
    includeData: bool
    maxStringLength: Optional[int]
    uiSummaryOnly: bool


_DEFAULT_POLICY: ToolResultPolicy = {
    "preferSummaryOnly": False,
    "includeData": True,
    "maxStringLength": 4000,
}


def get_tool_result_policy(tool_name: str) -> ToolResultPolicy:
    if tool_name in ("list_files", "glob_search", "grep_search", "file_info", "mkdir", "move_path"):
        return {
            "preferSummaryOnly": True,
            "includeData": False,
            "maxStringLength": 1000,
            "uiSummaryOnly": True,
        }
    if tool_name == "read_file":
        return {
            "preferSummaryOnly": False,
            "includeData": True,
            "maxStringLength": 12000,
        }
    if tool_name in ("apply_patch", "write_file", "str_replace"):
        return {
            "preferSummaryOnly": False,
            "includeData": True,
            "maxStringLength": 4000,
        }
    if tool_name == "task":
        # The sub-agent report is the compressed product of a whole inner run;
        # it is worth keeping more of it than a normal tool result.
        return {
            "preferSummaryOnly": True,
            "includeData": False,
            "maxStringLength": 8000,
        }
    return dict(_DEFAULT_POLICY)
