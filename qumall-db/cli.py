#!/usr/bin/env python3
"""qumall-db CLI — tiny command surface for the agent to drive case execution.

Subcommands (each prints one line of JSON to stdout):

  init --db PATH                       Create / migrate schema (idempotent).
  get --db PATH --id CASE_ID           Fetch one case as JSON.
  next-pending --db PATH               Return the lowest-sheet_row pending case
                                       (single-machine, no claim).
  claim-next --db PATH --worker WID    ATOMIC claim by worker WID. Used by the
                                       --lease-minutes N (default 30)        multi-worker pool so 2+ machines
                                       don't pick the same case.
  release --db PATH --id ID --worker WID
                                       Clear the claim on a case (e.g. if
                                       the agent fails before set).
  sweep-expired --db PATH              Find cases whose lease has expired
                                       (worker crashed) and free them.
  set --db PATH --id ID --status S     Write status (通过/失败/跳过) and --note.
  stats --db PATH                      Aggregate counts + per-module breakdown
                                       + per-worker breakdown.

Why this exists: xlsx round-trips are slow and the agent kept looping on
read_sheet / read_header / list_sheets to "double-check" the queue. SQLite
gives precise per-case queries and idempotent writes.

Multi-worker model:
  - Each machine is a "worker" (A, B, C, ...). One SQLite DB on a shared
    drive (SMB/NFS) holds the queue + status.
  - claim-next is atomic: UPDATE cases SET worker=?, claimed_at=?, lease_until=?
    WHERE status IS NULL AND (lease_until IS NULL OR lease_until < now)
    ORDER BY sheet_row LIMIT 1 RETURNING *.
  - SQLite locks the DB during the transaction, so two simultaneous
    claim-next calls from different workers get different rows.
  - When a worker crashes, its cases' leases expire after N minutes
    (default 30); sweep-expired (or claim-next itself) reclaims them.
  - set must be called with the same worker_id that claimed the row
    (or with --force), otherwise the write is refused (preventing
    stale workers from clobbering a row another worker is now running).

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
    """Create the schema and run lightweight migrations.

    Migrations are idempotent ALTERs that backfill columns added in newer
    versions of schema.sql. Safe to run on existing DBs.
    """
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with _connect(Path(args.db)) as conn:
        conn.executescript(schema)
        # v2 migration: add worker/claimed_at/lease_until if missing.
        # PRAGMA table_info doesn't raise on missing column, so probe by name.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(cases)").fetchall()}
        for col, decl in (
            ("worker",      "TEXT"),
            ("claimed_at",  "TEXT"),
            ("lease_until", "TEXT"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {col} {decl}")
        conn.commit()
    return {"ok": True, "db": args.db, "action": "init"}


def cmd_get(args: argparse.Namespace) -> dict[str, Any]:
    with _connect(Path(args.db)) as conn:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (args.id,)).fetchone()
    if row is None:
        return {"ok": False, "error": f"case id not found: {args.id}"}
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
    if row is None:
        return {"ok": True, "case": None, "remaining": 0}
    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM cases WHERE status IS NULL OR status = ''"
    ).fetchone() if False else None  # see below; recompute cleanly:
    with _connect(Path(args.db)) as conn2:
        rem_row = conn2.execute(
            "SELECT COUNT(*) AS n FROM cases WHERE status IS NULL OR status = ''"
        ).fetchone()
    remaining_n = rem_row["n"] if rem_row else 0
    return {"ok": True, "case": _row_to_dict(row), "remaining": remaining_n}


def cmd_set(args: argparse.Namespace) -> dict[str, Any]:
    status = args.status
    if status not in ("通过", "失败", "跳过"):
        return {"ok": False, "error": f"invalid status: {status!r} (must be 通过/失败/跳过)"}
    note = args.note or ""
    if len(note) > 200:
        return {"ok": False, "error": f"note too long ({len(note)} > 200 chars)"}
    with _connect(Path(args.db)) as conn:
        # Worker ownership check: if this case was claimed by another worker
        # and the lease is still valid, refuse the write so a stale worker
        # can't clobber a row another worker is now running.
        if args.worker and not args.force:
            row = conn.execute(
                "SELECT worker, lease_until FROM cases WHERE id = ?", (args.id,)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": f"case id not found: {args.id}"}
            owner = row["worker"]
            lease = row["lease_until"]
            if owner and owner != args.worker:
                if not lease or lease > _now_iso():
                    return {
                        "ok": False,
                        "error": (
                            f"case {args.id} is claimed by worker {owner!r} "
                            f"(lease {lease}); current worker {args.worker!r} "
                            "cannot write. Pass --force to override (unsafe)."
                        ),
                    }
        cur = conn.execute(
            "UPDATE cases SET status = ?, note = ?, updated_at = ?, "
            "worker = NULL, claimed_at = NULL, lease_until = NULL "
            "WHERE id = ?",
            (status, note, _now_iso(), args.id),
        )
        conn.commit()
    if cur.rowcount == 0:
        return {"ok": False, "error": f"case id not found: {args.id}"}
    return {"ok": True, "id": args.id, "status": status, "note_len": len(note)}


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
        # Per-worker in-flight (claimed, not yet finished) so the operator
        # can see which machines are alive and what they're working on.
        by_worker_rows = conn.execute(
            """
            SELECT worker,
                   COUNT(*) AS claimed,
                   MIN(claimed_at) AS oldest_claim,
                   MIN(lease_until) AS nearest_lease
            FROM cases
            WHERE worker IS NOT NULL AND worker != ''
            GROUP BY worker
            ORDER BY worker
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
    by_worker = [_row_to_dict(r) for r in by_worker_rows]
    return {
        "ok": True,
        "total": total_row["n"],
        "by_status": by_status,
        "by_module": by_module,
        "by_worker": by_worker,
        "top_failures": [_row_to_dict(r) for r in top_failures],
    }


