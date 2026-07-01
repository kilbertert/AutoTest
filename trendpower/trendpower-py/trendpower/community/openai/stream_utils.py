"""Accumulate OpenAI streaming deltas into progressive AssistantMessage snapshots."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ...foundation import AssistantMessage, TokenUsage


def _to_token_usage(usage: Any) -> Optional[TokenUsage]:
    if usage is None:
        return None

    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    return {
        "promptTokens": _get(usage, "prompt_tokens") or 0,
        "completionTokens": _get(usage, "completion_tokens") or 0,
        "totalTokens": _get(usage, "total_tokens") or 0,
    }


def _get_reasoning_content(delta: Any) -> Optional[str]:
    if delta is None:
        return None
    if isinstance(delta, dict):
        v = delta.get("reasoning_content")
    else:
        v = getattr(delta, "reasoning_content", None)
    return v if isinstance(v, str) else None


class StreamAccumulator:
    def __init__(self) -> None:
        self._reasoning_content: str = ""
        self._text_content: str = ""
        self._tool_calls: Dict[int, Dict[str, Any]] = {}
        self._usage: Optional[TokenUsage] = None

    def push(self, chunk: Any) -> None:
        def _get(obj: Any, key: str) -> Any:
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        choices = _get(chunk, "choices") or []
        if choices:
            delta = _get(choices[0], "delta")
            if delta is not None:
                reasoning = _get_reasoning_content(delta)
                if reasoning:
                    self._reasoning_content += reasoning

                content = _get(delta, "content")
                if isinstance(content, str):
                    self._text_content += content

                tool_calls_delta = _get(delta, "tool_calls") or []
                for tc in tool_calls_delta:
                    idx = _get(tc, "index")
                    if idx is None:
                        continue
                    entry = self._tool_calls.get(idx)
                    if entry is None:
                        entry = {"id": _get(tc, "id") or "", "name": "", "arguments": ""}
                        func = _get(tc, "function")
                        if func is not None:
                            entry["name"] = _get(func, "name") or ""
                        self._tool_calls[idx] = entry
                    tc_id = _get(tc, "id")
                    if tc_id:
                        entry["id"] = tc_id
                    func = _get(tc, "function")
                    if func is not None:
                        fname = _get(func, "name")
                        if fname:
                            entry["name"] = fname
                        fargs = _get(func, "arguments")
                        if fargs:
                            entry["arguments"] += fargs

        # Usage arrives on the final chunk (choices is empty)
        usage = _get(chunk, "usage")
        if usage:
            self._usage = _to_token_usage(usage)

    def snapshot(self) -> AssistantMessage:
        content: list = []
        if self._reasoning_content:
            content.append({"type": "thinking", "thinking": self._reasoning_content})
        if self._text_content:
            content.append({"type": "text", "text": self._text_content})

        is_final = self._usage is not None
        for _, tc in sorted(self._tool_calls.items(), key=lambda kv: kv[0]):
            parsed = False
            tool_input: Dict[str, Any] = {}
            try:
                tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
                parsed = True
            except (json.JSONDecodeError, ValueError):
                pass
            if not parsed and not is_final:
                continue
            content.append(
                {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tool_input}
            )

        result: AssistantMessage = {"role": "assistant", "content": content}
        if self._usage is not None:
            result["usage"] = self._usage
        else:
            result["streaming"] = True
        return result
