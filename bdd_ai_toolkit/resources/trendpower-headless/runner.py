#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""trendpower headless runner — invoked by the bdd_ai_toolkit VS Code shell.

Spawned as a subprocess. Reads --prompt and --cwd from argv, emits one NDJSON
event per line on stdout, UTF-8, line-delimited. Designed to be cancelled via
SIGTERM (asyncio.CancelledError path).

MCP servers, LLM keys, and skills all come from ~/.trendpower/ — the runner
never writes config.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

# Make sure stdout is line-buffered (subprocess pipes need this).
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # py3.7+
except Exception:
    pass


def emit(**kwargs) -> None:
    """Emit one NDJSON event to stdout."""
    kwargs.setdefault("ts", time.time())
    sys.stdout.write(json.dumps(kwargs, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def short_id() -> str:
    return uuid.uuid4().hex[:12]


async def main() -> int:
    ap = argparse.ArgumentParser(description="trendpower headless runner")
    ap.add_argument("--prompt", required=True, help="User prompt")
    ap.add_argument("--cwd", default=os.getcwd(), help="Working directory for the agent")
    ap.add_argument(
        "--mcp-config",
        default=str(Path.home() / ".trendpower" / "mcp_servers.json"),
        help="Path to mcp_servers.json",
    )
    ap.add_argument(
        "--provider",
        default=os.environ.get("TRENDPOWER_PROVIDER", "openai"),
        choices=["openai", "anthropic"],
        help="Model provider (default: env TRENDPOWER_PROVIDER or 'openai')",
    )
    ap.add_argument(
        "--model",
        default=os.environ.get("TRENDPOWER_MODEL", "gpt-4o-mini"),
        help="Model name (default: env TRENDPOWER_MODEL or 'gpt-4o-mini')",
    )
    ap.add_argument(
        "--base-url",
        default=os.environ.get("TRENDPOWER_BASE_URL"),
        help="Override base URL (e.g. https://api.minimaxi.com/anthropic for a "
             "non-default endpoint). Default: provider's own URL.",
    )
    args = ap.parse_args()

    run_id = short_id()
    emit(type="session_start", run_id=run_id, cwd=args.cwd, model=args.model, provider=args.provider)

    # ─── import trendpower ──────────────────────────────────────────────
    try:
        from trendpower.foundation import Model  # noqa: F401
        from trendpower.community.mcp import MCPManager, load_servers_from_file  # noqa: F401
        from trendpower.coding import create_coding_agent  # noqa: F401
    except ImportError as e:
        emit(
            type="error",
            message=(
                f"trendpower not importable: {e}. "
                "Install with: pip install -e /path/to/trendpower/trendpower-py "
                "(or `uv tool install --editable ...`)."
            ),
        )
        emit(type="session_end", run_id=run_id, ok=False, duration_ms=0)
        return 1

    # ─── model ──────────────────────────────────────────────────────────
    try:
        if args.provider == "anthropic":
            from trendpower.community.anthropic import AnthropicModelProvider
            # Pick up API key from env (the upstream env name the user typically
            # sets); AnthropicModelProvider requires explicit kwargs.
            api_key = (
                os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("TRENDPOWER_API_KEY")
            )
            provider_kwargs: dict = {}
            if api_key:
                provider_kwargs["api_key"] = api_key
            if args.base_url:
                provider_kwargs["base_url"] = args.base_url
            provider = AnthropicModelProvider(**provider_kwargs)
        else:
            from trendpower.community.openai import OpenAIModelProvider
            api_key = (
                os.environ.get("OPENAI_API_KEY")
                or os.environ.get("TRENDPOWER_API_KEY")
            )
            provider_kwargs = {}
            if api_key:
                provider_kwargs["api_key"] = api_key
            if args.base_url:
                provider_kwargs["base_url"] = args.base_url
            provider = OpenAIModelProvider(**provider_kwargs)
        model = Model(name=args.model, provider=provider)
    except Exception as e:
        emit(type="error", message=f"failed to create model provider: {e}", trace=traceback.format_exc())
        emit(type="session_end", run_id=run_id, ok=False, duration_ms=0)
        return 1

    # ─── MCP config ─────────────────────────────────────────────────────
    cfgs = []
    config_path = Path(args.mcp_config)
    if config_path.exists():
        try:
            cfgs = load_servers_from_file(config_path)
            emit(type="status", phase="mcp_config_loaded", detail=f"{len(cfgs)} server(s) from {config_path}")
        except Exception as e:
            emit(type="error", message=f"failed to parse {config_path}: {e}")
            emit(type="session_end", run_id=run_id, ok=False, duration_ms=0)
            return 1
    else:
        emit(type="status", phase="mcp_config_missing", detail=f"{config_path} not found; running without MCP tools")

    # ─── MCP connect ────────────────────────────────────────────────────
    mgr = MCPManager(cfgs) if cfgs else None
    mcp_tools = None
    if mgr is not None:
        emit(type="status", phase="connecting_mcp", detail=f"connecting to {len(cfgs)} server(s)…")
        try:
            mcp_tools = await mgr.connect_all()
            emit(type="status", phase="mcp_ready", detail=f"{len(mcp_tools)} tool(s) available")
        except Exception as e:
            emit(type="error", message=f"MCP connect failed: {e}", trace=traceback.format_exc())
            emit(type="session_end", run_id=run_id, ok=False, duration_ms=0)
            try:
                await mgr.aclose()
            except Exception:
                pass
            return 1

    # ─── agent ──────────────────────────────────────────────────────────
    cwd_path = Path(args.cwd)
    emit(type="status", phase="agent_creating", detail=f"cwd={cwd_path}")
    try:
        agent = await create_coding_agent(
            model=model,
            cwd=str(cwd_path),
            extra_tools=mcp_tools or None,
        )
    except Exception as e:
        emit(type="error", message=f"create_coding_agent failed: {e}", trace=traceback.format_exc())
        emit(type="session_end", run_id=run_id, ok=False, duration_ms=0)
        if mgr is not None:
            try:
                await mgr.aclose()
            except Exception:
                pass
        return 1

    # ─── stream ─────────────────────────────────────────────────────────
    user_message = {
        "role": "user",
        "content": [{"type": "text", "text": args.prompt}],
    }

    started = time.time()
    last_assistant_text = ""
    # Real Agent.stream() events are:
    #   {"type": "progress", "subtype": "thinking"}                → thinking
    #   {"type": "progress", "subtype": "tool", "name", "input"}  → tool_call (no id at progress time)
    #   {"type": "message", "message": {role: assistant, content: [...]}}   → assistant_text
    #   {"type": "message", "message": {role: tool, content: [{type: tool_result, tool_use_id, content}]}}
    #                                                                → tool_result
    #   {"type": "_think_done", ...}                               → INTERNAL SENTINEL, never emit
    pending_tool_use: dict[str, tuple[str, object]] = {}
    run_ok = True

    try:
        async for event in agent.stream(user_message):
            et = event.get("type") if isinstance(event, dict) else None

            if et == "_think_done":
                # Internal sentinel from Agent._think — do not forward to webview.
                continue

            if et == "progress":
                sub = event.get("subtype")
                if sub == "thinking":
                    # No text attached at progress time; emit a heartbeat.
                    emit(type="status", phase="thinking", detail="")
                elif sub == "tool":
                    # The progress tool event doesn't carry an id; we'll match it
                    # up by (name, input) when the tool_use part arrives in the
                    # assistant message.
                    emit(
                        type="status",
                        phase="tool_pending",
                        detail=f"{event.get('name', '')}({json.dumps(event.get('input'), ensure_ascii=False)[:120]})",
                    )
                continue

            if et != "message":
                # Unknown event shape — surface as raw status for debugging.
                emit(type="status", phase="raw", detail=json.dumps(event, ensure_ascii=False)[:400])
                continue

            msg = event.get("message") or {}
            role = msg.get("role")
            content = msg.get("content") or []
            if not isinstance(content, list):
                content = []

            for part in content:
                if not isinstance(part, dict):
                    continue
                pt = part.get("type")

                if pt == "text" and role == "assistant":
                    text = str(part.get("text") or "")
                    if text:
                        last_assistant_text += text
                        emit(type="assistant_text", text=text)

                elif pt == "tool_use":
                    tid = str(part.get("id") or short_id())
                    name = str(part.get("name") or "")
                    inp = part.get("input")
                    pending_tool_use[tid] = (name, inp)
                    emit(type="tool_call", id=tid, name=name, input=inp)

                elif pt == "tool_result":
                    tid = str(part.get("tool_use_id") or "")
                    raw = part.get("content")
                    if isinstance(raw, list):
                        flat = []
                        for p in raw:
                            if isinstance(p, dict) and p.get("type") == "text":
                                flat.append(str(p.get("text") or ""))
                        out_text = "\n".join(flat)
                    else:
                        out_text = "" if raw is None else str(raw)
                    name = pending_tool_use.get(tid, ("", None))[0]
                    is_err = bool(part.get("is_error"))
                    if len(out_text) > 4000:
                        out_text = out_text[:4000] + "\n…[truncated]"
                    emit(
                        type="tool_result",
                        tool_call_id=tid,
                        name=name,
                        output=out_text,
                        is_error=is_err,
                        elapsed_ms=0,
                    )

        emit(type="assistant_final", text=last_assistant_text)

    except asyncio.CancelledError:
        emit(type="status", phase="cancelled", detail="user requested stop")
        run_ok = False
    except Exception as e:
        emit(type="error", message=f"agent.stream failed: {e}", trace=traceback.format_exc())
        run_ok = False
    finally:
        if mgr is not None:
            try:
                await mgr.aclose()
            except Exception:
                pass
        emit(
            type="session_end",
            run_id=run_id,
            ok=run_ok,
            duration_ms=int((time.time() - started) * 1000),
        )

    return 0 if run_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        # Parent sent SIGTERM; asyncio.run already cancelled the inner task.
        sys.exit(130)