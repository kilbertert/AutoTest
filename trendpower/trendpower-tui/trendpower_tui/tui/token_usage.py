"""Token usage summary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenUsageSummary:
    latest_input_tokens: int
    session_total_tokens: int


def calculate_token_usage(messages: list[dict[str, Any]]) -> TokenUsageSummary:
    latest_input = 0
    session_total = 0
    for message in messages:
        if message.get("role") != "assistant":
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        latest_input = int(usage.get("promptTokens") or 0)
        session_total += int(usage.get("totalTokens") or 0)
    return TokenUsageSummary(latest_input_tokens=latest_input, session_total_tokens=session_total)


def format_token_count(count: int) -> str:
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)
