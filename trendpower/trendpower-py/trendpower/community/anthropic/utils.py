"""Convert between trendpower messages and Anthropic message shapes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...foundation import AssistantMessage, Message, TokenUsage, Tool


def extract_system_prompt(messages: List[Message]) -> Optional[str]:
    """Anthropic takes the system prompt as a separate parameter."""
    system_messages = [m for m in messages if m["role"] == "system"]
    if not system_messages:
        return None
    parts: List[str] = []
    for m in system_messages:
        for c in m["content"]:
            if c.get("type") == "text":
                parts.append(c["text"])
    return "\n\n".join(parts)


def convert_to_anthropic_messages(messages: List[Message]) -> List[Dict[str, Any]]:
    """Trendpower Message[] -> Anthropic MessageParam[]."""
    result: List[Dict[str, Any]] = []

    for message in messages:
        role = message["role"]
        if role == "system":
            continue

        if role == "user":
            content: List[Dict[str, Any]] = []
            for part in message["content"]:
                if part["type"] == "text":
                    content.append({"type": "text", "text": part["text"]})
                elif part["type"] == "image_url":
                    content.append(
                        {
                            "type": "image",
                            "source": {"type": "url", "url": part["image_url"]["url"]},
                        }
                    )
            result.append({"role": "user", "content": content})
        elif role == "assistant":
            content = []
            for part in message["content"]:
                ptype = part["type"]
                if ptype == "text":
                    content.append({"type": "text", "text": part["text"]})
                elif ptype == "thinking":
                    signature = part.get("_anthropicSignature", "")
                    content.append(
                        {
                            "type": "thinking",
                            "thinking": part["thinking"],
                            "signature": signature,
                        }
                    )
                elif ptype == "tool_use":
                    content.append(
                        {
                            "type": "tool_use",
                            "id": part["id"],
                            "name": part["name"],
                            "input": part["input"],
                        }
                    )
            result.append({"role": "assistant", "content": content})
        elif role == "tool":
            content = []
            for part in message["content"]:
                if part["type"] == "tool_result":
                    content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": part["tool_use_id"],
                            "content": part["content"],
                        }
                    )
            # Anthropic expects tool results inside a user-role message.
            result.append({"role": "user", "content": content})

    return result


def parse_assistant_message(response: Any, usage: Optional[TokenUsage] = None) -> AssistantMessage:
    """Anthropic API response -> trendpower AssistantMessage."""
    result: AssistantMessage = {"role": "assistant", "content": []}
    if usage is not None:
        result["usage"] = usage

    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    blocks = _get(response, "content") or []
    for block in blocks:
        btype = _get(block, "type")
        if btype == "text":
            result["content"].append({"type": "text", "text": _get(block, "text") or ""})
        elif btype == "thinking":
            thinking_content: Dict[str, Any] = {
                "type": "thinking",
                "thinking": _get(block, "thinking") or "",
            }
            signature = _get(block, "signature")
            if signature:
                thinking_content["_anthropicSignature"] = signature
            result["content"].append(thinking_content)  # type: ignore[arg-type]
        elif btype == "tool_use":
            result["content"].append(
                {
                    "type": "tool_use",
                    "id": _get(block, "id"),
                    "name": _get(block, "name"),
                    "input": _get(block, "input") or {},
                }
            )
    return result


def convert_to_anthropic_tools(tools: List[Tool]) -> List[Dict[str, Any]]:
    """Trendpower Tool[] -> Anthropic tool definitions."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.raw_input_schema or tool.parameters.model_json_schema(),
        }
        for tool in tools
    ]
