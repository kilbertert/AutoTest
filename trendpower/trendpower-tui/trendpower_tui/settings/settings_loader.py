"""Layered settings loader matching ``src/cli/settings/settings-loader.ts``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .settings import Settings


def _default_trendpower_home() -> Path:
    value = os.environ.get("TRENDPOWER_HOME", "").strip()
    return Path(value).expanduser() if value else Path.home() / ".trendpower"


def _read_json_file(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print(f"[trendpower] Could not read {path}; skipping settings layer.")
        return None


def _load_layer(path: Path) -> Settings:
    data = _read_json_file(path)
    if data is None:
        return Settings()
    try:
        return Settings.model_validate(data)
    except ValidationError:
        print(f"[trendpower] Invalid settings at {path}; ignoring layer.")
        return Settings()


def _merge_settings_layers(layers: list[Settings]) -> Settings:
    merged_top: dict[str, Any] = {}
    for layer in layers:
        rec = layer.model_dump(exclude_none=True)
        for key, value in rec.items():
            if key != "permissions":
                merged_top[key] = value

    allow: set[str] = set()
    permissions_rest: dict[str, Any] = {}
    for layer in layers:
        if not layer.permissions:
            continue
        permissions = layer.permissions.model_dump(exclude_none=True)
        for item in permissions.get("allow", []) or []:
            if isinstance(item, str):
                allow.add(item)
        for key, value in permissions.items():
            if key != "allow":
                permissions_rest[key] = value

    out = dict(merged_top)
    if allow or permissions_rest:
        permissions = dict(permissions_rest)
        if allow:
            permissions["allow"] = list(allow)
        out["permissions"] = permissions
    return Settings.model_validate(out)


class SettingsLoader:
    def __init__(self, trendpower_home: str | Path | None = None) -> None:
        self.trendpower_home = Path(trendpower_home).expanduser() if trendpower_home else _default_trendpower_home()

    def user_settings_path(self) -> Path:
        return self.trendpower_home / "settings.json"

    def project_settings_path(self, cwd: str | Path) -> Path:
        return Path(cwd) / ".trendpower" / "settings.json"

    def project_local_settings_path(self, cwd: str | Path) -> Path:
        return Path(cwd) / ".trendpower" / "settings.local.json"

    async def load(self, cwd: str | Path) -> Settings:
        paths = [
            self.user_settings_path(),
            self.project_settings_path(cwd),
            self.project_local_settings_path(cwd),
        ]
        return _merge_settings_layers([_load_layer(path) for path in paths])

    async def load_allow_list(self, cwd: str | Path) -> set[str]:
        settings = await self.load(cwd)
        allow = settings.permissions.allow if settings.permissions and settings.permissions.allow else []
        return set(allow)
