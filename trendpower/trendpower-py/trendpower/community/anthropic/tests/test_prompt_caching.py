"""Prompt-caching behavior of the Anthropic provider.

Covers the two coupled P0 concerns:
- cache breakpoints land on the stable request prefix (tools / system / last msg);
- usage folding keeps `promptTokens` meaning "full prompt size" even when the
  API splits out cached tokens (which the compaction middleware relies on).
"""

from __future__ import annotations

from pydantic import BaseModel

from trendpower.community.anthropic.model_provider import AnthropicModelProvider, _to_token_usage
from trendpower.community.anthropic.stream_utils import StreamAccumulator
from trendpower.foundation.tools import define_tool


class _Params(BaseModel):
    x: int = 0


def _tool(name: str):
    async def _invoke(_p, _s=None):
        return "ok"

    return define_tool(name=name, description=f"{name} tool", parameters=_Params, invoke=_invoke)


def _params(*, model="claude-x"):
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": "SYS"}]},
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ],
        "tools": [_tool("a"), _tool("b")],
        "options": None,
    }


_EPHEMERAL = {"type": "ephemeral"}


def test_cache_control_on_stable_prefix_when_enabled():
    provider = AnthropicModelProvider(api_key="test", enable_prompt_caching=True)
    base = provider._base_params(_params())

    # system: structured block carrying cache_control
    assert isinstance(base["system"], list)
    assert base["system"][0]["cache_control"] == _EPHEMERAL
    assert base["system"][0]["text"] == "SYS"

    # tools: only the LAST tool is marked (caches the whole array prefix)
    assert "cache_control" not in base["tools"][0]
    assert base["tools"][-1]["cache_control"] == _EPHEMERAL

    # messages: last block of the last message is marked (incremental prefix)
    assert base["messages"][-1]["content"][-1]["cache_control"] == _EPHEMERAL


def test_no_cache_control_when_disabled():
    provider = AnthropicModelProvider(api_key="test", enable_prompt_caching=False)
    base = provider._base_params(_params())

    assert base["system"] == "SYS"  # plain string, no breakpoint
    assert all("cache_control" not in t for t in base["tools"])
    assert all(
        "cache_control" not in b
        for m in base["messages"]
        for b in m["content"]
    )


def test_to_token_usage_folds_cache_tokens_into_prompt_tokens():
    usage = {
        "input_tokens": 100,
        "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 50,
        "output_tokens": 20,
    }
    out = _to_token_usage(usage)
    assert out is not None
    # 100 + 900 + 50 — the *true* prompt size, not just the uncached 100.
    assert out["promptTokens"] == 1050
    assert out["completionTokens"] == 20
    assert out["totalTokens"] == 1070


def test_stream_accumulator_folds_cache_tokens():
    acc = StreamAccumulator()
    acc.push(
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 900,
                    "cache_creation_input_tokens": 50,
                    "output_tokens": 0,
                }
            },
        }
    )
    acc.push({"type": "message_delta", "usage": {"output_tokens": 20}})
    snap = acc.snapshot()
    assert snap["usage"]["promptTokens"] == 1050
    assert snap["usage"]["completionTokens"] == 20
