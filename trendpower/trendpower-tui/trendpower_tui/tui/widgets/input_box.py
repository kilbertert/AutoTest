"""Input box with minimal slash-command/history support."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Input


class CommandSubmitted(Message):
    def __init__(self, text: str, requested_skill: str | None = None) -> None:
        self.text = text
        self.requested_skill = requested_skill
        super().__init__()


class InputBox(Input):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, placeholder="Ask Trendpower, or type /help...", **kwargs)
        self._history: list[str] = []
        self._history_index: int | None = None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        if not text:
            return
        self._history.append(text)
        self._history_index = None
        self.value = ""
        self.post_message(CommandSubmitted(text=text))

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.post_message(CommandInputChanged(event.value))

    def key_up(self) -> None:
        if not self._history:
            return
        if self._history_index is None:
            self._history_index = len(self._history) - 1
        else:
            self._history_index = max(0, self._history_index - 1)
        self.value = self._history[self._history_index]
        self.cursor_position = len(self.value)

    def key_down(self) -> None:
        if self._history_index is None:
            return
        self._history_index += 1
        if self._history_index >= len(self._history):
            self._history_index = None
            self.value = ""
        else:
            self.value = self._history[self._history_index]
        self.cursor_position = len(self.value)


class CommandInputChanged(Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()
