"""Tests for the `task` sub-agent tool and the generic sub-agent runner.

These drive a real ``Agent`` via a scripted fake provider so we exercise the
actual ReAct loop without touching the network or the filesystem.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from trendpower.agent import run_subagent
from trendpower.agent.agent import Agent
from trendpower.foundation import AbortController, Model, define_tool
from trendpower.coding.tools.task import READ_ONLY_TOOL_NAMES, create_task_tool

from pydantic import BaseModel


# --- scripted fake provider -------------------------------------------------


class _ScriptedProvider:
    """Yields one pre-baked AssistantMessage per `stream` call, in order."""

    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        self._responses = responses
        self._i = 0

    async def invoke(self, params):  # pragma: no cover - unused here
        msg = self._responses[self._i]
        self._i += 1
        return msg

    async def stream(self, params):
        msg = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        yield msg


def _model(responses: List[Dict[str, Any]]) -> Model:
    return Model(name="fake", provider=_ScriptedProvider(responses))


def _assistant_text(text: str) -> Dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "usage": {"promptTokens": 123, "completionTokens": 0, "totalTokens": 123},
    }


def _assistant_tool(tool_id: str, name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}],
    }


# --- a trivial echo tool for the inner agent --------------------------------


class _EchoParams(BaseModel):
    value: str = ""


def _echo_tool():
    async def _invoke(p: _EchoParams, _s=None):
        return f"echoed:{p.value}"

    return define_tool(name="echo", description="echo", parameters=_EchoParams, invoke=_invoke)


# --- runner -----------------------------------------------------------------


async def test_run_subagent_tool_use_then_text():
    model = _model(
        [
            _assistant_tool("t1", "echo", {"value": "hi"}),
            _assistant_text("Final report: done."),
        ]
    )
    inner = Agent(model=model, prompt="sys", messages=[], tools=[_echo_tool()])
    result = await run_subagent(inner, "do the thing")

    assert result.text == "Final report: done."
    assert result.steps == 2  # tool_use turn + final text turn
    assert result.prompt_tokens == 123


async def test_run_subagent_forwards_abort():
    """An already-aborted parent signal should immediately abort the inner agent."""
    aborted = {"v": False}

    class _StubInner:
        def abort(self):
            aborted["v"] = True

        async def stream(self, _msg):
            yield {"type": "message", "message": _assistant_text("noop")}

    ctrl = AbortController()
    ctrl.abort()  # pre-aborted: add_listener fires the callback synchronously
    await run_subagent(_StubInner(), "x", signal=ctrl.signal)  # type: ignore[arg-type]
    assert aborted["v"] is True


# --- task tool --------------------------------------------------------------


def _task(responses: List[Dict[str, Any]], **kw):
    base_tools = [_echo_tool()]
    return create_task_tool(model=_model(responses), cwd="/tmp", base_tools=base_tools, **kw)


async def test_task_explore_happy_path():
    tool = _task([_assistant_text("Found it at foo.py:10")])
    out = await tool.invoke(
        {"description": "find x", "prompt": "where is x", "subagent_type": "explore"}, None
    )
    assert out["ok"] is True
    assert out["summary"] == "Found it at foo.py:10"
    assert out["data"]["subagentType"] == "explore"


async def test_task_reports_inner_failure_as_error():
    class _Boom:
        async def invoke(self, params):  # pragma: no cover
            raise RuntimeError("kaboom")

        async def stream(self, params):
            raise RuntimeError("kaboom")
            yield  # noqa: unreachable — makes this an async generator

    tool = create_task_tool(
        model=Model(name="fake", provider=_Boom()), cwd="/tmp", base_tools=[_echo_tool()]
    )
    out = await tool.invoke({"description": "x", "prompt": "y", "subagent_type": "explore"}, None)
    assert out["ok"] is False
    assert out["code"] == "SUBAGENT_FAILED"


def test_read_only_names_exclude_mutating_and_task():
    # Guard the central invariant: the read-only set is exactly the safe tools.
    assert "task" not in READ_ONLY_TOOL_NAMES
    assert "ask_user_question" not in READ_ONLY_TOOL_NAMES
    for mutating in ("bash", "write_file", "str_replace", "apply_patch", "mkdir", "move_path"):
        assert mutating not in READ_ONLY_TOOL_NAMES
