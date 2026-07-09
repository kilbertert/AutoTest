"""Reconstruct a span tree from a trace JSONL file and render it with Rich.

The on-disk stream is flat ``start``/``end``/``event`` records (see
``trendpower.agent.tracing.events``); here we stitch them back into the
run → step → {llm, tool} tree and draw a waterfall. A span with a ``start`` but
no ``end`` is shown as ``aborted`` — that is exactly what a Ctrl+C'd run leaves
behind, since the agent loop has no on-abort hook.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from trendpower_tui.config import ensure_trendpower_home_env, get_trendpower_home_path


def traces_dir() -> Path:
    ensure_trendpower_home_env()
    return get_trendpower_home_path() / "traces"


def list_trace_files() -> List[Path]:
    directory = traces_dir()
    if not directory.exists():
        return []
    return sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_trace_path(run_id: Optional[str]) -> Optional[Path]:
    """Resolve a run id (or prefix) to a trace file; newest file if ``run_id`` is None."""
    files = list_trace_files()
    if not files:
        return None
    if run_id is None:
        return files[0]
    for path in files:
        stem = path.stem
        if stem == run_id or stem == f"run_{run_id}" or stem.startswith(run_id):
            return path
    return None


# --- reconstruction ---------------------------------------------------------


@dataclass
class _Span:
    kind: str
    id: str
    parent: Optional[str]
    order: int
    start: Optional[Dict[str, Any]] = None
    end: Optional[Dict[str, Any]] = None
    children: List["_Span"] = field(default_factory=list)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end and self.end.get("duration_ms") is not None:
            return self.end["duration_ms"]
        if self.start and self.end and "ts" in self.start and "ts" in self.end:
            return round((self.end["ts"] - self.start["ts"]) * 1000, 1)
        return None

    @property
    def closed(self) -> bool:
        return self.end is not None


def _load_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _build_spans(events: List[Dict[str, Any]]) -> List[_Span]:
    spans: Dict[str, _Span] = {}
    order = 0
    for ev in events:
        span_id = ev.get("id")
        if not span_id:
            continue
        sp = spans.get(span_id)
        if sp is None:
            sp = _Span(kind=ev.get("span", "?"), id=span_id, parent=ev.get("parent"), order=order)
            spans[span_id] = sp
            order += 1
        t = ev.get("t")
        if t == "start":
            sp.start = ev
        elif t == "end":
            sp.end = ev
        elif t == "event":  # zero-duration point span (e.g. compaction)
            sp.start = sp.start or ev
            sp.end = sp.end or ev

    roots: List[_Span] = []
    for sp in spans.values():
        parent = spans.get(sp.parent) if sp.parent else None
        if parent is not None and parent is not sp:
            parent.children.append(sp)
        else:
            roots.append(sp)
    for sp in spans.values():
        sp.children.sort(key=lambda c: c.order)
    roots.sort(key=lambda c: c.order)
    return roots


# --- rendering --------------------------------------------------------------


def _fmt_dur(ms: Optional[float]) -> str:
    if ms is None:
        return ""
    if ms >= 1000:
        return f"[dim]{ms / 1000:.2f}s[/dim]"
    return f"[dim]{ms:.0f}ms[/dim]"


def _label(sp: _Span) -> str:
    attrs = sp.start or {}
    end = sp.end or {}
    dur = _fmt_dur(sp.duration_ms)
    if sp.kind == "run":
        model = attrs.get("model") or "?"
        tools = attrs.get("tools")
        tag = "[magenta]sub-agent[/magenta]" if attrs.get("subagent") else "[bold]run[/bold]"
        if not sp.closed:
            outcome = "[yellow]● aborted[/yellow]"
        else:
            outcome = f"[green]✓ {end.get('outcome', 'done')}[/green]"
        return f"{tag} [cyan]{sp.id}[/cyan] · {model} · {tools} tools · {outcome}"
    if sp.kind == "step":
        return f"[bold]step {attrs.get('step', '?')}[/bold] {dur}"
    if sp.kind == "llm":
        pt = end.get("prompt_tokens")
        ct = end.get("completion_tokens")
        toks = f"[dim]↑{pt} ↓{ct}[/dim]" if pt is not None else ""
        status = "" if sp.closed else " [yellow]●[/yellow]"
        return f"llm {dur} {toks}{status}"
    if sp.kind == "tool":
        name = attrs.get("name", "?")
        if not sp.closed:
            mark = "[yellow]●[/yellow]"  # no afterToolUse → errored/skipped/aborted
        else:
            mark = "[green]✓[/green]" if end.get("ok") else "[red]✗[/red]"
        inp = attrs.get("input", "")
        inp_txt = f"  [dim]{inp}[/dim]" if inp else ""
        return f"{mark} [yellow]{name}[/yellow] {dur}{inp_txt}"
    if sp.kind == "compaction":
        before = attrs.get("messages_before")
        after = attrs.get("messages_after")
        toks = attrs.get("estimated_tokens")
        return f"[blue]⟳ compaction[/blue] [dim]{before}→{after} msgs (~{toks} tok)[/dim]"
    return f"{sp.kind} {sp.id}"


def _attach(tree: Tree, sp: _Span) -> None:
    node = tree.add(_label(sp))
    for child in sp.children:
        _attach(node, child)


def render_trace(path: Path) -> RenderableType:
    """Render one trace file as a Rich tree (run → step → llm/tool)."""
    roots = _build_spans(_load_events(path))
    if not roots:
        return Text(f"(empty or unreadable trace: {path.name})", style="dim")
    renderables: List[RenderableType] = []
    for root in roots:
        tree = Tree(_label(root))
        for child in root.children:
            _attach(tree, child)
        renderables.append(tree)
    return Group(*renderables)


def render_trace_index(limit: int = 20) -> RenderableType:
    """A table of recent trace files."""
    files = list_trace_files()[:limit]
    if not files:
        return Text(f"No traces found in {traces_dir()}", style="dim")
    table = Table(title="Recent agent traces", title_style="bold", expand=False)
    table.add_column("run id", style="cyan", no_wrap=True)
    table.add_column("model")
    table.add_column("steps", justify="right")
    table.add_column("outcome")
    for path in files:
        roots = _build_spans(_load_events(path))
        top = roots[0] if roots else None
        model = (top.start or {}).get("model", "?") if top else "?"
        steps = sum(1 for r in roots for c in r.children if c.kind == "step")
        if top is None:
            outcome = "[dim]empty[/dim]"
        elif not top.closed:
            outcome = "[yellow]aborted[/yellow]"
        else:
            outcome = "[green]completed[/green]"
        table.add_row(path.stem, str(model), str(steps), outcome)
    return table
