"""Tests for transcript-derived file entries."""

from __future__ import annotations

import os

from trendpower_tui.tui.file_view import build_file_entries


def _assistant(*tool_uses):
    return {"role": "assistant", "content": list(tool_uses)}


def _tu(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


def test_collects_write_and_str_replace_paths(tmp_path):
    cwd = str(tmp_path)
    a = os.path.join(cwd, "a.py")
    b = os.path.join(cwd, "sub", "b.py")
    messages = [
        _assistant(
            _tu("write_file", path=a, content="x"),
            _tu("str_replace", path=b, old="x", new="y"),
            _tu("read_file", path=os.path.join(cwd, "c.py")),  # non-mutating, ignored
        )
    ]
    entries = build_file_entries(messages, cwd)
    assert [e.path for e in entries] == [a, b]
    assert [e.display for e in entries] == ["a.py", os.path.join("sub", "b.py")]


def test_dedupes_and_preserves_first_seen_order(tmp_path):
    cwd = str(tmp_path)
    a = os.path.join(cwd, "a.py")
    b = os.path.join(cwd, "b.py")
    messages = [
        _assistant(_tu("write_file", path=a, content="1")),
        _assistant(_tu("write_file", path=b, content="2")),
        _assistant(_tu("str_replace", path=a, old="1", new="3")),  # repeat of a
    ]
    assert [e.path for e in build_file_entries(messages, cwd)] == [a, b]


def test_apply_patch_paths_from_headers(tmp_path):
    cwd = str(tmp_path)
    target = os.path.join(cwd, "patched.py")
    patch = f"--- a/{target}\n+++ b/{target}\n@@ -1 +1 @@\n-x\n+y\n"
    messages = [_assistant(_tu("apply_patch", patch=patch))]
    assert [e.path for e in build_file_entries(messages, cwd)] == [target]


def test_relative_paths_are_skipped(tmp_path):
    cwd = str(tmp_path)
    messages = [_assistant(_tu("write_file", path="relative/x.py", content="x"))]
    assert build_file_entries(messages, cwd) == []
