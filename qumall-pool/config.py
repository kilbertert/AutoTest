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
"""
from __future__ import annotations

import os

# SMB share. In Python source r"\\192.168.2.77\qumall-pool" is the literal
# string \\192.168.2.77\qumall-pool (Windows UNC path).
# SMB share. Note: a single backslash prefix works on Windows via SMB
# redirection; the standard double-backslash UNC form has shown
# intermittent WinError 3 failures from this Python process.
POOL_ROOT = r"\192.168.2.77\qumall-pool"

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
    raise RuntimeError(
        "OPENAI_API_KEY env var is required. Set it before running the worker:\n"
        "  set OPENAI_API_KEY=<your-mimo-api-key>"
    )

# Per-job limits.
MAX_CASES_PER_JOB = 75
CASE_TIMEOUT_SEC   = 540