"""qumall-runner — long-running 24/7 orchestrator.

This is a SMALL Python program that runs forever, claiming and executing
test cases from qumall.db. It does NOT go through trendpower's agent
loop, so it has no 540s/600s per-session limit. The Windows Task
Scheduler launches it at boot; the user kills it when they want to
stop the run.

Why a separate orchestrator:
  - trendpower's agent loop is wrapped in NDJSON streaming that the
    Claude Code harness drives; the harness has a hard 600s timeout.
  - chrome-devtools-mcp is a stdio JSON-RPC server that locks its
    profile to one process.
  - For 3000+ cases over many hours, we want direct control: claim
    one case at a time, run it, write back, repeat. Each case takes
    30-60 seconds; the loop runs forever (until SIGTERM).

Architecture per case:
  1. claim_next(WORKER_ID) → case row from qumall.db
  2. cdp_client.list_pages + select_page to ensure the right page
  3. Dispatch to a template (form / state / list / upload) OR fall
     through to mimo_client for free-form execution
  4. Compare actual to case.expected → 通过 / 失败 / 跳过
  5. set(WORKER_ID, status, note) → write to DB
  6. If crashed mid-case: release(WORKER_ID) so another worker can pick
     it up (or sweep-expired reclaims it after 30min)

Usage:
  python qumall-runner.py --db C:\\qumall-pool\\qumall-pilot.db \\
      --worker-id A --mirror C:\\qumall-pool\\qumall-pilot.xlsx \\
      --debug-port 9222

Env:
  TRENDPOWER_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
  OPENAI_API_KEY=tp-...
  QUMALL_USERNAME / QUMALL_PASSWORD (only if you don't pre-login the
    Edge profile; the orchestrator never auto-logs-in — captcha kills it)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Local imports (works when run from qumall-runner/ as cwd).
from cdp_client import connect as cdp_connect
from mimo_client import chat as mimo_chat
import templates


# ─── timing / formatting helpers ─────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_plus(minutes: int) -> str:
    return (datetime.now(timezone.utc).timestamp() + minutes * 60)


def fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


# ─── claim / release / set ──────────────────────────────────────────────

def claim_next(db: str, worker: str, lease_minutes: int) -> Optional[dict]:
    """Atomically claim the next pending case. Returns the case dict
    (with all columns) or None if the queue is empty."""
    claimed_at = now_iso()
    lease_until_dt = datetime.now(timezone.utc).timestamp() + lease_minutes * 60
    lease_until_iso = datetime.fromtimestamp(lease_until_dt, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with sqlite3.connect(db, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        # First: free any expired leases (crashed workers' cases).
        conn.execute(
            "UPDATE cases SET worker = NULL, claimed_at = NULL, lease_until = NULL "
            "WHERE worker IS NOT NULL AND lease_until IS NOT NULL AND lease_until < ?",
            (claimed_at,),
        )
        # Now: atomic claim.
        try:
            conn.execute(
                """
                UPDATE cases
                SET worker = ?, claimed_at = ?, lease_until = ?
                WHERE id = (
                    SELECT id FROM cases
                    WHERE (status IS NULL OR status = '')
                      AND (worker IS NULL OR worker = ''
                           OR lease_until IS NULL OR lease_until < ?)
                    ORDER BY sheet_row ASC
                    LIMIT 1
                )
                """,
                (worker, claimed_at, lease_until_iso, claimed_at),
            )
            conn.commit()
        except sqlite3.OperationalError as e:
            # Database is locked (another writer). Brief back-off and try again.
            print(f"[claim] db locked: {e}", file=sys.stderr)
            return None
        row = conn.execute(
            "SELECT * FROM cases WHERE worker = ? AND claimed_at = ?",
            (worker, claimed_at),
        ).fetchone()
    return dict(row) if row else None


def release(db: str, worker: str, case_id: str) -> None:
    """Clear our claim so another worker (or sweep) can re-take this case."""
    with sqlite3.connect(db, timeout=10) as conn:
        conn.execute(
            "UPDATE cases SET worker = NULL, claimed_at = NULL, lease_until = NULL "
            "WHERE id = ? AND worker = ?",
            (case_id, worker),
        )
        conn.commit()


def set_status(db: str, worker: str, case_id: str, status: str, note: str) -> None:
    """Write the result and free the claim in one shot."""
    with sqlite3.connect(db, timeout=10) as conn:
        # Worker ownership check (refuse if another worker now holds it).
        row = conn.execute(
            "SELECT worker, lease_until FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if row is None:
            print(f"[set] {case_id}: case gone (deleted?) — skipping write", file=sys.stderr)
            return
        owner = row[0]
        lease = row[1]
        if owner and owner != worker and lease and lease > now_iso():
            print(f"[set] {case_id}: refused — owned by {owner!r} until {lease}", file=sys.stderr)
            return
        conn.execute(
            "UPDATE cases SET status = ?, note = ?, updated_at = ?, "
            "worker = NULL, claimed_at = NULL, lease_until = NULL WHERE id = ?",
            (status, note[:200], now_iso(), case_id),
        )
        conn.commit()


# ─── case execution ─────────────────────────────────────────────────────

def execute_case(case: dict, cdp, module) -> tuple[str, str]:
    """Dispatch a case to the right template. Returns (status, note)."""
    title = case.get("title", "") or ""
    steps = case.get("steps", "") or ""
    expected = case.get("expected", "") or ""

    # 1) file-upload template (uses CDP DOM.setFileInputFiles)
    if "上传" in steps or "upload" in steps.lower():
        try:
            return templates.run_upload(case, cdp, module)
        except Exception as e:
            return "失败", f"upload_template error: {e!s:.120}"

    # 2) form-validation template (input + submit)
    if "输入" in steps and ("提交" in steps or "保存" in steps):
        try:
            return templates.run_form(case, cdp, module)
        except Exception as e:
            return "失败", f"form_template error: {e!s:.120}"

    # 3) state-check template (just verify expected text is in DOM)
    if "显示" in expected or "展示" in expected or "正常" in expected:
        try:
            return templates.run_state_check(case, cdp, module)
        except Exception as e:
            return "失败", f"state_template error: {e!s:.120}"

    # 4) fallback: mimo decides the action sequence
    try:
        return templates.run_via_mimo(case, cdp, module, mimo_chat)
    except Exception as e:
        return "失败", f"mimo_fallback error: {e!s:.120}"


# ─── main loop ──────────────────────────────────────────────────────────

class Stop:
    def __init__(self) -> None:
        self.flag = False
    def set(self, *_: Any) -> None:
        self.flag = True
        print("\n[runner] SIGTERM/SIGINT received, finishing current case then exiting...", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="qumall-runner 24/7 case executor")
    ap.add_argument("--db", required=True, help="Path to qumall.db (e.g. C:\\qumall-pool\\qumall-pilot.db)")
    ap.add_argument("--worker-id", required=True, help="Unique worker id (e.g. A, B)")
    ap.add_argument("--mirror", default=None, help="Optional mirror xlsx to write col 14/15 to")
    ap.add_argument("--debug-port", type=int, default=9222, help="Edge --remote-debugging-port")
    ap.add_argument("--lease-minutes", type=int, default=30, help="Claim lease duration")
    ap.add_argument("--sweep-every-min", type=int, default=10, help="How often to free expired leases")
    ap.add_argument("--max-cases", type=int, default=0, help="Stop after N cases (0 = forever)")
    ap.add_argument("--empty-sleep-s", type=int, default=60, help="Sleep when queue is empty")
    ap.add_argument("--log-file", default=None, help="Append run log to this file")
    ap.add_argument(
        "--edge-exe",
        default=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        help="Path to Edge executable. The runner launches its own Edge with --remote-debugging-port so it owns the profile lock.",
    )
    ap.add_argument(
        "--edge-profile",
        default=str(Path.home() / ".trendpower" / "qumall-profile"),
        help="Edge user-data-dir (separate profile per machine for multi-worker safety).",
    )
    args = ap.parse_args()

    log_path = Path(args.log_file) if args.log_file else (
        Path.home() / ".trendpower" / "runs" / f"qumall-runner-{args.worker_id}.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        line = f"[{fmt_ts(time.time())}] {msg}"
        print(line, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    log(f"=== qumall-runner start worker={args.worker_id} db={args.db} ===")
    log(f"  lease_minutes={args.lease_minutes} max_cases={args.max_cases or '∞'}")

    stop = Stop()
    signal.signal(signal.SIGINT, stop.set)
    signal.signal(signal.SIGTERM, stop.set)

    # Connect CDP — qumall-runner launches its OWN Edge instance so it owns
    # the profile lock and can be multi-worker safe (one Edge per worker).
    cdp = cdp_connect(
        debug_port=args.debug_port,
        executable=args.edge_exe,
        user_data_dir=args.edge_profile,
    )
    log(f"  CDP connected, debug_port={args.debug_port} edge={args.edge_exe}")

    # Best-effort navigate to home so the first case isn't racing the
    # login page. This works because the Edge profile is pre-logged-in.
    try:
        # Pick a real page (not about:blank, not the MSN new-tab page, not
        # a service worker). Open a fresh tab if needed.
        for attempt in range(5):
            pages = cdp.list_pages()
            real = [p for p in pages
                    if p.get("type") == "page"
                    and not p.get("url", "").startswith(("about:", "edge:", "chrome:", "https://ntp.msn"))]
            if real:
                cdp.select_page(real[0]["pageId"])
                break
            cdp.evaluate_script("window.open('about:blank', '_blank')")
            time.sleep(1)
        else:
            log("  WARN: no usable page target — opening one")
            cdp.evaluate_script("window.open('https://admin.qumall.qushiyun.com/', '_blank')")
            time.sleep(1)
        # Force navigate to qumall home and wait for the SPA to load.
        cdp.evaluate_script("window.location.href = 'https://admin.qumall.qushiyun.com/'")
        loaded = False
        for _ in range(30):
            ok1 = cdp.wait_for_text("huitong", timeout_ms=1500)
            ok2 = cdp.wait_for_text("首页", timeout_ms=500)
            if ok1 and ok2:
                loaded = True
                break
            # Force reload if not loaded
            try:
                cdp.evaluate_script("window.location.reload()")
            except Exception:
                pass
            time.sleep(1)
        log(f"  initial navigate: loaded={loaded}")
        if not loaded:
            shot = str(Path.home() / ".trendpower" / "logs" / "qumall-runner-init.png")
            try:
                cdp.take_screenshot(shot)
                log(f"  init screenshot saved: {shot}")
            except Exception as e:
                log(f"  init screenshot failed: {e!s:.80}")
            info = cdp.evaluate_script(
                "({url: location.href, title: document.title, "
                "has_huitong: document.body && document.body.innerText.includes('huitong'), "
                "body_start: document.body ? document.body.innerText.slice(0, 300) : ''})"
            )
            log(f"  page state: {info}")
    except Exception as e:
        log(f"  initial navigate failed (will continue anyway): {e}")

    cases_done = 0
    last_sweep = 0.0
    pass_count = fail_count = skip_count = 0
    t_start = time.time()

    while not stop.flag:
        # Periodic sweep — frees any cases that other workers' leases have
        # expired (handles inter-worker cleanup without waiting for those
        # workers to call claim_next).
        if time.time() - last_sweep > args.sweep_every_min * 60:
            with sqlite3.connect(args.db, timeout=10) as conn:
                cur = conn.execute(
                    "UPDATE cases SET worker = NULL, claimed_at = NULL, lease_until = NULL "
                    "WHERE worker IS NOT NULL AND lease_until IS NOT NULL AND lease_until < ?",
                    (now_iso(),),
                )
                conn.commit()
                if cur.rowcount:
                    log(f"  swept {cur.rowcount} expired claim(s)")
            last_sweep = time.time()

        case = claim_next(args.db, args.worker_id, args.lease_minutes)
        if case is None:
            log(f"  queue empty, sleeping {args.empty_sleep_s}s...")
            for _ in range(args.empty_sleep_s):
                if stop.flag:
                    break
                time.sleep(1)
            continue

        case_id = case["id"]
        sheet_row = case["sheet_row"]
        module = case.get("module", "")
        title = (case.get("title") or "")[:60]
        log(f"  ► claim case id={case_id} row={sheet_row} module={module} title={title!r}")

        t0 = time.time()
        try:
            status, note = execute_case(case, cdp, module)
        except Exception as e:
            log(f"  ✗ execute_case crashed: {e!r}")
            traceback.print_exc()
            status, note = "失败", f"crashed: {type(e).__name__}: {str(e)[:100]}"
            # Free the claim so this row can be retried by us or another worker.
            release(args.db, args.worker_id, case_id)
        elapsed = time.time() - t0
        log(f"  ← status={status} elapsed={elapsed:.1f}s note={note[:80]!r}")

        set_status(args.db, args.worker_id, case_id, status, note)
        if args.mirror:
            try:
                from mirror_writer import write_mirror_cell
                write_mirror_cell(args.mirror, sheet_row, status, note)
            except Exception as e:
                log(f"  ⚠ mirror write failed: {e!s:.80}")

        if status == "通过":
            pass_count += 1
        elif status == "失败":
            fail_count += 1
        else:
            skip_count += 1
        cases_done += 1

        if args.max_cases and cases_done >= args.max_cases:
            log(f"  max-cases {args.max_cases} reached, exiting")
            break

    elapsed = time.time() - t_start
    log(f"=== qumall-runner stop worker={args.worker_id} cases={cases_done} pass={pass_count} fail={fail_count} skip={skip_count} elapsed={elapsed:.0f}s ===")
    cdp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
