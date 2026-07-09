"""First-run wizard — Python port of `bootstrap/first-run-wizard.tsx`.

Opens automatically when the user starts ``trendpower`` with no models
configured. Walks them through provider → API key → model name → confirm,
then writes ``config.yaml`` and signals the App to retry runner creation.
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ...config import ModelEntry
from ...model_providers import MODEL_PROVIDERS


def _mask(secret: str) -> str:
    if not secret:
        return ""
    tail = secret[-4:] if len(secret) >= 4 else secret
    return ("*" * max(0, len(secret) - 4)) + tail


class FirstRunWizardScreen(ModalScreen[ModelEntry | None]):
    """Three-step wizard. Dismisses with the saved `ModelEntry` or `None`."""

    BINDINGS = [
        ("up", "move(-1)", "Up"),
        ("down", "move(1)", "Down"),
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    FirstRunWizardScreen {
        align: center middle;
    }
    FirstRunWizardScreen #wizard-box {
        width: 80%;
        max-width: 100;
        padding: 1 2;
        border: round #6fd6ff;
        background: #121822;
        color: #f4fbff;
    }
    FirstRunWizardScreen Input {
        margin-top: 1;
    }
    FirstRunWizardScreen .hint {
        color: #8fa0ad;
        margin-top: 1;
    }
    """

    def __init__(self, *, title: str | None = None) -> None:
        super().__init__()
        self.step: str = "provider"
        self.provider_index = 0
        self.api_key = ""
        self.model_name = ""
        self.custom_base_url = ""
        self._title_override = title

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard-box"):
            yield Static(self._title(), id="wizard-title")
            yield Static(self._body(), id="wizard-body")
            yield Input(id="wizard-input")
            yield Static(self._hint(), id="wizard-hint", classes="hint")

    def on_mount(self) -> None:
        self._enter_step("provider")

    # --- step management ----------------------------------------------------

    def _enter_step(self, step: str) -> None:
        self.step = step
        input_widget = self.query_one("#wizard-input", Input)
        input_widget.password = step == "api_key"
        if step == "provider":
            input_widget.display = False
            input_widget.value = ""
        elif step == "api_key":
            input_widget.display = True
            input_widget.placeholder = "API key"
            input_widget.value = self.api_key
            input_widget.focus()
        elif step == "model_name":
            input_widget.display = True
            input_widget.password = False
            input_widget.placeholder = "model name, e.g. deepseek-chat"
            input_widget.value = self.model_name
            input_widget.focus()
        elif step == "base_url":
            input_widget.display = True
            input_widget.password = False
            input_widget.placeholder = "https://your-endpoint/v1"
            input_widget.value = self.custom_base_url
            input_widget.focus()
        elif step == "confirm":
            input_widget.display = False
        self._refresh()

    def _refresh(self) -> None:
        self.query_one("#wizard-title", Static).update(self._title())
        self.query_one("#wizard-body", Static).update(self._body())
        self.query_one("#wizard-hint", Static).update(self._hint())

    def _title(self) -> str:
        if self._title_override:
            return f"[bold cyan]{self._title_override}[/bold cyan]"
        return "[bold cyan]Trendpower · 首次运行向导 / First-run setup[/bold cyan]"

    def _body(self) -> str:
        if self.step == "provider":
            return self._provider_body()
        provider = MODEL_PROVIDERS[self.provider_index]
        header = f"Provider: [cyan]{provider.label}[/cyan]"
        if self.step == "api_key":
            return f"{header}\n\n请输入 API key。"
        if self.step == "model_name":
            return f"{header}\n\n请输入模型名称（会作为 --name 传给 provider）。"
        if self.step == "base_url":
            return f"{header}\n\n该 provider 没有内置 base URL，请输入 OpenAI 兼容地址。"
        if self.step == "confirm":
            entry = self._build_entry()
            return (
                f"{header}\n"
                f"Model: [white]{entry.name}[/white]\n"
                f"baseURL: [white]{entry.baseURL}[/white]\n"
                f"API Key: [white]{_mask(entry.APIKey)}[/white]"
            )
        return ""

    def _provider_body(self) -> str:
        lines = ["[bold]选择模型 provider（↑/↓ 移动，Enter 确认）：[/bold]", ""]
        for i, provider in enumerate(MODEL_PROVIDERS):
            marker = "❯ " if i == self.provider_index else "  "
            color = "cyan" if i == self.provider_index else "white"
            lines.append(f"[{color}]{marker}{provider.label}[/{color}]")
        return "\n".join(lines)

    def _hint(self) -> str:
        if self.step == "provider":
            return "Esc 退出，Enter 进入下一步。"
        if self.step == "confirm":
            return "Enter 确认并写入配置，Esc 重新开始。"
        return "Enter 下一步，Esc 退出。"

    # --- step navigation ----------------------------------------------------

    def action_move(self, delta: int) -> None:
        if self.step != "provider":
            return
        self.provider_index = (self.provider_index + delta) % len(MODEL_PROVIDERS)
        self._refresh()

    def action_cancel(self) -> None:
        if self.step == "confirm":
            # Restart the flow.
            self.api_key = ""
            self.model_name = ""
            self.custom_base_url = ""
            self.provider_index = 0
            self._enter_step("provider")
            return
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if self.step == "provider" and event.key == "enter":
            event.stop()
            self._enter_step("api_key")
            return
        if self.step == "confirm" and event.key == "enter":
            event.stop()
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value.strip()
        if self.step == "api_key":
            if not value:
                return
            self.api_key = value
            self._enter_step("model_name")
        elif self.step == "model_name":
            if not value:
                return
            self.model_name = value
            provider = MODEL_PROVIDERS[self.provider_index]
            if provider.baseURL:
                self._enter_step("confirm")
            else:
                self._enter_step("base_url")
        elif self.step == "base_url":
            if not value:
                return
            self.custom_base_url = value
            self._enter_step("confirm")

    # --- finish -------------------------------------------------------------

    def _build_entry(self) -> ModelEntry:
        provider = MODEL_PROVIDERS[self.provider_index]
        base_url = provider.baseURL or self.custom_base_url
        return ModelEntry(
            name=self.model_name.strip(),
            baseURL=base_url.strip(),
            APIKey=self.api_key.strip(),
            provider=provider.providerType,
        )

    def _submit(self) -> None:
        # Caller owns persistence — first-run replaces the config, the model
        # manager appends to it. The wizard only builds and returns the entry.
        self.dismiss(self._build_entry())
