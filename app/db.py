"""SQLite schema and connection helper.

Blocking sqlite3 is used directly (no ORM, no async driver) -- at this
dataset's scale (~100 skills, low thousands of probes/day) a brief blocking
call per request/cycle is not a bottleneck.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    tags TEXT,
    source_type TEXT NOT NULL,
    source_url TEXT,
    content TEXT,
    endpoints_raw TEXT,
    reachable_raw INTEGER,
    created_at TEXT,
    superseded_by TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS probes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL,
    target TEXT NOT NULL,
    kind TEXT NOT NULL,
    ts TEXT NOT NULL,
    ok INTEGER NOT NULL,
    status_code INTEGER,
    latency_ms INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS ix_probes_skill_ts ON probes(skill_id, ts);

CREATE TABLE IF NOT EXISTS scores (
    skill_id TEXT PRIMARY KEY,
    alive_now INTEGER NOT NULL,
    uptime_24h REAL NOT NULL,
    uptime_all REAL NOT NULL,
    p50_latency_ms INTEGER,
    docs_ok INTEGER NOT NULL,
    n_probes INTEGER NOT NULL,
    score REAL NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
