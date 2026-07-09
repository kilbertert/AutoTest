"""Schema and pure merge helpers for ``settings.json`` files."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PermissionsSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    allow: list[str] | None = None


class Settings(BaseModel):
    model_config = ConfigDict(extra="allow")

    permissions: PermissionsSettings | None = None


def append_tool_to_allow_list(document: dict[str, Any], tool_name: str) -> dict[str, Any]:
    """Return a copy of ``document`` with ``tool_name`` added once."""

    raw_permissions = document.get("permissions")
    permissions = dict(raw_permissions) if isinstance(raw_permissions, dict) else {}
    raw_allow = permissions.get("allow")
    existing = [item for item in raw_allow if isinstance(item, str)] if isinstance(raw_allow, list) else []
    permissions["allow"] = existing if tool_name in existing else [*existing, tool_name]
    return {**document, "permissions": permissions}
