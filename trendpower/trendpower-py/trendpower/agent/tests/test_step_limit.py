"""maxSteps soft-landing: hitting the step budget wraps up instead of crashing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from trendpower.agent.agent import _STEP_LIMIT_PROMPT, Agent
from trendpower.foundation import Model, define_tool


class _ScriptedProvider:
    """Yields one pre-baked AssistantMessage per stream call, recording the
    tools it was given each call (so we can assert the final turn had none)."""

    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        self._responses = responses
        self._i = 0
        self.tools_seen: List[Optional[list]] = []

    async def invoke(self, params):  # pragma: no cover - unused
        ...

    async def stream(self, params):
        self.tools_seen.append(params.get("tools"))
        msg = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        yield msg


class _P(BaseModel):
    pass


def _noop_tool():
    async def _invoke(_p: _P, _s=None):
        return "ok"

    return define_tool(name="noop", description="noop", parameters=_P, invoke=_invoke)


def _tool_use(i: int) -> Dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "noop", "input": {}}]}


def _text(t: str) -> Dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "text", "text": t}]}


async def test_step_limit_soft_lands_with_a_final_summary():
    # Always-tool-using model; the final (3rd) call returns the wrap-up text.
    provider = _ScriptedProvider([_tool_use(1), _tool_use(2), _text("Here is where I got to.")])
    model = Model(name="fake", provider=provider)
    agent = Agent(model=model, prompt="sys", messages=[], tools=[_noop_tool()], maxSteps=2)

    events = [ev async for ev in agent.stream({"role": "user", "content": [{"type": "text", "text": "go"}]})]

    # No RuntimeError raised; the last emitted message is the text summary.
    msgs = [e["message"] for e in events if e["type"] == "message"]
    final = msgs[-1]
    assert final["role"] == "assistant"
    assert final["content"][0]["text"] == "Here is where I got to."

    # The nudge was injected as a user message before the final turn.
    assert any(
        m.get("role") == "user"
        and m["content"][0].get("text") == _STEP_LIMIT_PROMPT
        for m in agent.messages
    )

    # The final think ran with tools disabled (3 stream calls: 2 steps + wrap-up).
    assert provider.tools_seen[-1] is None
    assert provider.tools_seen[0] is not None

    # Tools are restored on the agent afterwards.
    assert agent.tools is not None
