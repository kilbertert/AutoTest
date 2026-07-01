"""Read/write helpers for conversation sessions under ``$trendpower_HOME/sessions``.

A session is a single JSON file holding the agent transcript (the real
user/assistant/tool messages — not the ephemeral system notices the TUI prints)
plus light metadata so ``/resume`` can present a pickable list without parsing
every transcript.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import get_trendpower_home_path

SESSIONS_DIRNAME = "sessions"
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SessionMeta:
    id: str
    title: str
    created: float
    updated: float
    message_count: int
    model: str | None
    cwd: str | None
    path: Path


def sessions_dir() -> Path:
    return get_trendpower_home_path() / SESSIONS_DIRNAME


def new_session_id() -> str:
    """Timestamp-prefixed id so files sort chronologically on disk."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime()) + f"-{os.getpid() % 10000:04d}"


def session_title(messages: list[dict[str, Any]]) -> str:
    """Derive a human-readable title from the first user text message."""
    for message in messages:
        if message.get("role") != "user":
            continue
        text = _first_text(message)
        if text:
            collapsed = " ".join(text.split())
            return collapsed if len(collapsed) <= 80 else collapsed[:77] + "…"
    return "(untitled session)"


def save_session(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    cwd: str | None = None,
    created: float | None = None,
) -> SessionMeta:
    target_dir = sessions_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{session_id}.json"

    now = time.time()
    payload = {
        "schema": _SCHEMA_VERSION,
        "id": session_id,
        "created": created if created is not None else now,
        "updated": now,
        "model": model,
        "cwd": cwd,
        "title": session_title(messages),
        "messages": messages,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=target_dir)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        tmp_path.replace(target)
    finally:
        with suppress(OSError):
            tmp_path.unlink()

    return _meta_from_payload(payload, target)


def list_sessions() -> list[SessionMeta]:
    """All saved sessions, most-recently-updated first. Skips unreadable files."""
    directory = sessions_dir()
    if not directory.is_dir():
        return []
    metas: list[SessionMeta] = []
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        metas.append(_meta_from_payload(payload, path))
    metas.sort(key=lambda meta: meta.updated, reverse=True)
    return metas


def load_session(session_id: str) -> tuple[SessionMeta, list[dict[str, Any]]]:
    path = sessions_dir() / f"{session_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = []
    return _meta_from_payload(payload, path), messages


def delete_session(session_id: str) -> bool:
    path = sessions_dir() / f"{session_id}.json"
    try:
        path.unlink()
        return True
    except OSError:
        return False


# --- internals --------------------------------------------------------------


def _meta_from_payload(payload: dict[str, Any], path: Path) -> SessionMeta:
    messages = payload.get("messages")
    count = len(messages) if isinstance(messages, list) else int(payload.get("message_count") or 0)
    created = _as_float(payload.get("created"))
    updated = _as_float(payload.get("updated")) or created
    return SessionMeta(
        id=str(payload.get("id") or path.stem),
        title=str(payload.get("title") or "(untitled session)"),
        created=created,
        updated=updated,
        message_count=count,
        model=payload.get("model"),
        cwd=payload.get("cwd"),
        path=path,
    )


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _first_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    return text
    return ""
