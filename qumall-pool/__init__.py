"""qumall-pool — multi-machine coordinator for running the 3590 qumall test cases.

Architecture:
  - Each machine runs `worker.py` which:
      1. atomically claims a job file from jobs/pending → jobs/claimed/<worker_id>/
      2. runs the cases (one per case via the trendpower headless runner)
      3. writes results back to the shared SQLite db + mirror xlsx
      4. moves the job file to jobs/done (or jobs/failed)
  - Jobs are split per-module by `split_jobs.py`.
  - `status.py` aggregates across all machines by scanning jobs/* + reading
    the shared qumall.db.
  - The shared SQLite uses WAL mode for cross-machine concurrency.

Pool path: \\\\192.168.2.77\\qumall-pool on SMB. All machines see the same
filesystem; we rely on os.rename atomicity (NTFS = atomic) for the claim.
"""
