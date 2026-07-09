#!/usr/bin/env python3
"""Filter the verbose NDJSON runner log into a compact key-events view.

Reads C:/Users/admin/.trendpower/runs/<run_id>.ndjson.log and prints only
the lines worth eyeballing while a long run is in progress:

  - session_start / session_end
  - status phase=mcp_ready / checkpoint_* / cancelled / error
  - progress (per-case)
  - module_status
  - tool_call / tool_result (only the names + a 1-line summary)
  - assistant_final
  - error

Writes to stdout one line per event, prefixed with [ts_short] for easy
sorting. Default output is human-readable; pass --json for machine-readable.

Usage:
  python qumall-db/filter_log.py qumall-batch-150
  python qumall-db/filter_log.py qumall-batch-150 --json
  python qumall-db/filter_log.py qumall-batch-150 --tail 50
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".trendpower" / "runs"
KEEP_TYPES = {
    "session_start",
    "session_end",
    "status",
    "progress",
    "module_status",
    "assistant_final",
    "error",
}

# status phases we keep; everything else (mcp_config_loaded, tool_pending,
# thinking, etc.) is noise during a long run.
KEEP_STATUS_PHASES = {
    "mcp_ready",
    "agent_creating",
    "skill_requested",
    "resumed",
    "cancelled",
    "checkpoint_save_failed",
    "checkpoint_load_failed",
    "running",
    "stopping",
}

# When emitting tool_call, what fraction of input JSON to show.
MAX_INPUT_CHARS = 240


def _ts_short(ts: float | None) -> str:
    if not ts:
        return "       "
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _summarize_tool(name: str, obj: dict) -> str:
    if name == "report_progress":
        inp = obj.get("input") or {}
        return f"progress done={inp.get('done')} total={inp.get('total')} failed={inp.get('failed')} module={inp.get('module')!r}"
    if name == "report_module_status":
        inp = obj.get("input") or {}
        return f"module {inp.get('module')!r} → {inp.get('state')!r}"
    if name == "bash":
        cmd = (obj.get("input") or {}).get("command", "")
        return f"bash: {cmd[:140]}"
    if name == "excelio__update_cells":
        u = (obj.get("input") or {}).get("updates") or []
        rows = sorted({x.get("row") for x in u})
        return f"update_cells rows={rows} col={[x.get('col') for x in u]}"
    if name == "chrome-devtools__take_screenshot":
        return f"take_screenshot filePath={(obj.get('input') or {}).get('filePath')}"
    if name == "chrome-devtools__navigate_page":
        return f"navigate_page url={(obj.get('input') or {}).get('url', '?')[:80]}"
    if name == "chrome-devtools__click":
        return f"click uid={(obj.get('input') or {}).get('uid')}"
    if name == "chrome-devtools__fill":
        i = obj.get("input") or {}
        return f"fill uid={i.get('uid')} value={str(i.get('value'))[:60]!r}"
    if name == "chrome-devtools__evaluate_script":
        return f"evaluate_script: {((obj.get('input') or {}).get('function') or '')[:100]}"
    if name == "chrome-devtools__take_snapshot":
        return "take_snapshot"
    if name == "chrome-devtools__list_pages":
        return "list_pages"
    if name == "chrome-devtools__select_page":
        return f"select_page pageId={(obj.get('input') or {}).get('pageId')}"
    return f"{name} input={json.dumps((obj.get('input') or {}), ensure_ascii=False)[:MAX_INPUT_CHARS]}"


def _summarize_tool_result(name: str, obj: dict) -> str:
    is_error = bool(obj.get("is_error"))
    out = (obj.get("output") or "")
    if name == "report_progress" or name == "report_module_status":
        return f"  → {out[:120]}"
    if name == "bash":
        return f"  → {out[:200].replace(chr(10), ' ')}"
    if name == "excelio__update_cells":
        return f"  → {out[:160]}"
    if name == "chrome-devtools__take_snapshot":
        return f"  → snapshot ({len(out)} chars)"
    if name == "chrome-devtools__evaluate_script":
        return f"  → result ({len(out)} chars) {'[ERROR]' if is_error else ''}"
    return f"  → {out[:120].replace(chr(10), ' ')}"


def main() -> int:
    p = argparse.ArgumentParser(description="Filter runner NDJSON log to key events")
    p.add_argument("run_id", help="Run id (matches ~/.trendpower/runs/<run_id>.ndjson.log)")
    p.add_argument("--json", action="store_true", help="Emit JSON Lines instead of human text")
    p.add_argument("--tail", type=int, default=0, help="Only show last N events (0 = all)")
    args = p.parse_args()

    log_path = LOG_DIR / f"{args.run_id}.ndjson.log"
    if not log_path.exists():
        print(f"log not found: {log_path}", file=sys.stderr)
        return 1

    events: list[tuple[float, str]] = []  # (ts, formatted_line)
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue

        t = o.get("type")
        if t not in KEEP_TYPES:
            continue
        if t == "status":
            phase = o.get("phase", "")
            if phase not in KEEP_STATUS_PHASES:
                continue

        ts = o.get("ts")

        if args.json:
            events.append((ts or 0, json.dumps({"ts": ts, **o}, ensure_ascii=False)))
            continue

        if t == "session_start":
            line = f"[{_ts_short(ts)}] ▶ session start run_id={o.get('run_id')} skill={o.get('skill')} model={o.get('model')}"
        elif t == "session_end":
            line = f"[{_ts_short(ts)}] ■ session end ok={o.get('ok')} duration={o.get('duration_ms', 0) // 1000}s"
        elif t == "status":
            line = f"[{_ts_short(ts)}] ● status.{(o.get('phase') or '')}: {(o.get('detail') or '')[:200]}"
        elif t == "progress":
            line = (f"[{_ts_short(ts)}] ▸ progress done={o.get('done')}/{o.get('total')} "
                    f"failed={o.get('failed')} module={o.get('module')!r}")
        elif t == "module_status":
            line = f"[{_ts_short(ts)}] ◇ module {o.get('module')!r} → {o.get('state')!r}"
        elif t == "assistant_final":
            text = (o.get("text") or "")[:600]
            line = f"[{_ts_short(ts)}] ★ assistant_final:\n{text}"
        elif t == "error":
            line = f"[{_ts_short(ts)}] ✗ error: {o.get('message')} | trace={(o.get('trace') or '')[:200]}"
        else:
            continue
        events.append((ts or 0, line))

    # also show tool_call + tool_result as a paired block (call + result)
    # by reading the log again in order and emitting them inline. To keep the
    # file simple, we only emit tool_call's first 1-line summary, and pair
    # tool_result right after.
    # Re-scan and inject tool_call / tool_result near their position.
    out: list[tuple[float, str]] = []
    last_call: dict | None = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue

        t = o.get("type")
        ts = o.get("ts")

        if t == "tool_call":
            name = o.get("name", "")
            if name in ("report_progress", "report_module_status") or name.startswith("bash"):
                last_call = {"name": name, "obj": o, "ts": ts}
                continue  # these are kept as their own progress/module_status
            summary = _summarize_tool(name, o)
            last_call = {"name": name, "obj": o, "ts": ts, "summary": summary}
            out.append((ts, f"[{_ts_short(ts)}] → {summary}"))
        elif t == "tool_result":
            if last_call and last_call.get("name") == o.get("name") and last_call.get("obj", {}).get("id") == o.get("tool_call_id"):
                res_summary = _summarize_tool_result(o.get("name", ""), o)
                out.append((o.get("ts") or 0, f"[{_ts_short(o.get('ts'))}] {res_summary}"))
                last_call = None
        elif t in KEEP_TYPES:
            if t == "status":
                if (o.get("phase") or "") not in KEEP_STATUS_PHASES:
                    continue
            # Re-derive the formatted line for keep types (above code didn't store it).
            # Easier: re-emit as we did above. Refactor: re-run formatting.
            out.append((ts, _format(o)))

    # Sort by ts (out is already in file order so this is a no-op safety).
    out.sort(key=lambda x: x[0])
    if args.tail:
        out = out[-args.tail:]

    for _, line in out:
        print(line, flush=True)
    return 0


def _format(o: dict) -> str:
    t = o.get("type")
    ts = o.get("ts")
    if t == "session_start":
        return f"[{_ts_short(ts)}] ▶ session start run_id={o.get('run_id')} skill={o.get('skill')} model={o.get('model')}"
    if t == "session_end":
        return f"[{_ts_short(ts)}] ■ session end ok={o.get('ok')} duration={o.get('duration_ms', 0) // 1000}s"
    if t == "status":
        return f"[{_ts_short(ts)}] ● status.{(o.get('phase') or '')}: {(o.get('detail') or '')[:200]}"
    if t == "progress":
        return (f"[{_ts_short(ts)}] ▸ progress done={o.get('done')}/{o.get('total')} "
                f"failed={o.get('failed')} module={o.get('module')!r}")
    if t == "module_status":
        return f"[{_ts_short(ts)}] ◇ module {o.get('module')!r} → {o.get('state')!r}"
    if t == "assistant_final":
        return f"[{_ts_short(ts)}] ★ assistant_final:\n{(o.get('text') or '')[:600]}"
    if t == "error":
        return f"[{_ts_short(ts)}] ✗ error: {o.get('message')} | trace={(o.get('trace') or '')[:200]}"
    return f"[{_ts_short(ts)}] {t}: {o}"


if __name__ == "__main__":
    sys.exit(main())
