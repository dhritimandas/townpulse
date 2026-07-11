"""FastAPI app: read-only serving + scheduler lifespan.

Full API contract per TOWN_PULSE_SPEC.md §5.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.config import DATABASE_PATH
from app.db import get_connection, init_db
from app.errors import TownPulseError
from app.queries import build_report, get_skill, get_skill_history, list_skills, recommend
from app.scheduler import build_scheduler

logging.basicConfig(level=logging.INFO)

_startup_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
_SKILL_MD_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"

ROOT = {
    "service": "Town Pulse",
    "description": "Continuous reliability index for the Nanda Town registry",
    "skill_md": "https://townpulse-production.up.railway.app/skill.md",
    "about": "/about",
    "health": "/health",
}

ABOUT = {
    "methodology": (
        "Every few minutes Town Pulse fetches the Nanda Town registry, probes "
        "each tracked skill, and recomputes its reliability score from the "
        "accumulated probe history. Serving endpoints only read precomputed "
        "scores; they never probe or rescore on request."
    ),
    "score_formula": (
        "score = 100 * (0.40*alive_now + 0.35*uptime_24h + 0.15*docs_ok + 0.10*latency_pt), "
        "latency_pt = clamp(1 - p50_latency_ms/5000, 0, 1). "
        "alive_now: any successful probe in the most recent cycle. "
        "uptime_24h: fraction of cycles in the last 24h with at least one successful probe. "
        "docs_ok: SKILL.md (or content) fetchable/present AND at least one endpoint line parses. "
        "Skills with fewer than 3 recorded probes should be treated with low confidence."
    ),
    "probe_ethics": (
        "Town Pulse only issues read-only GET requests to URLs participants publicly "
        "declared in the registry: the SKILL.md source, the root of each declared "
        "endpoint's host, and declared GET endpoints containing no {placeholder}. It "
        "never sends POST/PUT/DELETE/PATCH, never substitutes values into parameterized "
        "endpoints, and never attempts authentication. Each target is probed at most "
        "once per endpoint per cycle, cycles at least 5 minutes apart, with a 10s "
        "timeout and the identifying User-Agent TownPulse/1.0. A 401/403/405 response "
        "to a root-host probe counts as evidence the host is alive, not as a failure."
    ),
    "dedup_policy": (
        "The registry's edit path is resubmission (no edit button), so the same skill "
        "can appear multiple times under the same name. Town Pulse groups records by "
        "normalized (lowercased, trimmed) name and treats the newest created_at in each "
        "group as active; every other record in the group is marked superseded, is "
        "never probed, and is excluded from /skills, /recommend, and /report. "
        "Limitation: two different skills that happen to share a display name are "
        "incorrectly merged."
    ),
}


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(TownPulseError)
async def town_pulse_error_handler(request: Request, exc: TownPulseError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.error, "hint": exc.hint})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    messages = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=400, content={"error": "invalid request", "hint": messages})


@app.get("/")
def root() -> dict:
    return ROOT


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


@app.get("/skill.md")
def skill_md() -> Response:
    if not _SKILL_MD_PATH.exists():
        raise TownPulseError(404, "SKILL.md not found", "SKILL.md has not been published yet")
    return Response(content=_SKILL_MD_PATH.read_text(), media_type="text/markdown")


@app.get("/about")
def about() -> dict:
    return ABOUT


@app.get("/skills")
def skills() -> dict:
    conn = get_connection(DATABASE_PATH)
    try:
        rows = list_skills(conn)
    finally:
        conn.close()
    return {"count": len(rows), "skills": rows}


@app.get("/skills/{skill_id}")
def skill_detail(skill_id: str) -> dict:
    conn = get_connection(DATABASE_PATH)
    try:
        skill = get_skill(conn, skill_id)
    finally:
        conn.close()
    if skill is None:
        raise TownPulseError(404, "unknown skill id", "GET /skills for ids")
    return skill


@app.get("/skills/{skill_id}/history")
def skill_history(skill_id: str, hours: int = Query(24, ge=1)) -> dict:
    conn = get_connection(DATABASE_PATH)
    try:
        history = get_skill_history(conn, skill_id, hours)
    finally:
        conn.close()
    if history is None:
        raise TownPulseError(404, "unknown skill id", "GET /skills for ids")
    return history


@app.get("/recommend")
def recommend_route(
    need: str = Query(...),
    min_uptime: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(3, ge=1),
) -> dict:
    conn = get_connection(DATABASE_PATH)
    try:
        result = recommend(conn, need, min_uptime, limit)
    finally:
        conn.close()
    return result


@app.get("/report")
def report() -> dict:
    conn = get_connection(DATABASE_PATH)
    try:
        result = build_report(conn)
    finally:
        conn.close()
    return result
