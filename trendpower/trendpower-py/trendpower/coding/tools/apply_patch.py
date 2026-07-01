"""apply_patch tool — apply a unified diff to one or more files."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Literal, TypedDict

from pydantic import BaseModel, Field

from ...foundation import define_tool
from .tool_result import error_tool_result, ok_tool_result

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@$")


class _HunkLine(TypedDict):
    type: Literal["context", "delete", "add"]
    text: str


class _PatchHunk(TypedDict):
    oldStart: int
    oldCount: int
    newStart: int
    newCount: int
    lines: List[_HunkLine]


class _PatchFile(TypedDict):
    oldPath: str
    newPath: str
    hunks: List[_PatchHunk]


def _normalize_patch_path(raw_path: str) -> str:
    if raw_path.startswith("b/"):
        return raw_path[2:]
    if raw_path.startswith("a/"):
        return raw_path[2:]
    return raw_path


def _parse_patch(patch: str) -> List[_PatchFile]:
    lines = patch.replace("\r\n", "\n").split("\n")
    files: List[_PatchFile] = []
    current: _PatchFile | None = None
    index = 0

    while index < len(lines):
        line = lines[index] if index < len(lines) else ""
        if line.startswith("--- "):
            nxt = lines[index + 1] if index + 1 < len(lines) else ""
            if not nxt.startswith("+++ "):
                raise ValueError("Patch is missing +++ header after --- header.")
            current = {
                "oldPath": _normalize_patch_path(line[4:].strip()),
                "newPath": _normalize_patch_path(nxt[4:].strip()),
                "hunks": [],
            }
            files.append(current)
            index += 2
            continue

        header = _HUNK_HEADER.match(line)
        if header:
            if current is None:
                raise ValueError("Encountered hunk before file header.")
            hunk: _PatchHunk = {
                "oldStart": int(header.group(1)),
                "oldCount": int(header.group(2)) if header.group(2) is not None else 1,
                "newStart": int(header.group(3)),
                "newCount": int(header.group(4)) if header.group(4) is not None else 1,
                "lines": [],
            }
            index += 1
            while index < len(lines):
                hunk_line = lines[index]
                if hunk_line.startswith("@@ ") or hunk_line.startswith("--- "):
                    break
                if hunk_line == "\\ No newline at end of file":
                    index += 1
                    continue
                if hunk_line == "":
                    index += 1
                    continue
                prefix = hunk_line[0]
                text = hunk_line[1:]
                if prefix == " ":
                    hunk["lines"].append({"type": "context", "text": text})
                elif prefix == "-":
                    hunk["lines"].append({"type": "delete", "text": text})
                elif prefix == "+":
                    hunk["lines"].append({"type": "add", "text": text})
                else:
                    raise ValueError(f"Unsupported hunk line: {hunk_line}")
                index += 1
            current["hunks"].append(hunk)
            continue

        index += 1

    if len(files) == 0:
        raise ValueError("Patch does not contain any file changes.")
    return files


def _validate_hunk_counts(hunk: _PatchHunk, file_path: str) -> None:
    old_seen = 0
    new_seen = 0
    for line in hunk["lines"]:
        if line["type"] == "context":
            old_seen += 1
            new_seen += 1
        elif line["type"] == "delete":
            old_seen += 1
        else:
            new_seen += 1
    if old_seen != hunk["oldCount"] or new_seen != hunk["newCount"]:
        raise ValueError(
            f"Hunk count mismatch for {file_path} at @@ -{hunk['oldStart']},{hunk['oldCount']} "
            f"+{hunk['newStart']},{hunk['newCount']} @@. Observed old={old_seen}, new={new_seen}."
        )


def _apply_hunks(original: str, file: _PatchFile) -> str:
    source_lines: List[str] = [] if original == "" else original.replace("\r\n", "\n").split("\n")
    output: List[str] = []
    source_index = 0

    for hunk in file["hunks"]:
        _validate_hunk_counts(hunk, file["newPath"])
        expected_index = hunk["oldStart"] - 1

        while source_index < expected_index:
            output.append(source_lines[source_index] if source_index < len(source_lines) else "")
            source_index += 1

        for line in hunk["lines"]:
            if line["type"] == "context":
                actual = source_lines[source_index] if source_index < len(source_lines) else ""
                if actual != line["text"]:
                    raise ValueError(
                        f"Context mismatch in {file['newPath']} at line {source_index + 1}: "
                        f"expected {line['text']!r}, got {actual!r}"
                    )
                output.append(actual)
                source_index += 1
            elif line["type"] == "delete":
                actual = source_lines[source_index] if source_index < len(source_lines) else ""
                if actual != line["text"]:
                    raise ValueError(
                        f"Delete mismatch in {file['newPath']} at line {source_index + 1}: "
                        f"expected {line['text']!r}, got {actual!r}"
                    )
                source_index += 1
            else:
                output.append(line["text"])

    while source_index < len(source_lines):
        output.append(source_lines[source_index])
        source_index += 1

    return "\n".join(output)


class _ApplyPatchParams(BaseModel):
    description: str = Field(
        description="Explain why you want to apply the patch. Always place `description` as the first parameter."
    )
    patch: str = Field(description="Unified diff patch content with --- and +++ headers. Must use absolute paths.")


async def _invoke(params: _ApplyPatchParams) -> Dict:
    try:
        files = _parse_patch(params.patch)
        changed_files: List[str] = []

        for file in files:
            if not os.path.isabs(file["newPath"]):
                return error_tool_result(
                    f"Patch paths must be absolute. Received: {file['newPath']}",
                    "INVALID_PATCH_PATH",
                    {"oldPath": file["oldPath"], "newPath": file["newPath"]},
                )
            if file["newPath"] == "/dev/null":
                return error_tool_result(
                    "File deletion (+++ /dev/null) is currently not supported by apply_patch.",
                    "DELETE_NOT_SUPPORTED",
                    {"oldPath": file["oldPath"], "newPath": file["newPath"]},
                )

            target = Path(file["newPath"])
            original = target.read_text(encoding="utf-8") if target.exists() else ""
            updated = _apply_hunks(original, file)

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding="utf-8")
            changed_files.append(file["newPath"])

        return ok_tool_result(
            f"Applied patch to {len(changed_files)} file(s).",
            {"fileCount": len(changed_files), "changedFiles": changed_files},
        )
    except Exception as e:
        return error_tool_result(str(e), "PATCH_APPLY_FAILED")


apply_patch_tool = define_tool(
    name="apply_patch",
    description=(
        "Apply a unified diff patch to one or more files using absolute paths in the patch headers. "
        "Note: File deletion is not supported (will fail if +++ /dev/null is used)."
    ),
    parameters=_ApplyPatchParams,
    invoke=_invoke,
)
