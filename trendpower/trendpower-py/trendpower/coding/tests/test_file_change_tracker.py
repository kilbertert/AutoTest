"""Tests for the file-change tracker middleware."""

from __future__ import annotations

from pathlib import Path

from trendpower.coding.file_change_tracker import create_file_change_tracker


def _ok(data=None):
    return {"ok": True, "summary": "", "data": data or {}}


async def _register_write(mw, path: str) -> None:
    await mw.afterToolUse(
        {"toolUse": {"name": "write_file", "input": {"path": path}}, "toolResult": _ok()}
    )


async def test_agent_own_write_does_not_inject(tmp_path: Path) -> None:
    mw = create_file_change_tracker()
    f = tmp_path / "x.py"
    f.write_text("v1", encoding="utf-8")
    await _register_write(mw, str(f))

    ctx = {"prompt": "BASE"}
    assert await mw.beforeModel({"modelContext": ctx, "agentContext": {}}) is None


async def test_external_edit_injected_once(tmp_path: Path) -> None:
    mw = create_file_change_tracker()
    f = tmp_path / "x.py"
    f.write_text("v1", encoding="utf-8")
    await _register_write(mw, str(f))

    f.write_text("USER_EDIT", encoding="utf-8")
    ctx = {"prompt": "BASE"}
    result = await mw.beforeModel({"modelContext": ctx, "agentContext": {}})
    assert result is not None
    prompt = result["prompt"]
    assert prompt.startswith("BASE")
    assert "<files_changed_by_user>" in prompt
    assert "USER_EDIT" in prompt
    assert str(f) in prompt

    # No further change -> no re-injection.
    assert await mw.beforeModel({"modelContext": ctx, "agentContext": {}}) is None


async def test_apply_patch_changed_files_tracked(tmp_path: Path) -> None:
    mw = create_file_change_tracker()
    f = tmp_path / "patched.py"
    f.write_text("v1", encoding="utf-8")
    await mw.afterToolUse(
        {
            "toolUse": {"name": "apply_patch", "input": {"patch": "..."}},
            "toolResult": _ok({"changedFiles": [str(f)]}),
        }
    )
    f.write_text("EDITED", encoding="utf-8")
    result = await mw.beforeModel({"modelContext": {"prompt": "P"}, "agentContext": {}})
    assert result is not None and "EDITED" in result["prompt"]


async def test_failed_write_not_tracked(tmp_path: Path) -> None:
    mw = create_file_change_tracker()
    f = tmp_path / "y.py"
    await mw.afterToolUse(
        {
            "toolUse": {"name": "write_file", "input": {"path": str(f)}},
            "toolResult": {"ok": False, "summary": "nope"},
        }
    )
    f.write_text("appeared later", encoding="utf-8")
    assert await mw.beforeModel({"modelContext": {"prompt": "P"}, "agentContext": {}}) is None
