"""A middleware that turns the agent's 8 lifecycle hooks into a span tree.

Span shape, per agent run:

    run                         (one per stream() call / user turn)
    └─ step                     (one per ReAct step)
       ├─ llm                   (the model call)
       └─ tool …                (parallel tool calls; ids = tool_use ids)

It only ever *reads* the context, so it can sit anywhere in the middleware
chain. Every hook is wrapped so a tracing bug can never crash the agent —
observability must not endanger the task it observes.
"""

from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace
from typing import Any, Optional

from .events import new_span_id, point_event, span_end, span_start
from .sinks import TraceSink

_log = logging.getLogger("trendpower.tracing")

_MAX_INPUT_CHARS = 500


def _ms(start: Optional[float]) -> Optional[float]:
    if start is None:
        return None
    return round((time.perf_counter() - start) * 1000, 1)


def _truncate_input(value: Any, limit: int = _MAX_INPUT_CHARS) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _result_ok(result: Any) -> bool:
    """Best-effort success flag for a tool result (mirrors the tool_result shapes)."""
    if isinstance(result, dict) and "ok" in result:
        return bool(result.get("ok"))
    if isinstance(result, str) and result.startswith("Error:"):
        return False
    return True


def create_tracing_middleware(
    sink: TraceSink,
    *,
    model_name: Optional[str] = None,
    is_subagent: bool = False,
) -> Any:
    """Return a middleware (duck-typed ``SimpleNamespace``) that emits to ``sink``.

    ``is_subagent`` marks runs spawned via the ``task`` tool: they reuse the
    parent's sink, do not rotate its file, and link to the parent run via
    ``sink.current_top_run_id`` captured at run start.
    """

    st = SimpleNamespace(
        run_id=None,
        current_step_id=None,
        model_start=None,
        model_span_id=None,
        step_start={},  # step int -> perf_counter
        tool_start={},  # tool_use id -> perf_counter
    )

    def _emit(event: Any) -> None:
        try:
            sink.emit(event)
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace emit failed: %s", exc)

    async def before_agent_run(params: Any) -> None:
        try:
            run_id = new_span_id("run")
            st.run_id = run_id
            st.current_step_id = run_id
            parent = sink.current_top_run_id if is_subagent else None
            sink.begin_run(run_id, is_top=not is_subagent)
            tools = params["agentContext"].get("tools") or []
            _emit(
                span_start(
                    "run",
                    run_id,
                    parent,
                    model=model_name,
                    tools=len(tools),
                    subagent=is_subagent,
                )
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace beforeAgentRun failed: %s", exc)
        return None

    async def after_agent_run(params: Any) -> None:
        try:
            if st.run_id:
                _emit(span_end("run", st.run_id, outcome="completed"))
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace afterAgentRun failed: %s", exc)
        return None

    async def before_agent_step(params: Any) -> None:
        try:
            step = params["step"]
            sid = f"{st.run_id}:step:{step}"
            st.current_step_id = sid
            st.step_start[step] = time.perf_counter()
            _emit(span_start("step", sid, st.run_id, step=step))
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace beforeAgentStep failed: %s", exc)
        return None

    async def after_agent_step(params: Any) -> None:
        try:
            step = params["step"]
            sid = f"{st.run_id}:step:{step}"
            _emit(span_end("step", sid, duration_ms=_ms(st.step_start.pop(step, None))))
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace afterAgentStep failed: %s", exc)
        return None

    async def before_model(params: Any) -> None:
        try:
            st.model_start = time.perf_counter()
            st.model_span_id = new_span_id("llm")
            _emit(span_start("llm", st.model_span_id, st.current_step_id))
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace beforeModel failed: %s", exc)
        return None

    async def after_model(params: Any) -> None:
        try:
            usage = (params["message"].get("usage") or {}) if params.get("message") else {}
            span_id = st.model_span_id or new_span_id("llm")
            _emit(
                span_end(
                    "llm",
                    span_id,
                    duration_ms=_ms(st.model_start),
                    prompt_tokens=usage.get("promptTokens"),
                    completion_tokens=usage.get("completionTokens"),
                    total_tokens=usage.get("totalTokens"),
                )
            )
            st.model_start = None
            st.model_span_id = None
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace afterModel failed: %s", exc)
        return None

    async def before_tool_use(params: Any) -> None:
        try:
            tu = params["toolUse"]
            tid = tu["id"]
            st.tool_start[tid] = time.perf_counter()
            _emit(
                span_start(
                    "tool",
                    tid,
                    st.current_step_id,
                    name=tu.get("name"),
                    input=_truncate_input(tu.get("input")),
                )
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace beforeToolUse failed: %s", exc)
        return None  # never skips a tool

    async def after_tool_use(params: Any) -> None:
        try:
            tu = params["toolUse"]
            tid = tu["id"]
            _emit(
                span_end(
                    "tool",
                    tid,
                    duration_ms=_ms(st.tool_start.pop(tid, None)),
                    ok=_result_ok(params.get("toolResult")),
                )
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace afterToolUse failed: %s", exc)
        return None

    def emit_compaction(event: Any) -> None:
        """Hook for the compaction middleware's ``on_compaction`` callback."""
        try:
            _emit(
                point_event(
                    "compaction",
                    st.run_id or sink.current_top_run_id,
                    messages_before=getattr(event, "messages_before", None),
                    messages_after=getattr(event, "messages_after", None),
                    estimated_tokens=getattr(event, "estimated_tokens", None),
                    summarized=getattr(event, "summarized_messages", None),
                )
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("trace compaction event failed: %s", exc)

    middleware = SimpleNamespace(
        beforeAgentRun=before_agent_run,
        afterAgentRun=after_agent_run,
        beforeAgentStep=before_agent_step,
        afterAgentStep=after_agent_step,
        beforeModel=before_model,
        afterModel=after_model,
        beforeToolUse=before_tool_use,
        afterToolUse=after_tool_use,
        # Not an agent hook; exposed so the caller can forward compaction events.
        emit_compaction=emit_compaction,
    )
    return middleware
