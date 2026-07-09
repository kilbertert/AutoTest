-- qumall.db schema — stores the replay queue + per-case status.
-- One row per test case. status and note are written by the agent during
-- Stage 4 execution; everything else is populated by import_xlsx.py from the
-- dump_queue JSON (which mirrors the source xlsx's 16-col layout).

CREATE TABLE IF NOT EXISTS cases (
    id            TEXT NOT NULL,
    sheet_row     INTEGER PRIMARY KEY,
    module        TEXT NOT NULL,
    function      TEXT NOT NULL,
    subfunction   TEXT,
    title         TEXT NOT NULL,
    preconditions TEXT,
    test_data     TEXT,
    steps         TEXT NOT NULL,
    expected      TEXT NOT NULL,
    status        TEXT,
    note          TEXT,
    updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_cases_status     ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_module    ON cases(module);
CREATE INDEX IF NOT EXISTS idx_cases_sheet_row ON cases(sheet_row);
