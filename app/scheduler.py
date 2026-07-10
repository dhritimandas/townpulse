"""APScheduler wiring: runs one prober cycle immediately at startup, then
every CYCLE_INTERVAL_MINUTES.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import CYCLE_INTERVAL_MINUTES, DATABASE_PATH
from app.cycle import run_cycle
from app.db import get_connection, init_db

logger = logging.getLogger(__name__)


async def _run_cycle_job() -> None:
    conn = get_connection(DATABASE_PATH)
    try:
        init_db(conn)
        summary = await run_cycle(conn, DATABASE_PATH)
        logger.info("cycle complete: %s", summary)
    except Exception:
        logger.exception("prober cycle failed")
    finally:
        conn.close()


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_cycle_job,
        "interval",
        minutes=CYCLE_INTERVAL_MINUTES,
        id="probe_cycle",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )
    return scheduler
