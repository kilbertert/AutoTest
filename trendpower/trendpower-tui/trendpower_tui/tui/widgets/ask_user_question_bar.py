"""Inline `ask_user_question` bar — sits in the input slot, not a modal."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static


ACCENT_COLOR = "#6fd6ff"
DIM_COLOR = "#8fa0ad"
HIGHLIGHT_COLOR = "#ffd17a"


class AnswersSubmitted(Message):
    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.answers = answers
        super().__init__()


def _initial_selections(questions: list[dict[str, Any]]) -> list[list[str]]:
    selections: list[list[str]] = []
    for question in questions:
        options = question.get("options") or []
        if question.get("multi_select"):
            selections.append([])
        elif options and isinstance(options[0], dict):
            label = options[0].get("label")
            selections.append([str(label)] if label else [])
        else:
            selections.append([])
    return selections


def _can_submit(questions: list[dict[str, Any]], selections: list[list[str]]) -> bool:
    for question, picks in zip(questions, selections):
        if question.get("multi_select"):
            if len(picks) < 1:
                return False
        elif len(picks) != 1:
            return False
    return True


def _tab_label(header: str) -> str:
    return header if len(header) <= 12 else header[:11] + "…"


class AskUserQuestionBar(Vertical):
    can_focus = True

    BINDINGS = [
        Binding("up", "move_option(-1)", "up", show=False),
        Binding("down", "move_option(1)", "down", show=False),
        Binding("left", "move_tab(-1)", "left tab", show=False),
        Binding("right", "move_tab(1)", "right tab", show=False),
        Binding("enter", "confirm", "confirm"),
        Binding("space", "toggle", "toggle", show=False),
        Binding("escape", "dismiss_fallback", "cancel", show=False),
    ]

    DEFAULT_CSS = """
    AskUserQuestionBar {
        display: none;
        height: auto;
        padding: 0 2;
        border: round #6fd6ff;
        background: #121822;
        color: #f4fbff;
    }
    AskUserQuestionBar.-active { display: block; }
    AskUserQuestionBar:focus-within { border: round #ffd17a; }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.questions: list[dict[str, Any]] = []
        self.selections: list[list[str]] = []
        self.focus_idx: list[int] = []
        self.tab_index = 0
        self.review_tab_index = -1

    def compose(self) -> ComposeResult:
        yield Static("", id="ask-tabs", markup=True)
        yield Static("", id="ask-body", markup=True)
        yield Static("", id="ask-hint", markup=True)

    def show_for(self, questions: list[dict[str, Any]]) -> None:
        self.questions = list(questions)
        self.selections = _initial_selections(self.questions)
        self.focus_idx = [0 for _ in self.questions]
        self.tab_index = 0
        self.review_tab_index = len(self.questions) if len(self.questions) >= 2 else -1
        self.add_class("-active")
        self._refresh()
        self.focus()

    def hide(self) -> None:
        self.remove_class("-active")
        self.questions = []
        self.selections = []
        self.focus_idx = []

    def _refresh(self) -> None:
        try:
            self.query_one("#ask-tabs", Static).update(self._tab_row())
            self.query_one("#ask-body", Static).update(self._body())
            self.query_one("#ask-hint", Static).update(self._hint())
        except Exception:
            return

    def _tab_row(self) -> str:
        if len(self.questions) < 2:
            return ""
        parts: list[str] = []
        for i, q in enumerate(self.questions):
            header = _tab_label(str(q.get("header", "")))
            if i == self.tab_index:
                parts.append(f"[bold {ACCENT_COLOR}]▸ {_escape(header)}[/bold {ACCENT_COLOR}]")
            else:
                parts.append(f"[{DIM_COLOR}]  {_escape(header)}[/{DIM_COLOR}]")
        if self.review_tab_index >= 0:
            if self.tab_index == self.review_tab_index:
                parts.append(f"[bold {ACCENT_COLOR}]▸ Confirm[/bold {ACCENT_COLOR}]")
            else:
                parts.append(f"[{DIM_COLOR}]  Confirm[/{DIM_COLOR}]")
        return "   ".join(parts)

    def _body(self) -> str:
        if not self.questions:
            return ""
        if self.review_tab_index >= 0 and self.tab_index == self.review_tab_index:
            return self._review_body()
        return self._question_body(self.tab_index)

    def _question_body(self, question_index: int) -> str:
        question = self.questions[question_index]
        options = question.get("options") or []
        multi = bool(question.get("multi_select"))
        focus = self.focus_idx[question_index]
        selected = self.selections[question_index]

        lines: list[str] = [f"[bold]{_escape(str(question.get('question', '')))}[/bold]", ""]
        for i, opt in enumerate(options):
            label = str(opt.get("label", "")) if isinstance(opt, dict) else ""
            description = str(opt.get("description", "")) if isinstance(opt, dict) else ""
            is_focused = i == focus
            is_selected = label in selected if multi else is_focused
            if multi:
                prefix = "[×] " if is_selected else "[ ] "
            else:
                prefix = "❯ " if is_focused else "  "
            label_color = ACCENT_COLOR if is_focused else "white"
            lines.append(f"[{label_color}]{prefix}{_escape(label)}[/{label_color}]")
            if is_focused and description:
                lines.append(f"   [{DIM_COLOR}]{_escape(description)}[/{DIM_COLOR}]")

        if not multi and options:
            focused_opt = options[focus] if 0 <= focus < len(options) else None
            preview = focused_opt.get("preview") if isinstance(focused_opt, dict) else None
            if preview:
                lines.extend(["", f"[{DIM_COLOR}]preview:[/{DIM_COLOR}]", str(preview)])
        return "\n".join(lines)

    def _review_body(self) -> str:
        lines: list[str] = ["[bold]Review choices[/bold]", ""]
        for i, q in enumerate(self.questions):
            header = str(q.get("header", ""))
            picks = self.selections[i]
            value = ", ".join(picks) if picks else "(none selected)"
            lines.append(f"[{ACCENT_COLOR}]{_escape(header)}[/{ACCENT_COLOR}]")
            lines.append(f"  [{DIM_COLOR}]{_escape(value)}[/{DIM_COLOR}]")
        lines.extend(["", f"[{DIM_COLOR}]Press Enter to submit.[/{DIM_COLOR}]"])
        return "\n".join(lines)

    def _hint(self) -> str:
        if len(self.questions) >= 2:
            base = "←/→ tab  ·  ↑/↓ option  ·  Space toggle  ·  Enter next/confirm"
        else:
            base = "↑/↓ option  ·  Space toggle (multi)  ·  Enter confirm"
        return f"  [{DIM_COLOR}]{base}[/{DIM_COLOR}]"

    def action_move_tab(self, delta: int) -> None:
        if not self.has_class("-active") or len(self.questions) < 2:
            return
        total = len(self.questions) + (1 if self.review_tab_index >= 0 else 0)
        self.tab_index = (self.tab_index + delta) % total
        self._refresh()

    def action_move_option(self, delta: int) -> None:
        if not self.has_class("-active"):
            return
        if not (0 <= self.tab_index < len(self.questions)):
            return
        question = self.questions[self.tab_index]
        options = question.get("options") or []
        if not options:
            return
        focus = (self.focus_idx[self.tab_index] + delta) % len(options)
        self.focus_idx[self.tab_index] = focus
        if not question.get("multi_select"):
            label = options[focus].get("label") if isinstance(options[focus], dict) else None
            if label is not None:
                self.selections[self.tab_index] = [str(label)]
        self._refresh()

    def action_toggle(self) -> None:
        if not self.has_class("-active"):
            return
        if not (0 <= self.tab_index < len(self.questions)):
            return
        question = self.questions[self.tab_index]
        if not question.get("multi_select"):
            return
        options = question.get("options") or []
        focus = self.focus_idx[self.tab_index]
        if not (0 <= focus < len(options)):
            return
        label = options[focus].get("label") if isinstance(options[focus], dict) else None
        if label is None:
            return
        row = list(self.selections[self.tab_index])
        if label in row:
            row.remove(label)
        else:
            row.append(label)
        self.selections[self.tab_index] = row
        self._refresh()

    def action_confirm(self) -> None:
        if not self.has_class("-active"):
            return
        questions_total = len(self.questions)
        if questions_total <= 1 or self.tab_index == self.review_tab_index:
            self._try_submit()
            return
        if self.tab_index < questions_total - 1:
            self.tab_index += 1
        else:
            self.tab_index = self.review_tab_index
        self._refresh()

    def action_dismiss_fallback(self) -> None:
        # Esc submits fallback answers (first option for each question) so the
        # agent does not deadlock if the user wants out.
        if not self.has_class("-active"):
            return
        fallback: list[dict[str, Any]] = []
        for index, question in enumerate(self.questions):
            options = question.get("options") or []
            label = options[0].get("label") if options and isinstance(options[0], dict) else ""
            fallback.append({"question_index": index, "selected_labels": [label] if label else []})
        self.post_message(AnswersSubmitted(fallback))

    def _try_submit(self) -> None:
        if not _can_submit(self.questions, self.selections):
            return
        answers = [
            {"question_index": i, "selected_labels": list(picks)}
            for i, picks in enumerate(self.selections)
        ]
        self.post_message(AnswersSubmitted(answers))


def _escape(text: str) -> str:
    return text.replace("[", r"\[")
