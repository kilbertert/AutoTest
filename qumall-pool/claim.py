#!/usr/bin/env python3
"""Atomically claim the next pending job for a worker.

Algorithm: scan jobs/pending/ for *.json, try os.rename the first one into
jobs/claimed/<worker_id>/. Rename on NTFS (the SMB share's filesystem) is
atomic — only one worker can succeed; others will get FileNotFoundError and
move on to the next candidate.

Returns the claimed job payload (dict) or None if no pending jobs.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


def get_worker_id() -> str:
    """Stable per-machine ID. Prefer hostname + a short random suffix to
    distinguish two workers on the same machine."""
    return f"{socket.gethostname()}_{uuid.uuid4().hex[:6]}"


def claim(pending_dir: str, claimed_root: str, worker_id: str) -> dict | None:
    pending = Path(pending_dir)
    if not pending.exists():
        return None
    claimed_root = Path(claimed_root)
    claimed_worker = claimed_root / worker_id
    claimed_worker.mkdir(parents=True, exist_ok=True)

    candidates = sorted(pending.glob("*.json"))
    for job_path in candidates:
        dst = claimed_worker / job_path.name
        try:
            os.rename(str(job_path), str(dst))
        except (FileNotFoundError, PermissionError, OSError):
            # Lost the race to another worker; try next candidate.
            continue
        # We claimed it. Read the payload.
        return json.loads(dst.read_text(encoding="utf-8"))
    return None


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Atomically claim the next pending job")
    p.add_argument("--worker-id", default=get_worker_id())
    p.add_argument("--pending", default=config.PENDING_JOBS)
    p.add_argument("--claimed", default=config.CLAIMED_JOBS)
    args = p.parse_args()
    job = claim(args.pending, args.claimed, args.worker_id)
    if job is None:
        print(json.dumps({"ok": True, "claimed": None}))
    else:
        print(json.dumps({"ok": True, "claimed": job, "worker_id": args.worker_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
