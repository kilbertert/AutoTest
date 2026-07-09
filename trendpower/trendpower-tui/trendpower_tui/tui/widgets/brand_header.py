"""Brand header with left brand text and right status pill."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class BrandHeader(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("[bold #5d7cf5]Trendpower[/bold #5d7cf5] · loading…", id="brand-left")
        yield Static("·", id="brand-right")

    def update_status(
        self,
        *,
        model_name: str | None,
        ready: bool,
        skills_count: int = 0,
    ) -> None:
        model = model_name or "no model"
        ready_text = (
            "[#7cd992]● ready[/#7cd992]" if ready else "[#ff8b8b]● setup required[/#ff8b8b]"
        )
        self.query_one("#brand-left", Static).update(
            f"[bold #5d7cf5]Trendpower[/bold #5d7cf5]  [#8fa0ad]·[/#8fa0ad]  {model}"
        )
        self.query_one("#brand-right", Static).update(
            f"[#8fa0ad]skills {skills_count}  ·[/#8fa0ad]  {ready_text}"
        )
