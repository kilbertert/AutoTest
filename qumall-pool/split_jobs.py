#!/usr/bin/env python3
"""Split the 3590-case queue into per-module job files in jobs/pending/.

Each job file is a small JSON with the sheet_row range to run:

  {
    "job_id": "module_基础功能",
    "module": "基础功能",
    "first_row": 2,
    "last_row": 76,
    "total": 75,
    "created_at": "2026-07-07T20:00:00Z"
  }

Workers atomically rename jobs/pending/<job_id>.json → jobs/claimed/<worker_id>/
to claim it. If the rename fails (already taken), they move on to the next
pending job. This is git-style lock-free coordination.

Re-running this script is idempotent: existing pending jobs are NOT
overwritten (we only create if not exists). To re-split (e.g. after
re-importing the queue), wipe jobs/pending/ first.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

# Allow running this script directly without `python -m`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def split(queue_path: str, pending_dir: str, force: bool = False) -> dict:
    queue = json.loads(Path(queue_path).read_text(encoding="utf-8"))
    cases = queue.get("cases") or []
    pending = Path(pending_dir)
    pending.mkdir(parents=True, exist_ok=True)

    if force:
        for p in pending.glob("*.json"):
            p.unlink()

    # Group sheet_rows by module.
    by_module: dict[str, list[int]] = {}
    for c in cases:
        mod = c.get("module") or "未知模块"
        by_module.setdefault(mod, []).append(int(c["row"]))

    created = 0
    skipped = 0
    manifest = []
    for mod, rows in by_module.items():
        rows.sort()
        first, last = rows[0], rows[-1]
        # Safe filename: keep it short; modules are usually clean but
        # some have / like "商家入驻/合作商家".
        safe = mod.replace("/", "_").replace("\\", "_")[:50]
        job_id = f"module_{first:04d}_{last:04d}_{safe}"
        job_path = pending / f"{job_id}.json"
        if job_path.exists():
            skipped += 1
            manifest.append({"job_id": job_id, "module": mod, "rows": [first, last], "status": "exists"})
            continue
        payload = {
            "job_id": job_id,
            "module": mod,
            "first_row": first,
            "last_row": last,
            "total": len(rows),
            "row_list": rows,  # explicit list for the worker to use
            "created_at": _now_iso(),
        }
        job_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        created += 1
        manifest.append({"job_id": job_id, "module": mod, "rows": [first, last], "status": "created"})

    return {
        "ok": True,
        "queue_total": len(cases),
        "modules": len(by_module),
        "jobs_created": created,
        "jobs_skipped": skipped,
        "pending_dir": str(pending),
        "manifest": manifest,
    }


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Split qumall-full-queue.json into per-module jobs")
    p.add_argument("--queue", default=config.QUEUE_PATH)
    p.add_argument("--pending", default=config.PENDING_JOBS)
    p.add_argument("--force", action="store_true", help="Delete existing pending jobs first")
    args = p.parse_args()
    result = split(args.queue, args.pending, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
