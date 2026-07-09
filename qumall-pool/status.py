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
Also writes a Markdown report to REPORT.md on the share, so any
operator can read the latest run status without re-running this script.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


REPORT_MD   = os.path.join(config.POOL_ROOT, "REPORT.md")
REPORT_JSON = os.path.join(config.POOL_ROOT, "REPORT.json")


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


def _write_markdown_report(summary: dict) -> str:
    """Render summary as a Markdown report, write to REPORT.md, return the path."""
    bs = summary["db"].get("by_status", {}) if summary["db"].get("ok") else {}
    total     = summary["db"].get("total", 0)
    passed    = bs.get("通过", 0)
    failed    = bs.get("失败", 0)
    skipped   = bs.get("跳过", 0)
    pending_n = bs.get("(pending)", 0)
    finished  = passed + failed + skipped
    pct = (100.0 * passed / finished) if finished else 0.0

    lines = []
    lines.append("# qumall-pool 运行报告")
    lines.append("")
    lines.append(f"_生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_  ")
    lines.append(f"共享根: `{config.POOL_ROOT}`")
    lines.append("")
    lines.append("## 全局汇总")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 总用例 | {total} |")
    if total:
        lines.append(f"| 已完成 | {finished} ({100.0 * finished / total:.1f}%) |")
    else:
        lines.append("| 已完成 | 0 |")
    lines.append(f"| **通过** | **{passed}** ({pct:.1f}%) |")
    lines.append(f"| 失败 | {failed} |")
    lines.append(f"| 跳过 | {skipped} |")
    lines.append(f"| 未跑 | {pending_n} |")
    lines.append("")
    lines.append("## 任务池状态")
    lines.append("")
    j = summary["jobs"]
    lines.append(f"- pending: **{j['pending']}** 个 job 等待 claim")
    lines.append(f"- claimed: {j['claimed']} 个 job 正在跑")
    lines.append(f"- done: **{j['done']}** 个 job 已完成")
    lines.append(f"- failed: {j['failed']} 个 job 跑失败")
    lines.append("")

    if summary["workers"]:
        lines.append("## 当前活跃 worker")
        lines.append("")
        lines.append("| worker | claimed | jobs |")
        lines.append("|---|---|---|")
        for w, info in summary["workers"].items():
            lines.append(f"| `{w}` | {info['claimed_count']} | {', '.join(info['claimed_jobs'])} |")
        lines.append("")

    if summary["db"].get("by_module"):
        lines.append("## 按模块结果")
        lines.append("")
        lines.append("| 模块 | 总数 | 通过 | 失败 | 跳过 | 未跑 | 通过率 |")
        lines.append("|---|---|---|---|---|---|---|")
        for m in summary["db"]["by_module"]:
            t, p, f, s, pe = m["total"], m["passed"], m["failed"], m["skipped"], m["pending"]
            finish = p + f + s
            pr = (100.0 * p / finish) if finish else 0.0
            lines.append(f"| {m['module']} | {t} | {p} | {f} | {s} | {pe} | {pr:.1f}% |")
        lines.append("")

    if summary["db"].get("top_failures"):
        lines.append("## Top 失败原因")
        lines.append("")
        for tf in summary["db"]["top_failures"]:
            lines.append(f"- ({tf['n']}x) {tf['note']}")
        lines.append("")

    if summary["done_jobs"]:
        lines.append("## 已完成 job 详情")
        lines.append("")
        for d in summary["done_jobs"]:
            lines.append(f"### {d['module']} (`{d['job_id']}`)")
            lines.append("")
            stats = d.get("stats", {})
            if stats:
                lines.append("```")
                for k, v in stats.items():
                    lines.append(f"  {k}: {v}")
                lines.append("```")
            else:
                lines.append("_(无 stats)_")
            lines.append("")

    if summary["failed_jobs"]:
        lines.append("## 失败 job 详情")
        lines.append("")
        for d in summary["failed_jobs"]:
            err = d.get("error", "")
            lines.append(f"- **{d['module']}** (`{d['job_id']}`): {err}")
        lines.append("")

    md = "\n".join(lines)
    Path(REPORT_MD).parent.mkdir(parents=True, exist_ok=True)
    Path(REPORT_MD).write_text(md, encoding="utf-8")
    Path(REPORT_JSON).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return REPORT_MD


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

    # Write the Markdown report to the share.
    try:
        report_path = _write_markdown_report(summary)
        print(f"\nreport: {report_path}")
        print(f"        (open in any text editor; updates each time you run status.py)")
    except Exception as e:
        print(f"\n!! failed to write report: {e}")

    # Also dump the full JSON to stdout for machine consumers.
    print()
    print("---JSON---")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