# ─── multi-worker commands ──────────────────────────────────────────────


def cmd_claim_next(args: argparse.Namespace) -> dict[str, Any]:
    """Atomically claim the next pending case for this worker.

    The transaction:
      UPDATE cases SET worker=?, claimed_at=?, lease_until=?
        WHERE status IS NULL
          AND (lease_until IS NULL OR lease_until < ?)
        ORDER BY sheet_row LIMIT 1
        RETURNING *

    SQLite locks the DB during the UPDATE, so two concurrent workers calling
    claim-next get DIFFERENT rows. Workers that crashed leave stale leases;
    a lease older than `--lease-minutes` ago is reclaimable by anyone
    (a "sweep" pass on claim-next handles this transparently).
    """
    if not args.worker:
        return {"ok": False, "error": "--worker is required for claim-next"}
    lease_minutes = max(1, int(args.lease_minutes or 30))
    now = datetime.datetime.now(datetime.timezone.utc)
    claimed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    lease_until = (now + datetime.timedelta(minutes=lease_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _connect(Path(args.db)) as conn:
        # First: transparently reclaim any expired leases.
        conn.execute(
            "UPDATE cases SET worker = NULL, claimed_at = NULL, lease_until = NULL "
            "WHERE worker IS NOT NULL AND lease_until IS NOT NULL AND lease_until < ?",
            (claimed_at,),
        )
        # SQLite supports UPDATE ... RETURNING since 3.35. The subquery
        # MUST exclude rows that are already claimed by a live lease
        # (worker IS NOT NULL AND lease_until > now), otherwise a
        # not-yet-finished claim would be re-claimed by another worker.
        row = conn.execute(
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
            RETURNING *
            """,
            (args.worker, claimed_at, lease_until, claimed_at),
        ).fetchone()
        conn.commit()
    if row is None:
        return {"ok": True, "case": None, "remaining": 0, "worker": args.worker}
    # Count remaining for the operator's convenience.
    with _connect(Path(args.db)) as conn:
        rem = conn.execute(
            "SELECT COUNT(*) AS n FROM cases WHERE status IS NULL OR status = ''"
        ).fetchone()["n"]
    return {
        "ok": True,
        "case": _row_to_dict(row),
        "remaining": rem,
        "worker": args.worker,
        "lease_until": lease_until,
    }


def cmd_release(args: argparse.Namespace) -> dict[str, Any]:
    """Clear the claim on a case so another worker can re-claim it.

    Use cases:
      - agent calls claim-next but then crashes before set
      - agent wants to give up on a case and let the sweeper re-distribute
      - operator manually re-queues a row

    Idempotent: if the case isn't claimed (or isn't ours), returns ok with
    released=0 instead of erroring.
    """
    if not args.worker:
        return {"ok": False, "error": "--worker is required for release"}
    with _connect(Path(args.db)) as conn:
        cur = conn.execute(
            """
            UPDATE cases SET worker = NULL, claimed_at = NULL, lease_until = NULL
            WHERE id = ? AND worker = ?
            """,
            (args.id, args.worker),
        )
        conn.commit()
    return {"ok": True, "id": args.id, "released": cur.rowcount}


def cmd_sweep_expired(args: argparse.Namespace) -> dict[str, Any]:
    """Free all cases whose lease has expired (their worker is presumed dead).

    Returns the count of reclaimed cases. Safe to call from any machine; safe
    to call repeatedly. claim-next also does this transparently, so the
    operator doesn't NEED to call sweep — but a periodic cron sweep keeps
    the dashboard clean and surfaces crashed workers faster.
    """
    now = _now_iso()
    with _connect(Path(args.db)) as conn:
        cur = conn.execute(
            """
            UPDATE cases SET worker = NULL, claimed_at = NULL, lease_until = NULL
            WHERE worker IS NOT NULL AND lease_until IS NOT NULL AND lease_until < ?
            """,
            (now,),
        )
        # Surface who was reclaimed so the operator can investigate.
        reclaimed_rows = conn.execute(
            "SELECT worker, COUNT(*) AS n FROM cases WHERE lease_until IS NULL "
            "AND claimed_at IS NULL AND updated_at IS NULL AND worker IS NULL "
            "AND id IN (SELECT id FROM cases WHERE 1=0) "  # placeholder
        ).fetchall()
        conn.commit()
    # We can't easily say "who was reclaimed" from a single UPDATE. The above
    # SELECT is a placeholder. Real implementation: SELECT ... FROM history.
    # For now, just return the count.
    return {"ok": True, "reclaimed": cur.rowcount, "reclaimed_workers": []}


# ─── arg parser ─────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="qumall-db CLI for agent-driven case execution")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", required=True, help="Path to qumall.db")

    sp = sub.add_parser("init", parents=[common], help="Create schema if missing (idempotent + migrates)")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("get", parents=[common], help="Fetch one case by id")
    sp.add_argument("--id", required=True, help="用例ID")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("next-pending", parents=[common],
                        help="Return the next pending case (single-machine)")
    sp.set_defaults(func=cmd_next_pending)

    sp = sub.add_parser("claim-next", parents=[common],
                        help="ATOMIC claim by worker. Multi-worker safe.")
    sp.add_argument("--worker", required=True, help="worker id (e.g. A, B, machine-01)")
    sp.add_argument("--lease-minutes", type=int, default=30,
                    help="If worker doesn't set before this, the claim expires and "
                         "another worker can take over. Default 30.")
    sp.set_defaults(func=cmd_claim_next)

    sp = sub.add_parser("release", parents=[common],
                        help="Free a claim (so another worker can re-claim)")
    sp.add_argument("--id", required=True, help="用例ID")
    sp.add_argument("--worker", required=True, help="worker id (must match the claim)")
    sp.set_defaults(func=cmd_release)

    sp = sub.add_parser("sweep-expired", parents=[common],
                        help="Free all cases whose lease has expired (crashed worker)")
    sp.set_defaults(func=cmd_sweep_expired)

    sp = sub.add_parser("set", parents=[common], help="Write status + note for one case")
    sp.add_argument("--id", required=True, help="用例ID")
    sp.add_argument("--status", required=True, help="通过 / 失败 / 跳过")
    sp.add_argument("--note", default="", help="备注 (≤ 200 chars)")
    sp.add_argument("--worker", default=None,
                    help="If set, refuses to write rows claimed by a different worker "
                         "(prevents stale workers from clobbering active cases).")
    sp.add_argument("--force", action="store_true",
                    help="Override the worker ownership check. Use with care.")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("stats", parents=[common],
                        help="Aggregate counts + per-module + per-worker breakdown")
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
