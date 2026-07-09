"""Convert between trendpower messages and OpenAI Chat Completions message shapes."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ...foundation import AssistantMessage, Message, TokenUsage, Tool


def convert_to_openai_messages(messages: List[Message]) -> List[Dict[str, Any]]:
    """Trendpower Message[] -> OpenAI ChatCompletionMessageParam[]."""
    openai_messages: List[Dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "system" or role == "user":
            openai_messages.append({"role": role, "content": message["content"]})
        elif role == "assistant":
            assistant_message: Dict[str, Any] = {"role": "assistant", "content": []}
            assistant_message["reasoning_content"] = ""
            for content in message["content"]:
                ctype = content["type"]
                if ctype == "thinking":
                    assistant_message["reasoning_content"] = content["thinking"]
                elif ctype == "tool_use":
                    assistant_message.setdefault("tool_calls", []).append(
                        {
                            "type": "function",
                            "id": content["id"],
                            "function": {
                                "name": content["name"],
                                "arguments": json.dumps(content["input"]),
                            },
                        }
                    )
                else:
                    # text content
                    assistant_message["content"].append({"type": "text", "text": content["text"]})
            if isinstance(assistant_message["content"], list) and len(assistant_message["content"]) == 0:
                assistant_message["content"] = ""
            openai_messages.append(assistant_message)
        elif role == "tool":
            for content in message["content"]:
                if content["type"] == "tool_result":
                    openai_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": content["tool_use_id"],
                            "content": content["content"],
                        }
                    )
    return openai_messages


def parse_assistant_message(
    message: Any, usage: Optional[TokenUsage] = None
) -> AssistantMessage:
    """OpenAI ChatCompletionMessage -> trendpower AssistantMessage."""
    result: AssistantMessage = {"role": "assistant", "content": []}
    if usage is not None:
        result["usage"] = usage

    # message may be a pydantic model (openai SDK) or a dict.
    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    reasoning = _get(message, "reasoning_content")
    if isinstance(reasoning, str):
        result["content"].append({"type": "thinking", "thinking": reasoning})

    content = _get(message, "content")
    if isinstance(content, str):
        result["content"].append({"type": "text", "text": content})

    tool_calls = _get(message, "tool_calls") or []
    for tc in tool_calls:
        tc_type = _get(tc, "type")
        if tc_type == "function":
            func = _get(tc, "function")
            result["content"].append(
                {
                    "type": "tool_use",
                    "id": _get(tc, "id"),
                    "name": _get(func, "name"),
                    "input": json.loads(_get(func, "arguments") or "{}"),
                }
            )
    return result


def convert_to_openai_tools(tools: List[Tool]) -> List[Dict[str, Any]]:
    """Trendpower Tool[] -> OpenAI ChatCompletionTool[]."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.raw_input_schema or tool.parameters.model_json_schema(),
            },
        }
        for tool in tools
    ]
