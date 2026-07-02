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


# ─── checkpoints ────────────────────────────────────────────────────────
# Resume support: after every tool_result we snapshot the agent transcript
# to ~/.trendpower/checkpoints/<run_id>.json so a crashed/killed run can be
# resumed later via --resume <run_id>. Atomic write (tmp + replace).

CHECKPOINT_DIR = Path.home() / ".trendpower" / "checkpoints"


def checkpoint_path(run_id: str) -> Path:
    return CHECKPOINT_DIR / f"{run_id}.json"


def load_checkpoint(run_id: str) -> dict | None:
    """Load a previously persisted transcript. Returns None if missing."""
    p = checkpoint_path(run_id)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        emit(type="status", phase="checkpoint_load_failed", detail=str(e))
        return None


# ─── progress reporting tools ───────────────────────────────────────────
# The qumall-fulltest skill calls these to surface structured progress to the
# webview. They are plain function tools (not MCP); the runner registers them
# as extra_tools alongside the MCP set. Each call emits one NDJSON event.

class _ProgressState:
    """Mutable progress snapshot, also serialized into the checkpoint."""

    def __init__(self) -> None:
        self.done = 0
        self.total = 0
        self.failed = 0
        self.module: str | None = None
        self.modules: dict[str, str] = {}  # module -> pending|running|passed|failed
        # Last known stable page URL (the most recent navigate_page URL).
        # Used on --resume to re-open the tab the agent was working on.
        self.last_url: str | None = None

    def snapshot(self) -> dict:
        return {
            "done": self.done,
            "total": self.total,
            "failed": self.failed,
            "module": self.module,
            "modules": dict(self.modules),
            "last_url": self.last_url,
        }


