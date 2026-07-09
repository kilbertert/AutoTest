#!/usr/bin/env python3
"""Aggregate status across the qumall pool.

Reads:
  - jobs/pending/  → how many jobs still unclaimed
  - jobs/claimed/  → how many jobs in progress (and by which worker)
  - jobs/done/     → how many jobs completed (and each one's stats)
  - jobs/failed/   → which jobs failed and why
  - db/qumall.db   → case-level pass/fail/skip counts (read-only)
  - status/        → per-worker latest progress snapshot

Prints a single human-readable summary + machine-readable JSON to stdout.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


def _read_status_files(status_dir: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    p = Path(status_dir)
    if not p.exists():
        return out
    for f in p.glob("*.json"):
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return out


def _scan_jobs(claimed_root: str) -> dict[str, list[str]]:
    """Map worker_id → list of job files currently claimed."""
    out: dict[str, list[str]] = defaultdict(list)
    p = Path(claimed_root)
    if not p.exists():
        return out
    for worker_dir in p.iterdir():
        if not worker_dir.is_dir():
            continue
        for f in worker_dir.glob("*.json"):
            out[worker_dir.name].append(f.stem)
    return out


def _scan_done(done_dir: str) -> list[dict]:
    out = []
    p = Path(done_dir)
    if not p.exists():
        return out
    for f in sorted(p.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def _scan_pending(pending_dir: str) -> list[dict]:
    out = []
    p = Path(pending_dir)
    if not p.exists():
        return out
    for f in sorted(p.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({"job_id": d.get("job_id"), "module": d.get("module"), "total": d.get("total")})
        except Exception:
            pass
    return out


def _scan_failed(failed_dir: str) -> list[dict]:
    out = []
    p = Path(failed_dir)
    if not p.exists():
        return out
    for f in sorted(p.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def main() -> int:
    pending   = _scan_pending(config.PENDING_JOBS)
    claimed   = _scan_jobs(config.CLAIMED_JOBS)
    done      = _scan_done(config.DONE_JOBS)
    failed    = _scan_failed(config.FAILED_JOBS)
    worker_st = _read_status_files(config.STATUS_DIR_FMT)

    # SQLite read-only (open in read-only URI mode so we don't lock).
    db_stats = {"ok": False, "error": "db not found"}
    db_path = Path(config.DB_PATH)
    if db_path.exists():
        try:
            # Read-only URI on Windows requires backslash in URI; skip URI
            # and just open normally — we only do SELECTs.
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) AS n FROM cases").fetchone()["n"]
            by_status = {
                (r["status"] or "(pending)"): r["n"]
                for r in conn.execute("SELECT status, COUNT(*) AS n FROM cases GROUP BY status").fetchall()
            }
            by_module = [
                dict(r) for r in conn.execute(
                    "SELECT module, COUNT(*) AS total, "
                    "SUM(CASE WHEN status='通过' THEN 1 ELSE 0 END) AS passed, "
                    "SUM(CASE WHEN status='失败' THEN 1 ELSE 0 END) AS failed, "
                    "SUM(CASE WHEN status='跳过' THEN 1 ELSE 0 END) AS skipped, "
                    "SUM(CASE WHEN status IS NULL OR status='' THEN 1 ELSE 0 END) AS pending "
                    "FROM cases GROUP BY module ORDER BY module"
                ).fetchall()
            ]
            top_failures = [
                dict(r) for r in conn.execute(
                    "SELECT note, COUNT(*) AS n FROM cases "
                    "WHERE status='失败' AND note IS NOT NULL AND note!='' "
                    "GROUP BY note ORDER BY n DESC LIMIT 5"
                ).fetchall()
            ]
            conn.close()
            db_stats = {"ok": True, "total": total, "by_status": by_status,
                        "by_module": by_module, "top_failures": top_failures}
        except Exception as e:
            db_stats = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    summary = {
        "ok": True,
        "pool_root": config.POOL_ROOT,
        "jobs": {
            "pending": len(pending),
            "claimed": sum(len(v) for v in claimed.values()),
            "done": len(done),
            "failed": len(failed),
        },
        "workers": {
            w: {
                "claimed_count": len(jobs),
                "claimed_jobs": jobs,
                "last_status": worker_st.get(w, {}),
            } for w, jobs in claimed.items()
        },
        "pending_jobs": pending,
        "done_jobs": [{"job_id": d.get("job_id"), "module": d.get("module"),
                       "stats": d.get("stats", {})} for d in done],
        "failed_jobs": [{"job_id": d.get("job_id"), "module": d.get("module"),
                         "error": d.get("error", "")[:200]} for d in failed],
        "db": db_stats,
    }

    # Human-readable print.
    print(f"=== qumall-pool status ===")
    print(f"pool: {config.POOL_ROOT}")
    print(f"jobs: pending={summary['jobs']['pending']}  claimed={summary['jobs']['claimed']}  done={summary['jobs']['done']}  failed={summary['jobs']['failed']}")
    if summary["db"].get("ok"):
        bs = summary["db"]["by_status"]
        print(f"cases: total={summary['db']['total']}  "
              f"通过={bs.get('通过', 0)}  失败={bs.get('失败', 0)}  跳过={bs.get('跳过', 0)}  pending={bs.get('(pending)', 0)}")
        if summary["db"]["top_failures"]:
            print("top failures:")
            for tf in summary["db"]["top_failures"]:
                print(f"  ({tf['n']}x) {tf['note']}")
    if claimed:
        print("active workers:")
        for w, info in summary["workers"].items():
            print(f"  {w}: {info['claimed_count']} job(s) — {', '.join(info['claimed_jobs'])}")
    print()
    # Also dump the full JSON to stdout for machine consumers.
    print("---JSON---")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
