"""Model/token status footer."""

from __future__ import annotations

from textual.widgets import Static

from ..token_usage import TokenUsageSummary, format_token_count


class StatusFooter(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(" ", *args, **kwargs)

    def update_status(self, model_name: str | None, token_usage: TokenUsageSummary) -> None:
        model = model_name or "(no model)"
        self.update(
            f"model {model}    last input {format_token_count(token_usage.latest_input_tokens)}    "
            f"session {format_token_count(token_usage.session_total_tokens)}"
        )
