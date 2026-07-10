"""Manual one-off script: run exactly one real prober cycle against the live
Nanda Town registry and print row counts + sample rows.

Not part of the deployed service -- a verification tool for Milestone 1.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cycle import run_cycle  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402

DB_PATH = "./pulse_manual_run.db"


async def main() -> None:
    conn = get_connection(DB_PATH)
    init_db(conn)

    summary = await run_cycle(conn, DB_PATH)
    print("Cycle summary:", summary)

    n_skills = conn.execute("SELECT COUNT(*) AS n FROM skills").fetchone()["n"]
    n_active = conn.execute(
        "SELECT COUNT(*) AS n FROM skills WHERE superseded_by IS NULL"
    ).fetchone()["n"]
    n_probes = conn.execute("SELECT COUNT(*) AS n FROM probes").fetchone()["n"]
    n_scores = conn.execute("SELECT COUNT(*) AS n FROM scores").fetchone()["n"]

    print(f"\nskills: {n_skills} total, {n_active} active (non-superseded)")
    print(f"probes: {n_probes}")
    print(f"scores: {n_scores}")

    print("\n5 sample probe rows:")
    rows = conn.execute(
        "SELECT skill_id, target, kind, ok, status_code, latency_ms, error FROM probes LIMIT 5"
    ).fetchall()
    for row in rows:
        print(dict(row))

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
