"""Minimal example: run the coding agent against an OpenAI-compatible endpoint.

Requires environment variables:
- OPENAI_API_KEY (or your provider's key)
- OPENAI_BASE_URL (optional; for OpenAI-compatible endpoints like Ark, OpenRouter, etc.)

Run with: `python examples/basic_openai.py`
"""

from __future__ import annotations

import asyncio
import os

from trendpower.coding import create_coding_agent
from trendpower.community.openai import OpenAIModelProvider
from trendpower.foundation import Model


async def main() -> None:
    provider = OpenAIModelProvider(
        base_url="https://api.aabao.top/v1",
        api_key="",
    )
    model = Model(name=os.environ.get("MODEL", "gpt-4o-mini"), provider=provider)
    agent = await create_coding_agent(model=model)

    user_message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    "请你帮我写一个处理jsonl文件变成json的python代码，并保存在本地 "
                    
                ),
            }
        ],
    }

    async for event in agent.stream(user_message):
        if event["type"] == "message":
            msg = event["message"]
            role = msg["role"]
            for part in msg["content"]:
                if part["type"] == "text":
                    print(f"[{role}] {part['text']}")
                elif part["type"] == "tool_use":
                    print(f"[{role}] -> tool {part['name']}({part['input']})")
                elif part["type"] == "tool_result":
                    print(f"[{role}] <- result {part['content'][:200]}")
                elif part["type"] == "thinking":
                    print(f"[{role}] (thinking) {part['thinking'][:200]}")
        elif event["type"] == "progress":
            # progress events fire many times per second during streaming —
            # leave them off by default to keep the demo readable.
            pass


if __name__ == "__main__":
    asyncio.run(main())
