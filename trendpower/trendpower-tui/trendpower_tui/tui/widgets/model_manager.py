"""Modal screen for `/model` — list, switch, add, remove configured models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from ...config import TrendpowerConfig, ModelEntry


@dataclass(frozen=True)
class ModelManagerAction:
    """Result returned to the App when the user dismisses the screen.

    ``kind`` is one of:
      - ``"switch"`` — user picked an existing model as default. ``payload`` is
        the chosen model name.
      - ``"add"`` — user pressed `a` to add a new model. App should push the
        wizard, then call ``ModelManagerScreen`` again with the updated config.
      - ``"remove"`` — user pressed `d`. ``payload`` is the model name.
      - ``"none"`` — user dismissed without changes (Esc).
    """

    kind: str
    payload: str | None = None


class ModelManagerScreen(ModalScreen[ModelManagerAction]):
    BINDINGS = [
        ("up", "move(-1)", "Up"),
        ("down", "move(1)", "Down"),
        ("enter", "switch", "Switch"),
        ("a", "add", "Add"),
        ("d", "remove", "Remove"),
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ModelManagerScreen {
        align: center middle;
    }
    ModelManagerScreen #manager-box {
        width: 80%;
        max-width: 110;
        padding: 1 2;
        border: round #6fd6ff;
        background: #121822;
        color: #f4fbff;
    }
    ModelManagerScreen .hint {
        color: #8fa0ad;
        margin-top: 1;
    }
    ModelManagerScreen #manager-feedback {
        color: #ff8b8b;
        margin-top: 1;
    }
    """

    def __init__(self, config: TrendpowerConfig) -> None:
        super().__init__()
        self.config = config
        self.index = 0
        self._feedback = ""
        default_name = config.defaultModel or (config.models[0].name if config.models else None)
        if default_name is not None:
            for i, entry in enumerate(config.models):
                if entry.name == default_name:
                    self.index = i
                    break

    def compose(self) -> ComposeResult:
        with Vertical(id="manager-box"):
            yield Static("[bold cyan]Trendpower · /model[/bold cyan]", id="manager-title")
            yield Static(self._body(), id="manager-body")
            yield Static(self._hint(), id="manager-hint", classes="hint")
            yield Static(self._feedback, id="manager-feedback")

    def _refresh(self) -> None:
        self.query_one("#manager-body", Static).update(self._body())
        self.query_one("#manager-hint", Static).update(self._hint())
        self.query_one("#manager-feedback", Static).update(self._feedback)

    def _body(self) -> str:
        if not self.config.models:
            return "[dim]当前未配置任何模型。按 `a` 添加。[/dim]"
        default_name = self.config.defaultModel or self.config.models[0].name
        lines: list[str] = ["[bold]已配置的模型：[/bold]", ""]
        for i, entry in enumerate(self.config.models):
            is_focused = i == self.index
            is_default = entry.name == default_name
            marker = "❯ " if is_focused else "  "
            badge = " [green](default)[/green]" if is_default else ""
            color = "cyan" if is_focused else "white"
            tail = _mask_url(entry.baseURL)
            lines.append(
                f"[{color}]{marker}{entry.name}{badge}[/{color}]\n"
                f"     [dim]provider={entry.provider}  baseURL={tail}[/dim]"
            )
        return "\n".join(lines)

    def _hint(self) -> str:
        return (
            "↑/↓ 选择 · Enter 设为默认 · a 添加 · d 删除 · Esc 关闭"
        )

    def action_move(self, delta: int) -> None:
        if not self.config.models:
            return
        self.index = (self.index + delta) % len(self.config.models)
        self._refresh()

    def action_switch(self) -> None:
        if not self.config.models:
            self._feedback = "[red]没有可切换的模型。先按 `a` 添加。[/red]"
            self._refresh()
            return
        chosen = self.config.models[self.index].name
        self.dismiss(ModelManagerAction(kind="switch", payload=chosen))

    def action_add(self) -> None:
        self.dismiss(ModelManagerAction(kind="add"))

    def action_remove(self) -> None:
        if not self.config.models:
            return
        if len(self.config.models) <= 1:
            self._feedback = "[red]不能删除最后一个模型。至少保留一个配置。[/red]"
            self._refresh()
            return
        target = self.config.models[self.index].name
        self.dismiss(ModelManagerAction(kind="remove", payload=target))

    def action_cancel(self) -> None:
        self.dismiss(ModelManagerAction(kind="none"))

    def on_key(self, event: events.Key) -> None:
        # Swallow stray characters so they do not leak into the InputBox once
        # we close. The named bindings above already cover the real actions.
        pass


def _mask_url(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 60:
        return value
    return value[:40] + "..." + value[-12:]


def apply_switch(config: TrendpowerConfig, model_name: str) -> TrendpowerConfig:
    if all(entry.name != model_name for entry in config.models):
        return config
    return TrendpowerConfig(models=list(config.models), defaultModel=model_name)


def apply_remove(config: TrendpowerConfig, model_name: str) -> TrendpowerConfig:
    remaining = [entry for entry in config.models if entry.name != model_name]
    if not remaining:
        return config
    default = config.defaultModel
    if default == model_name:
        default = remaining[0].name
    return TrendpowerConfig(models=remaining, defaultModel=default)


def apply_append(config: TrendpowerConfig, entry: ModelEntry) -> TrendpowerConfig:
    # If a model with the same name already exists, replace it rather than
    # duplicating — matches the CLI `add` semantics (last-write-wins by name).
    models = [m for m in config.models if m.name != entry.name]
    models.append(entry)
    default = config.defaultModel or entry.name
    return TrendpowerConfig(models=models, defaultModel=default)


def _ensure_models(_value: Any) -> None:  # placeholder for future extension
    return None