def build_reporting_tools(state: _ProgressState):
    """Build report_progress / report_module_status tools bound to `state`."""
    from pydantic import BaseModel

    from trendpower.foundation.tools import define_tool

    class ReportProgressParams(BaseModel):
        done: int
        total: int
        failed: int = 0
        module: str | None = None

    class ReportModuleStatusParams(BaseModel):
        module: str
        state: str  # pending|running|passed|failed

    async def report_progress(params: ReportProgressParams) -> dict:
        state.done = params.done
        state.total = params.total
        state.failed = params.failed
        if params.module is not None:
            state.module = params.module
        emit(
            type="progress",
            done=state.done,
            total=state.total,
            failed=state.failed,
            module=state.module,
        )
        return {"ok": True, "summary": f"progress {state.done}/{state.total} (failed={state.failed})"}

    async def report_module_status(params: ReportModuleStatusParams) -> dict:
        state.modules[params.module] = params.state
        emit(type="module_status", module=params.module, state=params.state)
        return {"ok": True, "summary": f"module {params.module}: {params.state}"}

    return [
        define_tool(
            name="report_progress",
            description=(
                "Report structured test execution progress to the UI. Call this "
                "after each test case is executed (and after design is complete "
                "to set the total). done=cases executed, total=total cases "
                "planned, failed=cases that did not pass."
            ),
            parameters=ReportProgressParams,
            invoke=report_progress,
        ),
        define_tool(
            name="report_module_status",
            description=(
                "Report the state of one test module (section) to the UI. state "
                "is one of: pending, running, passed, failed. Call when starting/"
                "finishing a module."
            ),
            parameters=ReportModuleStatusParams,
            invoke=report_module_status,
        ),
    ]


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
    ap.add_argument(
        "--run-id",
        default=None,
        help="Stable run identifier (used for the checkpoint filename). "
             "If omitted, a random id is generated.",
    )
    ap.add_argument(
        "--resume",
        default=None,
        help="Resume a previous run by run_id. Loads the saved transcript from "
             "~/.trendpower/checkpoints/<run_id>.json and continues. The --prompt "
             "is still required as the resume nudge.",
    )
    ap.add_argument(
        "--skill",
        default=None,
        help="Force-activate a skill by name (e.g. qumall-fulltest). The skill "
             "file is read first even if the user prompt is short.",
    )
    args = ap.parse_args()

    run_id = args.run_id or args.resume or short_id()
    emit(type="session_start", run_id=run_id, cwd=args.cwd, model=args.model, provider=args.provider, resume=bool(args.resume), skill=args.skill)

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

    progress_state = _ProgressState()
    reporting_tools = build_reporting_tools(progress_state)
    extra_tools = list(mcp_tools or [])
    extra_tools.extend(reporting_tools)

    try:
        agent = await create_coding_agent(
            model=model,
            cwd=str(cwd_path),
            extra_tools=extra_tools or None,
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

    # ─── skill + resume ─────────────────────────────────────────────────
    if args.skill:
        agent.set_requested_skill_name(args.skill)
        emit(type="status", phase="skill_requested", detail=args.skill)

    if args.resume:
        ckpt = load_checkpoint(args.resume)
        if ckpt is None:
            emit(type="error", message=f"no checkpoint found for run_id={args.resume}")
            emit(type="session_end", run_id=run_id, ok=False, duration_ms=0)
            if mgr is not None:
                try:
                    await mgr.aclose()
                except Exception:
                    pass
            return 1
        saved_msgs = ckpt.get("messages") or []
        agent.load_messages(saved_msgs)
        # Re-emit last known progress so the UI restores its state.
        snap = ckpt.get("progress") or {}
        if snap:
            progress_state.done = snap.get("done", 0)
            progress_state.total = snap.get("total", 0)
            progress_state.failed = snap.get("failed", 0)
            progress_state.module = snap.get("module")
            progress_state.modules = dict(snap.get("modules") or {})
            emit(
                type="progress",
                done=progress_state.done,
                total=progress_state.total,
                failed=progress_state.failed,
                module=progress_state.module,
            )
            for mod, st in progress_state.modules.items():
                emit(type="module_status", module=mod, state=st)
        emit(type="status", phase="resumed", detail=f"loaded {len(saved_msgs)} message(s) from checkpoint")

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
                    # Track the most recent stable URL so a resume can re-open
                    # the same module's tab. Tolerates both {"url": "..."} and
                    # {"type": "url", "url": "..."} shapes that chrome-devtools
                    # tools have used across versions.
                    if name in ("chrome-devtools__navigate_page", "chrome-devtools__new_page") and isinstance(inp, dict):
                        url = inp.get("url")
                        if isinstance(url, str) and url.startswith(("http://", "https://")):
                            progress_state.last_url = url

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
                    # CDP target recovery hint: when a chrome-devtools tool
                    # fails with "Target closed" (typical after an SPA route
                    # change), emit a follow-up status event so the agent
                    # knows to call chrome-devtools__list_pages + re-select
                    # (or re-new_page) and retry once. Defined in
                    # qumall-fulltest SKILL.md §2.6.
                    if is_err and name.startswith("chrome-devtools__") and (
                        "Target closed" in out_text
                        or "Session closed" in out_text
                        or "no such target" in out_text
                    ):
                        emit(
                            type="status",
                            phase="cdp_target_recover",
                            detail=(
                                f"chrome-devtools target detached after {name}. "
                                "Call chrome-devtools__list_pages, re-select or "
                                "new_page the expected module URL, then retry "
                                "the original tool call once."
                            ),
                        )
                    # Persist transcript + progress so a crash can be resumed.
                    try:
                        ckpt = {
                            "run_id": run_id,
                            "saved_at": time.time(),
                            "messages": agent.messages,
                            "progress": progress_state.snapshot(),
                        }
                        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
                        tmp = checkpoint_path(run_id).with_suffix(".json.tmp")
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(ckpt, f, ensure_ascii=False)
                        os.replace(tmp, checkpoint_path(run_id))
                    except Exception as e:
                        emit(type="status", phase="checkpoint_save_failed", detail=str(e))

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