"""mimo API client — direct HTTP, no trendpower.

Why this exists: trendpower's agent loop is a black box that bakes in a
540s/600s per-session cap (we hit it during the pilot runs). For long
batch jobs (100s-1000s of cases, 24/7) we want a thin HTTP client that
just makes chat calls and returns the response. Stdlib only so it
runs on any Windows machine with no extra install.

Usage:
    from mimo_client import chat
    reply = chat("你是什么模型?", system="你是助手")
    # "我是 MiniMax..."
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

# Defaults match the env vars we set on the Windows runner.
_BASE_URL = os.environ.get("TRENDPOWER_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
_API_KEY = os.environ.get("OPENAI_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
_MODEL = os.environ.get("TRENDPOWER_MODEL", "mimo-v2.5-pro")

# Per-call timeout. Cases that need more thinking get retried; we don't
# let any single call hang longer than this.
_DEFAULT_TIMEOUT_S = 120

# How many times to retry on 429 / 5xx with exponential backoff.
_MAX_RETRIES = 3


def _request(messages: list[dict], *, timeout_s: int = _DEFAULT_TIMEOUT_S,
             temperature: float = 0.0, max_tokens: int = 4096) -> str:
    """Make one OpenAI-compatible chat completion call and return the content."""
    url = _BASE_URL.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": _MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")
    last_err: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_API_KEY}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            return content if isinstance(content, str) else str(content)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 or 500 <= e.code < 600:
                # rate-limited or transient server error; back off and retry
                time.sleep(2 ** attempt)
                continue
            # 4xx (other) — fail fast, no point retrying
            raise RuntimeError(f"mimo {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"mimo call failed after {_MAX_RETRIES} retries: {last_err}")


def chat(prompt: str, *, system: Optional[str] = None,
         temperature: float = 0.0, max_tokens: int = 4096,
         timeout_s: int = _DEFAULT_TIMEOUT_S) -> str:
    """One-shot chat call. `prompt` is the user message; optional system
    instruction goes into the system slot. Returns the assistant's text."""
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _request(messages, timeout_s=timeout_s,
                    temperature=temperature, max_tokens=max_tokens)


if __name__ == "__main__":
    # Smoke test from CLI: `python mimo_client.py 你好`
    import sys
    msg = sys.argv[1] if len(sys.argv) > 1 else "用一句话确认你能工作"
    print(chat(msg))
