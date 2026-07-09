#!/usr/bin/env python3
"""Worker — one process per machine. Loops: claim → run → write-back → next.

Each worker:
  1. atomically claims one job from jobs/pending → jobs/claimed/<worker_id>/
  2. runs the trendpower headless runner with --resume + --skill qumall-fulltest
     and a prompt that scopes the run to the job's row range
  3. on runner exit, reads qumall-db stats to see how many cases finished
  4. writes a status.json into status/<worker_id>.json (small heartbeat)
  5. moves the job to jobs/done (or jobs/failed) and continues
  6. when no more pending jobs exist, exits cleanly

The runner itself is the same trendpower Agent we built — it drives the
chrome-devtools browser through the qumall backend and writes pass/fail/
skip into the shared qumall.db (via qumall-db cli.py set) + the mirror
xlsx (via excelio__update_cells).

This script does NOT spawn the runner itself; it `uv run`s it as a child
process (so a worker crash doesn't take the whole session down). The
runner writes its full NDJSON log to logs/<worker_id>/<run_id>.ndjson.log
for debugging.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claim
import config


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_status(worker_id: str, payload: dict) -> None:
    p = Path(config.STATUS_DIR_FMT) / f"{worker_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_runner_command(job: dict, run_id: str) -> list[str]:
    """Build the `uv run ... runner.py` command for a given job.

    The prompt tells the agent to limit execution to the job's row range.
    We also pass --resume so the runner reuses this run's checkpoint if
    it crashes mid-job (the next invocation picks up where it left off).
    """
    module = job["module"]
    rows = job.get("row_list") or list(range(job["first_row"], job["last_row"] + 1))
    first, last = rows[0], rows[-1]
    row_csv = ",".join(str(r) for r in rows)

    # IMPORTANT: do NOT put SMB paths directly in the prompt text — the model
    # has been observed to truncate them and fall back to local relative paths,
    # creating a stale local qumall.db instead of writing to the pool. Instead,
    # we set the paths as environment variables and tell the agent to use
    # "$POOL_DB" / "$POOL_QUEUE" verbatim.
    prompt = (
        f"执行 qumall 单一模块任务：模块={module}，"
        f"行号范围 {first}..{last}（共 {len(rows)} 条）。\n"
        f"\n"
        f"【路径 - 用环境变量，绝对不要自己拼】\n"
        f"数据库路径已设到环境变量 POOL_DB，必须用 $POOL_DB。例：\n"
        f"  uv run python qumall-db/import_xlsx.py --db \"$POOL_DB\" --queue \"$POOL_QUEUE\" --reset\n"
        f"  uv run python qumall-db/cli.py stats --db \"$POOL_DB\"\n"
        f"  uv run python qumall-db/cli.py next-pending --db \"$POOL_DB\"\n"
        f"  uv run python qumall-db/cli.py set --db \"$POOL_DB\" --id <sheet_row> --status <S> --note \"...\"\n"
        f"\n"
        f"严禁自己拼路径（如 --db qumall.db 或 --db ./xxx）。"
        f"严禁 ls / find / locate 找 .db 文件后再用本地路径。\n"
        f"\n"
        f"【硬约束】\n"
        f"- 严禁 list_files/glob_search/file_info/find/grep/ls/cat\n"
        f"- 严禁 excelio__read_sheet/read_header/list_sheets；严禁 read_file 读 xlsx/JSON/queue\n"
        f"- 严禁 evaluate_script 多次（≤1次/case）；take_snapshot 多次（≤2次/case）\n"
        f"- 严禁 navigate 到 #/login；如出现登录表单 → 立即标'跳过'进入下一条\n"
        f"- 严禁反复刷新登录页：连续 2 次 reload/back 没有进展 → 标'跳过'进下一条\n"
        f"- 登录账号密码来自 env var QUMALL_USERNAME / QUMALL_PASSWORD（不是 case.test_data）\n"
        f"- 验证码无法自动填 → 立即标'跳过'，不要重试\n"
        f"\n"
        f"【故障恢复】\n"
        f"chrome-devtools 返回 Target closed / Protocol error → 标'跳过'进下一条\n"
        f"一条 case 阻塞超过 3 分钟 → 标'跳过'进下一条\n"
        f"\n"
        f"【流程】\n"
        f"1) uv run python qumall-db/import_xlsx.py --db \"$POOL_DB\" --queue \"$POOL_QUEUE\" --reset\n"
        f"2) uv run python qumall-db/cli.py stats --db \"$POOL_DB\"\n"
        f"3) report_progress(done=0, total={len(rows)}, failed=0) + report_module_status(module={module!r}, state='pending')\n"
        f"4) 循环 next-pending → chrome-devtools → set + update_cells → report_progress\n"
        f"5) cli.py stats → assistant_final 报告\n"
    )
    cwd = r"D:\workspace\project\auto-test\AutoGenesis"
    runner = cwd + r"\bdd_ai_toolkit\resources\trendpower-headless\runner.py"
    trendpower_py = cwd + r"\trendpower\trendpower-py"
    return [
        "uv", "run", "--project", trendpower_py, "python", "-u", runner,
        "--prompt", prompt,
        "--cwd", cwd,
        "--mcp-config", r"C:\Users\admin\.trendpower\mcp_servers.json",
        "--run-id", run_id,
        "--skill", "qumall-fulltest",
    ]


def _run_one_job(job: dict, worker_id: str) -> dict:
    """Run a single job end-to-end. Returns the final job-result dict."""
    run_id = f"{worker_id}_{job['job_id']}_{uuid.uuid4().hex[:6]}"
    log_dir = Path(config.LOGS_DIR_FMT) / worker_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}.ndjson.log"

    cmd = _build_runner_command(job, run_id)
    env = os.environ.copy()
    env.update({
        "TRENDPOWER_PROVIDER": config.MODEL_PROVIDER,
        "TRENDPOWER_MODEL":    config.MODEL_NAME,
        "TRENDPOWER_BASE_URL": config.MODEL_BASE_URL,
        "OPENAI_API_KEY":      config.MODEL_API_KEY,
        "QUMALL_USERNAME":     config.QUMALL_USERNAME,
        "QUMALL_PASSWORD":     config.QUMALL_PASSWORD,
        # Expose the pool paths as env vars so the agent can use $POOL_DB
        # instead of trying to spell out the SMB path in shell commands
        # (which it then truncates or gets wrong).
        "POOL_ROOT":  config.POOL_ROOT,
        "POOL_DB":    config.DB_PATH,
        "POOL_QUEUE": config.QUEUE_PATH,
        "PYTHONIOENCODING":    "utf-8",
        "PYTHONUTF8":          "1",
    })
    # Fix chrome-devtools mcp config userDataDir on the local machine to
    # use the local Edge profile. We rewrite the mcp_servers.json if it
    # points to the local profile path; if it doesn't, leave it.
    # (worker runs on the local machine, the Edge is local.)

    started = time.time()
    job["started_at"] = _now_iso()
    job["run_id"] = run_id

    # Job-level timeout: 30 min hard ceiling. If exceeded, kill the job
    # so other workers can pick up the remaining modules.
    JOB_TIMEOUT_SEC = 1800

    # Open log file; let the runner write NDJSON to it directly.
    with open(log_path, "w", encoding="utf-8", buffering=1) as logf:
        try:
            proc = subprocess.run(
                cmd, env=env, stdout=logf, stderr=subprocess.STDOUT,
                timeout=JOB_TIMEOUT_SEC,
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = -1
            logf.write(f"\n{{\"type\": \"error\", \"message\": \"job-level timeout ({JOB_TIMEOUT_SEC}s) exceeded\"}}\n")

    # Read the runner's session_end from the log to find duration / ok.
    duration_ms = int((time.time() - started) * 1000)
    ok = exit_code == 0
    job["finished_at"] = _now_iso()
    job["duration_ms"] = duration_ms
    job["exit_code"]   = exit_code

    # Pull aggregate stats from the shared db so the job record shows
    # how many cases were touched in this job.
    try:
        import sqlite3
        rows = job.get("row_list") or list(range(job["first_row"], job["last_row"] + 1))
        placeholders = ",".join("?" * len(rows))
        conn = sqlite3.connect(str(config.DB_PATH))
        conn.row_factory = sqlite3.Row
        stats_rows = conn.execute(
            f"SELECT status, COUNT(*) AS n FROM cases WHERE sheet_row IN ({placeholders}) GROUP BY status",
            rows,
        ).fetchall()
        conn.close()
        stats = {r["status"] or "(pending)": r["n"] for r in stats_rows}
    except Exception as e:
        stats = {"error": str(e)}
    job["stats"] = stats
    job["ok"] = ok
    return job


def _finalize_job(job: dict, worker_id: str) -> None:
    """Move the job file from claimed/<worker_id>/ to done/ or failed/."""
    src = Path(config.CLAIMED_JOBS) / worker_id / f"{job['job_id']}.json"
    if job.get("ok"):
        dst_dir = Path(config.DONE_JOBS)
    else:
        dst_dir = Path(config.FAILED_JOBS)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{job['job_id']}.json"
    # Update the on-disk job record with the result.
    src.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.move(str(src), str(dst))


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="qumall-pool worker: claim + run + write-back")
    p.add_argument("--worker-id", default=claim.get_worker_id())
    p.add_argument("--max-jobs", type=int, default=0, help="0 = unlimited")
    p.add_argument("--idle-sleep", type=int, default=30, help="seconds to wait when no pending jobs")
    args = p.parse_args()
    worker_id = args.worker_id
    print(f"[worker {worker_id}] started at {_now_iso()}", flush=True)

    jobs_done = 0
    consecutive_idle = 0
    while True:
        if args.max_jobs and jobs_done >= args.max_jobs:
            print(f"[worker {worker_id}] reached --max-jobs={args.max_jobs}; exiting")
            break
        job = claim.claim(config.PENDING_JOBS, config.CLAIMED_JOBS, worker_id)
        if job is None:
            consecutive_idle += 1
            if consecutive_idle == 1:
                print(f"[worker {worker_id}] no pending jobs; sleeping {args.idle_sleep}s (Ctrl-C to stop)")
            _write_status(worker_id, {
                "worker_id": worker_id, "state": "idle",
                "last_check": _now_iso(), "claimed": None,
            })
            time.sleep(args.idle_sleep)
            # 5 consecutive idles (150s) = assume pool done, exit.
            if consecutive_idle >= 5:
                print(f"[worker {worker_id}] no jobs for {consecutive_idle * args.idle_sleep}s; pool drained, exiting")
                break
            continue
        consecutive_idle = 0
        print(f"[worker {worker_id}] claimed {job['job_id']} ({job['module']}, {job['total']} cases)")
        _write_status(worker_id, {
            "worker_id": worker_id, "state": "running",
            "last_check": _now_iso(),
            "claimed": job["job_id"], "module": job["module"],
        })
        result = _run_one_job(job, worker_id)
        _finalize_job(result, worker_id)
        jobs_done += 1
        print(f"[worker {worker_id}] finished {result['job_id']}: ok={result['ok']} stats={result.get('stats')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
