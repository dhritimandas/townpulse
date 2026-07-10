"""FastAPI app: read-only serving + scheduler lifespan.

Milestone 1 exposes only /health; the rest of the API contract (spec §5)
lands in Milestone 2.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from app.config import DATABASE_PATH
from app.db import get_connection, init_db
from app.scheduler import build_scheduler

logging.basicConfig(level=logging.INFO)

_startup_time = datetime.now(timezone.utc).isoformat(timespec="seconds")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection(DATABASE_PATH)
    init_db(conn)
    conn.close()

    scheduler = build_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Town Pulse", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    conn = get_connection(DATABASE_PATH)
    try:
        skills_tracked = conn.execute(
            "SELECT COUNT(*) AS n FROM skills WHERE superseded_by IS NULL"
        ).fetchone()["n"]
        probe_cycles = conn.execute("SELECT COUNT(DISTINCT ts) AS n FROM probes").fetchone()["n"]
        since_row = conn.execute("SELECT MIN(ts) AS since FROM probes").fetchone()
        since = since_row["since"] or _startup_time
    finally:
        conn.close()

    return {
        "status": "ok",
        "skills_tracked": skills_tracked,
        "probe_cycles": probe_cycles,
        "since": since,
    }
