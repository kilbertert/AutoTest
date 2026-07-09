"""Accumulate Anthropic stream events into progressive AssistantMessage snapshots.

See the TS source `stream-utils.ts` for the event protocol details:
- message_start — carries initial usage (input tokens).
- content_block_start — opens a block (text, thinking, tool_use).
- content_block_delta — appends to current block.
- message_delta — carries final usage (output tokens).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ...foundation import AssistantMessage, TokenUsage


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class StreamAccumulator:
    def __init__(self) -> None:
        self._blocks: Dict[int, Dict[str, Any]] = {}
        self._input_tokens = 0
        self._output_tokens = 0
        self._has_final_usage = False

    def push(self, event: Any) -> None:
        etype = _get(event, "type")
        if etype == "message_start":
            message = _get(event, "message")
            usage = _get(message, "usage")
            # With prompt caching, `input_tokens` excludes cached tokens; fold
            # cache reads/writes back in so promptTokens reflects the true
            # prompt size (the compaction middleware depends on this).
            input_tokens = _get(usage, "input_tokens") or 0
            cache_read = _get(usage, "cache_read_input_tokens") or 0
            cache_creation = _get(usage, "cache_creation_input_tokens") or 0
            self._input_tokens = input_tokens + cache_read + cache_creation
            self._output_tokens = _get(usage, "output_tokens") or 0
        elif etype == "content_block_start":
            self._handle_block_start(event)
        elif etype == "content_block_delta":
            self._handle_block_delta(event)
        elif etype == "message_delta":
            self._handle_message_delta(event)

    def snapshot(self) -> AssistantMessage:
        content: List[Dict[str, Any]] = []
        for _, block in sorted(self._blocks.items(), key=lambda kv: kv[0]):
            item = _block_to_content(block)
            if item is not None:
                content.append(item)
        result: AssistantMessage = {"role": "assistant", "content": content}  # type: ignore[typeddict-item]
        if self._has_final_usage:
            result["usage"] = {
                "promptTokens": self._input_tokens,
                "completionTokens": self._output_tokens,
                "totalTokens": self._input_tokens + self._output_tokens,
            }
        else:
            result["streaming"] = True
        return result

    def _handle_block_start(self, event: Any) -> None:
        index = _get(event, "index")
        block = _get(event, "content_block")
        btype = _get(block, "type")
        if btype == "text":
            self._blocks[index] = {"type": "text", "text": _get(block, "text") or ""}
        elif btype == "thinking":
            entry: Dict[str, Any] = {
                "type": "thinking",
                "thinking": _get(block, "thinking") or "",
            }
            sig = _get(block, "signature")
            if sig:
                entry["signature"] = sig
            self._blocks[index] = entry
        elif btype == "tool_use":
            self._blocks[index] = {
                "type": "tool_use",
                "id": _get(block, "id"),
                "name": _get(block, "name"),
                "partialJson": "",
            }

    def _handle_block_delta(self, event: Any) -> None:
        index = _get(event, "index")
        block = self._blocks.get(index)
        if block is None:
            return
        delta = _get(event, "delta")
        dtype = _get(delta, "type")
        if dtype == "text_delta" and block["type"] == "text":
            block["text"] += _get(delta, "text") or ""
        elif dtype == "thinking_delta" and block["type"] == "thinking":
            block["thinking"] += _get(delta, "thinking") or ""
        elif dtype == "signature_delta" and block["type"] == "thinking":
            block["signature"] = _get(delta, "signature")
        elif dtype == "input_json_delta" and block["type"] == "tool_use":
            block["partialJson"] += _get(delta, "partial_json") or ""

    def _handle_message_delta(self, event: Any) -> None:
        usage = _get(event, "usage")
        if usage is not None:
            output_tokens = _get(usage, "output_tokens")
            input_tokens = _get(usage, "input_tokens")
            if output_tokens is not None:
                self._output_tokens = output_tokens
            # Only override the input count if this event actually carries one;
            # fold cache tokens back in (consistent with message_start) so the
            # cache-inclusive value from message_start is not clobbered.
            if input_tokens is not None:
                cache_read = _get(usage, "cache_read_input_tokens") or 0
                cache_creation = _get(usage, "cache_creation_input_tokens") or 0
                self._input_tokens = input_tokens + cache_read + cache_creation
        self._has_final_usage = True


def _block_to_content(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    btype = block["type"]
    if btype == "text":
        return {"type": "text", "text": block["text"]} if block["text"] else None
    if btype == "thinking":
        out: Dict[str, Any] = {"type": "thinking", "thinking": block["thinking"]}
        if block.get("signature"):
            out["_anthropicSignature"] = block["signature"]
        return out
    # tool_use
    return {
        "type": "tool_use",
        "id": block["id"],
        "name": block["name"],
        "input": _parse_tool_input(block.get("partialJson", "")),
    }


def _parse_tool_input(partial_json: str) -> Dict[str, Any]:
    if not partial_json:
        return {}
    try:
        return json.loads(partial_json)
    except (json.JSONDecodeError, ValueError):
        return {}
