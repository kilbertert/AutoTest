"""Minimal example: run the coding agent against the Anthropic API.

Requires environment variables:
- ANTHROPIC_API_KEY

Run with: `python examples/basic_anthropic.py`
"""

from __future__ import annotations

import asyncio
import os

from trendpower.coding import create_coding_agent
from trendpower.community.anthropic import AnthropicModelProvider
from trendpower.foundation import Model


async def main() -> None:
    provider = AnthropicModelProvider(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = Model(name=os.environ.get("MODEL", "claude-sonnet-4-5"), provider=provider)
    agent = await create_coding_agent(model=model)

    user_message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "Briefly tell me what files exist in the current working directory. Use list_files. Then stop.",
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


if __name__ == "__main__":
    asyncio.run(main())
