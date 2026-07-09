"""qumall-pool — multi-machine coordinator for the 3590 qumall test cases.

All sensitive values (API keys, passwords) are read from environment
variables. Defaults below are PLACEHOLDERS — never put real secrets in
this file. Set the env vars on each machine before starting a worker:

  set TRENDPOWER_PROVIDER=openai
  set TRENDPOWER_MODEL=mimo-v2.5-pro
  set TRENDPOWER_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
  set OPENAI_API_KEY=<your-mimo-api-key>
  set QUMALL_USERNAME=huitong
  set QUMALL_PASSWORD=<your-password>

You can also drop a `.env` file in the repo root — every qumall-pool
script auto-loads it (setdefault, so explicit env vars still win).
"""
from __future__ import annotations

import os
from pathlib import Path

# Load .env from the repo root if it exists — lets any qumall-pool script
# (worker, claim, status, split_jobs) run without exporting env vars in
# their shell. Stdlib only; format is `KEY=VALUE` per line, `#` comments.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"
_lines = _ENV_FILE.read_text(encoding="utf-8").splitlines() if _ENV_FILE.exists() else []
for _line in _lines:
    _line = _line.strip()
    if not _line or _line.startswith("#"):
        continue
    if "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())
for _name in ("_line", "_k", "_v", "_lines", "_REPO_ROOT", "_ENV_FILE"):
    if _name in locals():
        del locals()[_name]  # type: ignore[index]
del _name

# SMB share. Standard UNC: \\server\share. Verified working on both
# the share host (192.168.2.77 itself) and on remote clients.
# (Earlier single-backslash form r"\server\share" is NOT a UNC path —
# Windows treats it as a path relative to the current drive root,
# which silently returns "no such file" instead of erroring out.)
POOL_ROOT = r"\\192.168.2.77\qumall-pool"

# Sub-directory names.
DB_DIR     = "db"
MIRROR_DIR = "mirror"
JOBS_DIR   = "jobs"
LOGS_DIR   = "logs"
STATUS_DIR = "status"
PENDING    = "pending"
CLAIMED    = "claimed"
DONE       = "done"
FAILED     = "failed"

# os.path.join is reliable across raw-string handling.
DB_PATH         = os.path.join(POOL_ROOT, DB_DIR,     "qumall.db")
MIRROR_PATH     = os.path.join(POOL_ROOT, MIRROR_DIR, "qumall-full-replay.xlsx")
QUEUE_PATH      = os.path.join(POOL_ROOT, MIRROR_DIR, "qumall-full-queue.json")
PENDING_JOBS    = os.path.join(POOL_ROOT, JOBS_DIR,   PENDING)
CLAIMED_JOBS    = os.path.join(POOL_ROOT, JOBS_DIR,   CLAIMED)
DONE_JOBS       = os.path.join(POOL_ROOT, JOBS_DIR,   DONE)
FAILED_JOBS     = os.path.join(POOL_ROOT, JOBS_DIR,   FAILED)
LOGS_DIR_FMT    = os.path.join(POOL_ROOT, LOGS_DIR)
STATUS_DIR_FMT  = os.path.join(POOL_ROOT, STATUS_DIR)

# Local Edge profile (each machine should have qumall logged in here).
EDGE_USER_DATA_DIR = r"C:\Users\admin\.trendpower\qumall-profile"

# The actual qumall admin URL. The worker prompt passes this verbatim to
# the agent so it does NOT confuse chrome-devtools-mcp's startup tab
# (http://localhost:30081/) with the qumall site. Override per
# environment via QUMALL_TARGET_URL env var.
QUMALL_TARGET_URL = os.environ.get("QUMALL_TARGET_URL", "https://admin.qumall.qushiyun.com/")

# qumall login (used if the local Edge isn't logged in).
# These ARE in the file as placeholder defaults — they match the QA's test
# credential, not a personal account. Override via env var if your environment
# uses different credentials.
QUMALL_USERNAME = os.environ.get("QUMALL_USERNAME", "huitong")
QUMALL_PASSWORD = os.environ.get("QUMALL_PASSWORD", "")

# mimo (OpenAI compatible). API key MUST be supplied via env var.
MODEL_PROVIDER = os.environ.get("TRENDPOWER_PROVIDER", "openai")
MODEL_NAME     = os.environ.get("TRENDPOWER_MODEL", "mimo-v2.5-pro")
MODEL_BASE_URL = os.environ.get("TRENDPOWER_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MODEL_API_KEY  = os.environ.get("OPENAI_API_KEY", "")

if not MODEL_API_KEY:
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    _env_status = "exists" if _env_path.exists() else "MISSING"
    raise RuntimeError(
        f"OPENAI_API_KEY env var is required. .env at {_env_path}: {_env_status}.\n"
        f"\n"
        f"  Option 1 — create {_env_path} (recommended, auto-loaded):\n"
        f'     @"',
        f"     OPENAI_API_KEY=<your-mimo-api-key>",
        f"     TRENDPOWER_PROVIDER=openai",
        f"     TRENDPOWER_MODEL=mimo-v2.5-pro",
        f"     TRENDPOWER_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1",
        f"     QUMALL_USERNAME=huitong",
        f"     QUMALL_PASSWORD=<your-password>",
        f'     "@ | Out-File -FilePath "{_env_path}" -Encoding utf8',
        f"\n",
        f"  Option 2 — set inline each time:",
        f'     $env:OPENAI_API_KEY="<your-mimo-api-key>"',
        f'     python qumall-pool\\worker.py --worker-id "host_X"',
    )

# Per-job limits.
MAX_CASES_PER_JOB = 75
CASE_TIMEOUT_SEC   = 540