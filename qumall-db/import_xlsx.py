#!/usr/bin/env python3
"""Import a dump_queue JSON (or the source xlsx via dump_queue) into qumall.db.

Two modes:

  1. import from the dump_queue JSON that excelio-mcp-server/dump_queue.py
     produces (default — the agent pipeline already uses it):
         python import_xlsx.py --db blueprints/qumall.db \\
             --queue blueprints/qumall-full-queue.json

  2. import directly from a mirror xlsx (re-runs dump_queue internally):
         python import_xlsx.py --db blueprints/qumall.db \\
             --mirror blueprints/qumall-full-replay.xlsx

Behavior:
- Idempotent: re-running the same import updates module/function/... but
  PRESERVES any existing status / note / updated_at (so a partial run
  can be re-imported without losing progress).
- Prints one JSON line: {ok, db, total, source}.

Stdlib only. No MCP, no openpyxl, no external deps.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

# Import cli.py from the same package without triggering its __main__.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cli as qumall_cli  # noqa: E402


def _dump_queue_via_subprocess(mirror: Path) -> dict:
    """Re-run dump_queue.py to get a fresh JSON. Avoids hard-importing
    excelio-mcp-server modules into qumall-db (keeps the dep tree clean)."""
    dump_script = (
        Path(__file__).resolve().parent.parent
        / "excelio-mcp-server"
        / "dump_queue.py"
    )
    if not dump_script.exists():
        raise FileNotFoundError(f"dump_queue.py not found at {dump_script}")
    out_path = mirror.with_suffix(".queue.json")
    subprocess.run(
        [
            sys.executable,
            str(dump_script),
            "--mirror", str(mirror),
            "--out", str(out_path),
        ],
        check=True,
    )
    return json.loads(out_path.read_text(encoding="utf-8"))


def _ensure_schema(db: Path) -> None:
    qumall_cli.cmd_init(argparse.Namespace(db=str(db)))


def _import_cases(db: Path, cases: list[dict], preserve_results: bool) -> tuple[int, int]:
    """Upsert all cases. Returns (inserted, updated) counts."""
    db.parent.mkdir(parents=True, exist_ok=True)
    inserted = 0
    updated = 0
    with sqlite3.connect(str(db)) as conn:
        for case in cases:
            # dump_queue JSON shape: {row, id, module, function, subfunction,
            # title, preconditions, test_data, steps, expected}.
            # NOTE: `id` is NOT unique (e.g. test_001 recurs in 登录 and 基础功能).
            # We use sheet_row as the natural primary key.
            row = int(case["row"])
            case_id = str(case.get("id") or f"row{row}")
            if preserve_results:
                # On re-import: only update non-result columns; keep status/note
                # so a partial run isn't lost.
                conn.execute(
                    """
                    INSERT INTO cases
                        (id, sheet_row, module, function, subfunction, title,
                         preconditions, test_data, steps, expected)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sheet_row) DO UPDATE SET
                        id            = excluded.id,
                        module        = excluded.module,
                        function      = excluded.function,
                        subfunction   = excluded.subfunction,
                        title         = excluded.title,
                        preconditions = excluded.preconditions,
                        test_data     = excluded.test_data,
                        steps         = excluded.steps,
                        expected      = excluded.expected
                    """,
                    (
                        case_id,
                        row,
                        case.get("module", ""),
                        case.get("function", ""),
                        case.get("subfunction") or "",
                        case.get("title", ""),
                        case.get("preconditions") or "",
                        case.get("test_data") or "",
                        case.get("steps", ""),
                        case.get("expected", ""),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO cases
                        (id, sheet_row, module, function, subfunction, title,
                         preconditions, test_data, steps, expected,
                         status, note, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            NULL, '', NULL)
                    """,
                    (
                        case_id,
                        row,
                        case.get("module", ""),
                        case.get("function", ""),
                        case.get("subfunction") or "",
                        case.get("title", ""),
                        case.get("preconditions") or "",
                        case.get("test_data") or "",
                        case.get("steps", ""),
                        case.get("expected", ""),
                    ),
                )
        conn.commit()
        inserted = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        updated = 0
    return inserted, updated


def main() -> int:
    p = argparse.ArgumentParser(description="Import dump_queue JSON (or mirror xlsx) into qumall.db")
    p.add_argument("--db", required=True, help="Path to qumall.db (created if missing)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--queue", help="Path to dump_queue JSON")
    src.add_argument("--mirror", help="Path to mirror xlsx (will run dump_queue internally)")
    p.add_argument(
        "--reset",
        action="store_true",
        help="Drop existing rows and re-insert (clears any prior status/note). "
             "Default is to preserve prior results.",
    )
    args = p.parse_args()

    db = Path(args.db)
    if args.mirror:
        data = _dump_queue_via_subprocess(Path(args.mirror))
    else:
        data = json.loads(Path(args.queue).read_text(encoding="utf-8"))

    cases = data.get("cases") or []
    _ensure_schema(db)

    if args.reset:
        # Drop and recreate so re-import is fully clean.
        with sqlite3.connect(str(db)) as conn:
            conn.execute("DELETE FROM cases")
            conn.commit()

    inserted, _ = _import_cases(db, cases, preserve_results=not args.reset)
    print(json.dumps(
        {
            "ok": True,
            "db": str(db),
            "total": inserted,
            "source": args.queue or args.mirror,
            "modules": data.get("modules") or {},
            "preserved_results": not args.reset,
        },
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
