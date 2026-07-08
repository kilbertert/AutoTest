-- qumall.db schema — stores the replay queue + per-case status.
-- One row per test case. status and note are written by the agent during
-- Stage 4 execution; everything else is populated by import_xlsx.py from the
-- dump_queue JSON (which mirrors the source xlsx's 16-col layout).

CREATE TABLE IF NOT EXISTS cases (
    id            TEXT PRIMARY KEY,
    sheet_row     INTEGER NOT NULL,
    module        TEXT NOT NULL,
    function      TEXT NOT NULL,
    subfunction   TEXT,
    title         TEXT NOT NULL,
    preconditions TEXT,
    test_data     TEXT,
    steps         TEXT NOT NULL,
    expected      TEXT NOT NULL,
    status        TEXT,                    -- NULL = pending; "通过" / "失败" / "跳过"
    note          TEXT,                    -- 备注 (≤ 200 chars, populated on 失败/跳过)
    updated_at    TEXT,                    -- ISO8601 of last status write
    -- Multi-worker claim tracking (added when migrating from single-machine
    -- run to parallel workers). claim-next sets these atomically; release
    -- clears them on success/failure. A row whose lease_until < now() is
    -- reclaimable by another worker (so a crashed worker doesn't lock rows).
    worker        TEXT,                    -- worker_id that claimed this case (e.g. "A", "B")
    claimed_at    TEXT,                    -- ISO8601 when claim-next succeeded
    lease_until   TEXT                     -- ISO8601; if NULL, no lease; if past, reclaimable
);

CREATE INDEX IF NOT EXISTS idx_cases_status     ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_module    ON cases(module);
CREATE INDEX IF NOT EXISTS idx_cases_sheet_row ON cases(sheet_row);
CREATE INDEX IF NOT EXISTS idx_cases_worker    ON cases(worker);
CREATE INDEX IF NOT EXISTS idx_cases_lease     ON cases(lease_until);
