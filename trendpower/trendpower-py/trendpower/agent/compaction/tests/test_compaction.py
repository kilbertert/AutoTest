from __future__ import annotations

from typing import Any, Dict, List

from trendpower.agent.compaction import (
    create_compaction_middleware,
    estimate_tokens,
    plan_compaction,
)


# --- helpers ----------------------------------------------------------------


def user(text: str) -> Dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant_text(text: str, prompt_tokens: int | None = None) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    if prompt_tokens is not None:
        msg["usage"] = {"promptTokens": prompt_tokens, "completionTokens": 0, "totalTokens": prompt_tokens}
    return msg


def assistant_tool(tool_id: str, name: str = "bash") -> Dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {}}]}


def tool_result(tool_id: str, content: str = "ok") -> Dict[str, Any]:
    return {"role": "tool", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}]}


async def _run_before_model(middleware: Any, messages: List[Dict[str, Any]]) -> Any:
    agent_context = {"messages": messages}
    model_context = {"messages": messages, "signal": None}
    return await middleware.beforeModel(
        {"agentContext": agent_context, "modelContext": model_context}
    )


# --- estimation -------------------------------------------------------------


def test_estimate_uses_prompt_tokens_when_available() -> None:
    messages = [user("hi"), assistant_text("hello", prompt_tokens=50_000)]
    assert estimate_tokens(messages) >= 50_000


def test_estimate_falls_back_to_char_heuristic() -> None:
    messages = [user("x" * 4000)]
    # ~4 chars/token => ~1000 tokens, no usage present
    assert estimate_tokens(messages) >= 900


# --- partitioning / tool-pairing safety -------------------------------------


def test_plan_returns_none_when_nothing_to_compact() -> None:
    messages = [user("a"), assistant_text("b")]
    assert plan_compaction(messages, keep_head=1, keep_recent=8) is None


def test_plan_keeps_head_and_recent() -> None:
    messages = [user("task")] + [assistant_text(f"m{i}") for i in range(10)]
    plan = plan_compaction(messages, keep_head=1, keep_recent=3)
    assert plan is not None
    head, middle, tail = plan
    assert head == [messages[0]]
    assert len(tail) == 3
    assert len(middle) == len(messages) - 1 - 3


def test_tail_never_starts_on_orphan_tool_message() -> None:
    # Build: user, [assistant_tool + tool_result] x N. If the recent window
    # would start on a tool_result, the boundary must move forward.
    messages: List[Dict[str, Any]] = [user("task")]
    for i in range(6):
        messages.append(assistant_tool(f"t{i}"))
        messages.append(tool_result(f"t{i}"))
    # keep_recent=3 would land mid-pair; planner must fix it.
    plan = plan_compaction(messages, keep_head=1, keep_recent=3)
    assert plan is not None
    _, _, tail = plan
    assert tail[0]["role"] != "tool", "tail must not begin with an orphaned tool_result"


def test_head_not_left_with_orphan_tool_use() -> None:
    # Head boundary lands right after an assistant tool_use; planner must pull
    # back so the matching result is not summarized away from its call.
    messages = [assistant_tool("t0"), tool_result("t0"), user("next"), assistant_text("done")]
    plan = plan_compaction(messages, keep_head=1, keep_recent=1)
    assert plan is not None
    head, _, _ = plan
    assert head == [] or not any(
        b.get("type") == "tool_use" for b in head[-1].get("content", [])
    )


# --- middleware behavior ----------------------------------------------------


async def test_no_compaction_below_threshold() -> None:
    captured: List[Any] = []
    mw = create_compaction_middleware(
        trigger_tokens=1_000_000,
        summarizer=_fake_summarizer(captured),
    )
    messages = [user("hi"), assistant_text("hello", prompt_tokens=10)]
    result = await _run_before_model(mw, messages)
    assert result is None
    assert len(messages) == 2  # untouched
    assert not captured


async def test_compaction_replaces_middle_in_place() -> None:
    captured: List[Any] = []
    events: List[Any] = []
    mw = create_compaction_middleware(
        trigger_tokens=100,
        keep_head_messages=1,
        keep_recent_messages=2,
        summarizer=_fake_summarizer(captured),
        on_compaction=events.append,
    )
    messages: List[Dict[str, Any]] = [user("task")]
    for i in range(8):
        messages.append(assistant_text(f"message number {i} " + "x" * 100, prompt_tokens=None))
    original_first = messages[0]
    original_last_two = messages[-2:]

    result = await _run_before_model(mw, messages)

    assert result is not None
    # First message preserved, summary inserted, recent window preserved.
    assert messages[0] is original_first
    assert messages[1]["role"] == "user"
    assert "SUMMARY" in messages[1]["content"][0]["text"]
    assert messages[-2:] == original_last_two
    assert len(messages) == 1 + 1 + 2
    assert events and events[0].messages_after == len(messages)
    assert captured, "summarizer was invoked with the middle slice"


async def test_compaction_failure_is_non_fatal() -> None:
    async def boom(middle, signal):  # noqa: ANN001
        raise RuntimeError("summarizer down")

    mw = create_compaction_middleware(trigger_tokens=1, summarizer=boom)
    messages = [user("a"), assistant_text("b"), user("c"), assistant_text("d")]
    before = list(messages)
    result = await _run_before_model(mw, messages)
    assert result is None
    assert messages == before  # left intact on summarizer error


def _fake_summarizer(captured: List[Any]):
    async def summarize(middle, signal):  # noqa: ANN001
        captured.append(middle)
        return "SUMMARY"

    return summarize
