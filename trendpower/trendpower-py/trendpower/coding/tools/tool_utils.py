"""Path/text helpers shared by coding tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


def ensure_absolute_path(path: str) -> Dict[str, Any]:
    # The TS source uses `path.startsWith("/")` (POSIX-only). We use
    # `os.path.isabs` instead so the same code works on Windows (C:\...) and
    # POSIX (/...) — required since this is a Python port, not Bun-on-Unix.
    if not os.path.isabs(path):
        return {"ok": False, "error": f"Path must be absolute: {path}"}
    return {"ok": True, "path": path}


def ensure_directory_path(path: str) -> Dict[str, Any]:
    absolute = ensure_absolute_path(path)
    if not absolute["ok"]:
        return absolute
    try:
        p = Path(path)
        st = p.stat()
        if not p.is_dir():
            return {"ok": False, "error": f"Path exists but is not a directory: {path}"}
        return {"ok": True, "path": path}
    except FileNotFoundError:
        return {"ok": False, "error": f"Directory does not exist: {path}"}
    except OSError as e:
        return {"ok": False, "error": f"Directory is inaccessible: {path} ({e})"}


def is_within_directory(root: str, target: str) -> bool:
    rel = os.path.relpath(os.path.realpath(target), os.path.realpath(root))
    if rel == "":
        return True
    sep = os.sep
    return not rel.startswith("..") and f"..{sep}" not in rel


def truncate_text(text: str, max_chars: int) -> Dict[str, Any]:
    if len(text) <= max_chars:
        return {"text": text, "truncated": False}
    return {
        "text": f"{text[:max_chars]}\n... [truncated {len(text) - max_chars} chars]",
        "truncated": True,
    }
