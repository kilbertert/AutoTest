"""Right-hand code panel: a file list plus an editable viewer.

Lists every file the agent has written/edited this conversation (left side keeps
the execution steps). Clicking a file loads its current on-disk content into an
editable text area; pressing the confirm button (or Ctrl+S) writes the edits back
to disk. Because the core `file_change_tracker` middleware re-reads touched files
before each model call, both in-panel saves and external-editor edits are picked
up on the next turn.
"""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, ListItem, ListView, Static, TextArea

from ..file_view import FileEntry

# Map file extensions to TextArea syntax-highlight languages. Highlighting only
# kicks in when the matching tree-sitter grammar is installed; we fall back to
# plain text otherwise (see `_apply_language`).
_LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".xml": "xml",
}


class FileSaved(Message):
    """Posted after the user saves an edited file from the panel."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__()


class CodePanel(Vertical):
    """File list + editable content viewer for agent-touched files."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.display = False
        self._entries: list[FileEntry] = []
        self._current: str | None = None
        self._loaded_text: str = ""
        self._suppress_highlight = False

    def compose(self) -> ComposeResult:
        yield Static("FILES", id="code-title")
        yield ListView(id="file-list")
        yield TextArea("", id="code-editor", read_only=False, show_line_numbers=True)
        with Horizontal(id="code-actions"):
            yield Static("", id="code-status")
            yield Button("确认修改 (Ctrl+S)", id="code-save", variant="primary")

    # --- public API -------------------------------------------------------

    def set_files(self, entries: list[FileEntry]) -> None:
        """Refresh the file list from the latest transcript-derived entries."""

        if not entries:
            self.display = False
            self._entries = []
            self._current = None
            return

        self.display = True
        paths_changed = [e.path for e in entries] != [e.path for e in self._entries]
        self._entries = entries

        if paths_changed:
            self._rebuild_list()

        current_paths = {e.path for e in entries}
        if self._current not in current_paths:
            # Default to the most recently touched file (last in the list).
            self._load_file(entries[-1].path, focus_list_index=len(entries) - 1)
        elif not self._is_dirty():
            # The agent may have rewritten the file we're viewing; refresh it
            # unless the user has unsaved edits (their work wins until saved).
            self._reload_current()

    def save_current(self) -> bool:
        """Write the editor's content back to disk. Returns True on success."""

        if self._current is None:
            return False
        editor = self.query_one("#code-editor", TextArea)
        try:
            with open(self._current, "w", encoding="utf-8") as fh:
                fh.write(editor.text)
        except OSError as error:
            self._set_status(f"保存失败: {error}", error=True)
            return False
        self._loaded_text = editor.text
        self._set_status("已保存 ✓")
        self.post_message(FileSaved(self._current))
        return True

    # --- internal helpers -------------------------------------------------

    def _rebuild_list(self) -> None:
        list_view = self.query_one("#file-list", ListView)
        self._suppress_highlight = True
        try:
            list_view.clear()
            for entry in self._entries:
                list_view.append(ListItem(Static(entry.display)))
        finally:
            self._suppress_highlight = False

    def _index_of(self, path: str) -> int:
        return next((i for i, e in enumerate(self._entries) if e.path == path), -1)

    def _load_file(self, path: str, focus_list_index: int | None = None) -> None:
        editor = self.query_one("#code-editor", TextArea)
        content = self._read(path)
        self._current = path
        self._loaded_text = content if content is not None else ""
        self._apply_language(path, editor)
        editor.load_text(self._loaded_text)
        self._set_title(path, missing=content is None)
        self._set_status("")
        if focus_list_index is not None:
            list_view = self.query_one("#file-list", ListView)
            self._suppress_highlight = True
            try:
                list_view.index = focus_list_index
            finally:
                self._suppress_highlight = False

    def _reload_current(self) -> None:
        if self._current is not None:
            self._load_file(self._current, focus_list_index=self._index_of(self._current))

    def _is_dirty(self) -> bool:
        try:
            editor = self.query_one("#code-editor", TextArea)
        except Exception:
            return False
        return editor.text != self._loaded_text

    @staticmethod
    def _read(path: str) -> str | None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except (OSError, UnicodeDecodeError):
            return None

    def _apply_language(self, path: str, editor: TextArea) -> None:
        language = _LANGUAGE_BY_EXT.get(os.path.splitext(path)[1].lower())
        try:
            editor.language = language
        except Exception:
            # Grammar not installed for this language; stay plain text.
            try:
                editor.language = None
            except Exception:
                pass

    def _set_title(self, path: str, missing: bool = False) -> None:
        entry = next((e for e in self._entries if e.path == path), None)
        label = entry.display if entry else path
        suffix = "  (文件不存在)" if missing else ""
        self.query_one("#code-title", Static).update(f"FILES · {label}{suffix}")

    def _set_status(self, text: str, error: bool = False) -> None:
        widget = self.query_one("#code-status", Static)
        if error:
            widget.update(f"[#ff8b8b]{text}[/#ff8b8b]")
        else:
            widget.update(f"[#7cd992]{text}[/#7cd992]" if text else "")

    # --- events -----------------------------------------------------------

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if self._suppress_highlight or event.list_view.id != "file-list":
            return
        index = event.list_view.index
        if index is None or index < 0 or index >= len(self._entries):
            return
        path = self._entries[index].path
        if path != self._current:
            self._load_file(path)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "file-list":
            return
        index = event.list_view.index
        if index is not None and 0 <= index < len(self._entries):
            self._load_file(self._entries[index].path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "code-save":
            event.stop()
            self.save_current()
