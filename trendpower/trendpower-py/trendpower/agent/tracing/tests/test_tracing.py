"""Unit tests for the tracing middleware and JsonlSink."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from trendpower.agent.tracing import JsonlSink, MultiSink, create_tracing_middleware
from trendpower.agent.tracing.sinks import _BaseSink


class CapturingSink(_BaseSink):
    """In-memory sink that records every event for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.events: List[Dict[str, Any]] = []

    def emit(self, event: Dict[str, Any]) -> None:
        self.events.append(event)


def _ctx(tools: int = 3) -> Dict[str, Any]:
    return {"agentContext": {"tools": [object()] * tools}}


async def _drive_one_step(mw: Any, *, with_tool: bool = True) -> None:
    """Replay the hook sequence the Agent loop would issue for one step."""
    await mw.beforeAgentRun(_ctx())
    await mw.beforeAgentStep({"step": 1})
    await mw.beforeModel({})
    await mw.afterModel(
        {"message": {"usage": {"promptTokens": 100, "completionTokens": 20, "totalTokens": 120}}}
    )
    if with_tool:
        tu = {"id": "toolu_abc", "name": "read_file", "input": {"path": "/x"}}
        await mw.beforeToolUse({"toolUse": tu})
        await mw.afterToolUse({"toolUse": tu, "toolResult": {"ok": True, "summary": "read"}})
    await mw.afterAgentStep({"step": 1})


def _by(events: List[Dict[str, Any]], span: str, t: str) -> List[Dict[str, Any]]:
    return [e for e in events if e["span"] == span and e["t"] == t]


async def test_emits_full_span_tree() -> None:
    sink = CapturingSink()
    mw = create_tracing_middleware(sink, model_name="test-model")
    await _drive_one_step(mw)
    await mw.afterAgentRun({})

    run_start = _by(sink.events, "run", "start")[0]
    assert run_start["parent"] is None
    assert run_start["model"] == "test-model"
    assert run_start["tools"] == 3
    assert run_start["subagent"] is False

    step_start = _by(sink.events, "step", "start")[0]
    assert step_start["parent"] == run_start["id"]
    assert step_start["step"] == 1

    llm_end = _by(sink.events, "llm", "end")[0]
    assert llm_end["prompt_tokens"] == 100
    assert llm_end["completion_tokens"] == 20

    tool_start = _by(sink.events, "tool", "start")[0]
    assert tool_start["id"] == "toolu_abc"
    assert tool_start["parent"] == step_start["id"]
    assert tool_start["name"] == "read_file"
    tool_end = _by(sink.events, "tool", "end")[0]
    assert tool_end["ok"] is True

    run_end = _by(sink.events, "run", "end")[0]
    assert run_end["outcome"] == "completed"


async def test_aborted_run_leaves_run_span_unclosed() -> None:
    sink = CapturingSink()
    mw = create_tracing_middleware(sink)
    # Simulate Ctrl+C mid-step: afterAgentRun is never reached.
    await mw.beforeAgentRun(_ctx())
    await mw.beforeAgentStep({"step": 1})
    await mw.beforeModel({})

    assert _by(sink.events, "run", "start")  # a run was opened
    assert not _by(sink.events, "run", "end")  # but never closed -> "aborted"


async def test_tool_error_marked_not_ok() -> None:
    sink = CapturingSink()
    mw = create_tracing_middleware(sink)
    await mw.beforeAgentRun(_ctx())
    tu = {"id": "t1", "name": "bash", "input": {"command": "false"}}
    await mw.beforeToolUse({"toolUse": tu})
    await mw.afterToolUse({"toolUse": tu, "toolResult": "Error: boom"})
    assert _by(sink.events, "tool", "end")[0]["ok"] is False


async def test_subagent_links_to_parent_run() -> None:
    sink = CapturingSink()
    parent = create_tracing_middleware(sink, is_subagent=False)
    child = create_tracing_middleware(sink, is_subagent=True)

    await parent.beforeAgentRun(_ctx())
    parent_run_id = _by(sink.events, "run", "start")[0]["id"]

    # Child runs while the parent run is open (during a `task` tool call).
    await child.beforeAgentRun(_ctx())
    child_run_start = _by(sink.events, "run", "start")[1]
    assert child_run_start["parent"] == parent_run_id
    assert child_run_start["subagent"] is True


async def test_tracing_never_raises_on_bad_input() -> None:
    sink = CapturingSink()
    mw = create_tracing_middleware(sink)
    # Missing keys must not propagate out of a hook.
    await mw.beforeAgentStep({})  # no "step"
    await mw.afterModel({})  # no "message"
    await mw.beforeToolUse({})  # no "toolUse"


def test_jsonl_sink_round_trips(tmp_path: Any) -> None:
    sink = JsonlSink(tmp_path)
    sink.begin_run("run_1", is_top=True)
    sink.emit({"t": "start", "span": "run", "id": "run_1"})
    sink.emit({"t": "end", "span": "run", "id": "run_1"})

    path = tmp_path / "run_1.jsonl"
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["t"] == "start"


def test_jsonl_sink_rotates_per_top_run_keeps_subagent_in_parent_file(tmp_path: Any) -> None:
    sink = JsonlSink(tmp_path)
    sink.begin_run("run_top", is_top=True)
    sink.emit({"id": "a"})
    sink.begin_run("run_sub", is_top=False)  # sub-agent reuses the open file
    sink.emit({"id": "b"})
    assert (tmp_path / "run_top.jsonl").read_text().count("\n") == 2
    assert not (tmp_path / "run_sub.jsonl").exists()


def test_multisink_fans_out(tmp_path: Any) -> None:
    a, b = CapturingSink(), CapturingSink()
    multi = MultiSink([a, b])
    multi.begin_run("r", is_top=True)
    multi.emit({"x": 1})
    assert a.events == b.events == [{"x": 1}]
    assert multi.current_top_run_id == "r"
