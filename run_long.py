#!/usr/bin/env python3
"""Spawn trendpower runner.py as a fully detached background process.

The Claude Code harness Bash tool has a hard 600s timeout on synchronous
calls. Long-running tests (Mode B replay of 100+ cases) need to outlive
the parent shell. This launcher:

1. Forks runner.py via subprocess.Popen with DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP
   on Windows (setsid on Linux) so the child has no controlling terminal
2. Redirects all stdio to a log file the user can tail
3. Returns IMMEDIATELY with the child PID + log path + checkpoint path
4. The harness sees a sub-second exit code; the runner keeps running for hours

Usage:
  uv run --project trendpower-py python run_long.py       --prompt "..." --cwd "D:/workspace/..."       --run-id qumall-replay-3hr       [--resume <id>] [--skill <name>]       [--mcp-config ~/.trendpower/mcp_servers.json]       [--provider anthropic --model MiniMax-M2.7 --base-url ...]       [--log-dir ~/.trendpower/runs]

Environment variables (TRENDPOWER_PROVIDER, _MODEL, _BASE_URL, _API_KEY,
QUMALL_USERNAME, QUMALL_PASSWORD) are inherited from the parent shell.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detached trendpower runner launcher")
    p.add_argument("--prompt", required=True)
    p.add_argument("--cwd", default=os.getcwd())
    p.add_argument("--run-id", default=None,
                   help="Stable run id shared across all workers in the same pool. "
                        "Each worker's log file is named {run_id}-{worker}.ndjson.log.")
    p.add_argument("--resume", default=None)
    p.add_argument("--skill", default=None)
    p.add_argument(
        "--worker-id", required=True,
        help="Unique worker id (e.g. A, B, machine-01). Used by qumall-db "
             "claim-next to atomically reserve cases so 2+ workers don't pick "
             "the same case. Each worker gets its own log/checkpoint paths.",
    )
    p.add_argument(
        "--mcp-config",
        default=str(Path.home() / ".trendpower" / "mcp_servers.json"),
    )
    p.add_argument("--provider", default=os.environ.get("TRENDPOWER_PROVIDER", "openai"))
    p.add_argument("--model", default=os.environ.get("TRENDPOWER_MODEL", "gpt-4o-mini"))
    p.add_argument("--base-url", default=os.environ.get("TRENDPOWER_BASE_URL"))
    p.add_argument("--log-dir", default=str(Path.home() / ".trendpower" / "runs"))
    p.add_argument(
        "--runner-py",
        default=str(
            Path(__file__).resolve().parent
            / "bdd_ai_toolkit"
            / "resources"
            / "trendpower-headless"
            / "runner.py"
        ),
        help="Path to runner.py (auto-detected relative to this script).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    run_id = args.run_id or args.resume or uuid.uuid4().hex[:12]
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    # Per-worker log/checkpoint file so N workers on the same run-id don't
    # clobber each other. E.g. run qumall-150 / A / B each get their own log.
    log_path = log_dir / f"{run_id}-{args.worker_id}.ndjson.log"

    runner_py = Path(args.runner_py)
    if not runner_py.exists():
        print(f"ERROR: runner.py not found at {runner_py}", file=sys.stderr)
        return 1

    # The wrapper that spawns runner.py. On Windows we use a small .cmd to
    # inherit the Python interpreter and forward env cleanly.
    # The trendpower import path is required so the spawned process can do
    # `import trendpower.foundation` etc. The parent run_long.py is invoked
    # from inside trendpower-py/ as cwd, but to be safe we pass it explicitly.
    trendpower_py = Path(args.runner_py).resolve()
    # Walk up from bdd_ai_toolkit/resources/trendpower-headless/runner.py
    # to the workspace root, then into trendpower/trendpower-py.
    workspace_root = None
    for parent in trendpower_py.parents:
        if (parent / "trendpower" / "trendpower-py" / "pyproject.toml").exists():
            workspace_root = parent
            break
    if workspace_root is None:
        print("ERROR: could not locate trendpower-py/ relative to runner.py", file=sys.stderr)
        return 1
    trendpower_py_dir = workspace_root / "trendpower" / "trendpower-py"

    # Build the inner command (uv run with --project trendpower-py).
    # --run-id is suffixed with the worker id so each worker's runner.py
    # writes its own ~/.trendpower/checkpoints/<run-id>-<worker>.json.
    inner = [
        "uv",
        "run",
        "--project",
        str(trendpower_py_dir),
        "python",
        "-u",
        str(runner_py),
        "--prompt",
        args.prompt,
        "--cwd",
        args.cwd,
        "--mcp-config",
        args.mcp_config,
        "--provider",
        args.provider,
        "--model",
        args.model,
        "--run-id",
        f"{run_id}-{args.worker_id}",
    ]
    if args.resume:
        inner += ["--resume", f"{args.resume}-{args.worker_id}"]
    if args.skill:
        inner += ["--skill", args.skill]
    if args.base_url:
        inner += ["--base-url", args.base_url]

    # Open log file
    log_fh = open(log_path, "w", encoding="utf-8", buffering=1)  # line-buffered

    # Spawn detached.
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "cwd": args.cwd,
        "env": os.environ.copy(),
        "close_fds": True,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS (0x00000008) | CREATE_NEW_PROCESS_GROUP (0x00000200)
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        # POSIX: preexec_fn = os.setsid
        kwargs["preexec_fn"] = os.setsid

    try:
        proc = subprocess.Popen(inner, **kwargs)
    except Exception as e:
        print(f"ERROR: failed to spawn runner: {e}", file=sys.stderr)
        log_fh.close()
        return 1

    # Don't close log_fh in parent — the child holds the write end via
    # inheritance. Closing would cause the child to see a broken pipe.
    # On Windows, handles are duplicated; closing in parent does NOT close
    # them in child. We deliberately keep log_fh open until the script exits.

    print(f"=== trendpower runner detached ===")
    print(f"run_id:      {run_id}")
    print(f"worker:      {args.worker_id}")
    print(f"pid:         {proc.pid}")
    print(f"log:         {log_path}")
    print(f"checkpoint:  {Path.home() / '.trendpower' / 'checkpoints' / f'{run_id}-{args.worker_id}.json'}")
    print(f"")
    print(f"Multi-worker tip: this run_id can be shared by N workers on N machines.")
    print(f"All workers see the same qumall.db (e.g. on SMB); claim-next")
    print(f"guarantees they pick different cases.")
    print(f"")
    print(f"Monitor with:")
    print(f'  tail -f "{log_path}"            # on macOS / Linux')
    print(f'  Get-Content -Wait "{log_path}"  # on PowerShell')
    print(f"")
    print(f"Filter key events:")
    print(f'  PYTHONIOENCODING=utf-8 python qumall-db/filter_log.py {run_id}-{args.worker_id} --tail 30')
    print(f"")
    print(f"Stop with:")
    print(f"  taskkill /F /PID {proc.pid}     # on Windows")
    print(f"  kill {proc.pid}                  # on macOS / Linux")
    return 0


if __name__ == "__main__":
    sys.exit(main())
