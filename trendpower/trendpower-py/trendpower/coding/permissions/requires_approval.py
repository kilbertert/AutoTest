"""Tool names that require interactive approval (unless allowed in project settings)."""

from __future__ import annotations

from typing import List

CODING_TOOLS_REQUIRING_APPROVAL: List[str] = [
    "bash",
    "write_file",
    "str_replace",
    "apply_patch",
    "mkdir",
    "move_path",
]
