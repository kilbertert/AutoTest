#!/usr/bin/env python3
"""qumall-db CLI — tiny command surface for the agent to drive case execution.

Five subcommands, each prints one line of JSON to stdout. Designed so the
agent can do everything via `bash uv run python qumall-db/cli.py <cmd> ...`:

  init --db PATH                      Create schema (idempotent).
  get --db PATH --id CASE_ID          Fetch one case as JSON.
  next-pending --db PATH              Return the lowest-sheet_row pending case.
  set --db PATH --id ID --status S    Write status (通过/失败/跳过) and optional --note.
  stats --db PATH                     Aggregate counts + per-module breakdown.

Why this exists: xlsx round-trips are slow and the agent kept looping on
read_sheet / read_header / list_sheets to "double-check" the queue. SQLite
gives precise per-case queries and idempotent writes.

Usage from the agent (skill Stage 4 per-case loop):

  # once at run start
  uv run python qumall-db/cli.py init    --db blueprints/qumall.db
  uv run python qumall-db/cli.py import  --db blueprints/qumall.db \\
      --queue blueprints/qumall-pilot-queue.json    (or see import_xlsx.py for the full pipeline)

  # per case
  case=$(uv run python qumall-db/cli.py next-pending --db blueprints/qumall.db)
  # ... execute the steps ...
  uv run python qumall-db/cli.py set     --db blueprints/qumall.db \\
      --id test_001 --status 通过 --note "首页KPI卡片正常"

  # final report
  uv run python qumall-db/cli.py stats   --db blueprints/qumall.db

Stdlib only (sqlite3, json, argparse, datetime). Run via the project venv or
any Python 3.10+. Output is always single-line JSON for easy agent parsing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


# ─── helpers ────────────────────────────────────────────────────────────


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── subcommands ────────────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with _connect(Path(args.db)) as conn:
        conn.executescript(schema)
        conn.commit()
    return {"ok": True, "db": args.db, "action": "init"}


def cmd_get(args: argparse.Namespace) -> dict[str, Any]:
    with _connect(Path(args.db)) as conn:
        # Look up by sheet_row (unique) primarily; fall back to id.
        try:
            row_id = int(args.id)
            row = conn.execute("SELECT * FROM cases WHERE sheet_row = ?", (row_id,)).fetchone()
        except (ValueError, TypeError):
            row = conn.execute("SELECT * FROM cases WHERE id = ?", (args.id,)).fetchone()
    if row is None:
        return {"ok": False, "error": f"case not found: {args.id}"}
    return {"ok": True, "case": _row_to_dict(row)}


def cmd_next_pending(args: argparse.Namespace) -> dict[str, Any]:
    with _connect(Path(args.db)) as conn:
        # The "pending" case is the one with the lowest sheet_row whose status
        # is NULL (or empty string from a prior partial run). The agent
        # typically loops on this to drive the queue in source order.
        row = conn.execute(
            """
            SELECT * FROM cases
            WHERE status IS NULL OR status = ''
            ORDER BY sheet_row ASC
            LIMIT 1
            """
        ).fetchone()
        rem_row = conn.execute(
            "SELECT COUNT(*) AS n FROM cases WHERE status IS NULL OR status = ''"
        ).fetchone()
    if row is None:
        return {"ok": True, "case": None, "remaining": 0}
    case_dict = _row_to_dict(row)
    # The CLI client should use sheet_row as the unique key (NOT id, which
    # can repeat across modules). Inject a "_key" hint.
    case_dict["_key"] = str(case_dict["sheet_row"])
    return {"ok": True, "case": case_dict, "remaining": rem_row["n"]}


def cmd_set(args: argparse.Namespace) -> dict[str, Any]:
    status = args.status
    if status not in ("通过", "失败", "跳过"):
        return {"ok": False, "error": f"invalid status: {status!r} (must be 通过/失败/跳过)"}
    note = args.note or ""
    if len(note) > 200:
        return {"ok": False, "error": f"note too long ({len(note)} > 200 chars)"}
    with _connect(Path(args.db)) as conn:
        # Look up by sheet_row (unique) primarily; fall back to id.
        try:
            row_id = int(args.id)
            cur = conn.execute(
                "UPDATE cases SET status = ?, note = ?, updated_at = ? WHERE sheet_row = ?",
                (status, note, _now_iso(), row_id),
            )
        except (ValueError, TypeError):
            cur = conn.execute(
                "UPDATE cases SET status = ?, note = ?, updated_at = ? WHERE id = ?",
                (status, note, _now_iso(), args.id),
            )
        conn.commit()
    if cur.rowcount == 0:
        return {"ok": False, "error": f"case not found: {args.id}"}
    return {"ok": True, "id": args.id, "sheet_row": row_id if isinstance(row_id, int) else None, "status": status, "note_len": len(note)}


def cmd_stats(args: argparse.Namespace) -> dict[str, Any]:
    with _connect(Path(args.db)) as conn:
        total_row = conn.execute("SELECT COUNT(*) AS n FROM cases").fetchone()
        by_status_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM cases GROUP BY status ORDER BY n DESC"
        ).fetchall()
        by_module_rows = conn.execute(
            """
            SELECT module,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = '通过' THEN 1 ELSE 0 END) AS passed,
                   SUM(CASE WHEN status = '失败' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN status = '跳过' THEN 1 ELSE 0 END) AS skipped,
                   SUM(CASE WHEN status IS NULL OR status = '' THEN 1 ELSE 0 END) AS pending
            FROM cases
            GROUP BY module
            ORDER BY module
            """
        ).fetchall()
        # Top 5 failure reasons (group by note text, count occurrences).
        top_failures = conn.execute(
            """
            SELECT note, COUNT(*) AS n
            FROM cases
            WHERE status = '失败' AND note IS NOT NULL AND note != ''
            GROUP BY note
            ORDER BY n DESC
            LIMIT 5
            """
        ).fetchall()
    by_status = {r["status"] or "(pending)": r["n"] for r in by_status_rows}
    by_module = [_row_to_dict(r) for r in by_module_rows]
    return {
        "ok": True,
        "total": total_row["n"],
        "by_status": by_status,
        "by_module": by_module,
        "top_failures": [_row_to_dict(r) for r in top_failures],
    }


# ─── arg parser ─────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="qumall-db CLI for agent-driven case execution")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", required=True, help="Path to qumall.db")

    sp = sub.add_parser("init", parents=[common], help="Create schema if missing")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("get", parents=[common], help="Fetch one case by id")
    sp.add_argument("--id", required=True, help="用例ID")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("next-pending", parents=[common], help="Return the next pending case")
    sp.set_defaults(func=cmd_next_pending)

    sp = sub.add_parser("set", parents=[common], help="Write status + note for one case")
    sp.add_argument("--id", required=True, help="用例ID")
    sp.add_argument("--status", required=True, help="通过 / 失败 / 跳过")
    sp.add_argument("--note", default="", help="备注 (≤ 200 chars)")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("stats", parents=[common], help="Aggregate counts + per-module breakdown")
    sp.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except Exception as e:  # surface as structured error, never crash
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
