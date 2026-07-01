"""Settings writer with project-local persistence for approvals."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .settings import Settings, append_tool_to_allow_list
from .settings_loader import SettingsLoader


class SettingsWriter:
    def __init__(self, loader: SettingsLoader | None = None) -> None:
        self.loader = loader or SettingsLoader()

    async def append_allowed_tool(self, cwd: str | Path, tool_name: str) -> None:
        path = self.loader.project_local_settings_path(cwd)
        base: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                try:
                    base = Settings.model_validate(data).model_dump(exclude_none=True)
                except ValidationError:
                    if isinstance(data, dict):
                        print("[trendpower] Merging into settings.local.json with relaxed parse; fixing shape on write.")
                        base = data
            except Exception:
                print(f"[trendpower] Could not parse {path}; overwriting with new permissions.")

        merged = append_tool_to_allow_list(base, tool_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            tmp_path.replace(path)
        finally:
            with suppress(OSError):
                tmp_path.unlink()
