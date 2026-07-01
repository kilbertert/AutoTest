"""Compact slash-command suggestion list."""

from __future__ import annotations

from textual.widgets import Static

from ..command_registry import SlashCommand, filter_commands


class CommandList(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(" ", *args, **kwargs)
        self.display = False

    def set_commands(self, commands: list[SlashCommand], query: str) -> None:
        matches = filter_commands(commands, query)[:8]
        if not matches or not query:
            self.display = False
            self.update(" ")
            return
        self.display = True
        lines = ["Commands"]
        lines.extend(f"  /{command.name:<16} {command.description}" for command in matches)
        self.update("\n".join(lines))
