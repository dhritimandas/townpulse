"""Read-only query logic for the serving API (spec §5).

Every function here reads from ``skills``/``scores``/``probes`` as already
computed by the prober cycle (app.cycle) -- nothing here recomputes a score,
alive_now, or docs_ok from raw probes. /skills/{id}/history is the one
exception that aggregates raw probes into per-cycle summaries, since showing
that history is the endpoint's entire purpose.
"""

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from app.parsing import normalize_tags, parse_endpoints
from app.scoring import median_latency

_NEED_TOKEN_RE = re.compile(r"\s+")


def list_skills(conn: sqlite3.Connection) -> list[dict]:
    """Every active skill with its score, sorted best first."""
    rows = conn.execute(
        """
        SELECT sk.id, sk.name, sk.tags, sc.score, sc.alive_now, sc.uptime_24h, sc.p50_latency_ms
        FROM scores sc JOIN skills sk ON sk.id = sc.skill_id
        ORDER BY sc.score DESC
        """
    ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "score": round(row["score"], 1),
            "alive_now": bool(row["alive_now"]),
            "uptime_24h": round(row["uptime_24h"], 2),
            "p50_latency_ms": row["p50_latency_ms"],
            "tags": normalize_tags(row["tags"]),
        }
        for row in rows
    ]


def get_skill(conn: sqlite3.Connection, skill_id: str) -> dict | None:
    """Full score record + the latest cycle's probe evidence, or None if the
    id is unknown (never registered, or superseded by a resubmission).
    """
    row = conn.execute(
        """
        SELECT sk.id, sk.name, sc.score, sc.alive_now, sc.uptime_24h, sc.uptime_all,
               sc.docs_ok, sc.n_probes, sc.p50_latency_ms
        FROM scores sc JOIN skills sk ON sk.id = sc.skill_id
        WHERE sk.id = ?
        """,
        (skill_id,),
    ).fetchone()
    if row is None:
        return None

    latest_ts = conn.execute(
        "SELECT MAX(ts) AS ts FROM probes WHERE skill_id = ?", (skill_id,)
    ).fetchone()["ts"]

    evidence = []
    if latest_ts is not None:
        evidence = [
            dict(r)
            for r in conn.execute(
                "SELECT target, status_code, latency_ms, ts FROM probes"
                " WHERE skill_id = ? AND ts = ? ORDER BY target",
                (skill_id, latest_ts),
            ).fetchall()
        ]

    return {
        "id": row["id"],
        "name": row["name"],
        "score": round(row["score"], 1),
        "alive_now": bool(row["alive_now"]),
        "uptime_24h": round(row["uptime_24h"], 2),
        "uptime_all": round(row["uptime_all"], 2),
        "docs_ok": bool(row["docs_ok"]),
        "n_probes": row["n_probes"],
        "p50_latency_ms": row["p50_latency_ms"],
        "latest_evidence": evidence,
    }


def get_skill_history(conn: sqlite3.Connection, skill_id: str, hours: int) -> dict | None:
    """Per-cycle probe summaries over the last ``hours``, or None if the id
    is unknown.
    """
    exists = conn.execute("SELECT 1 FROM scores WHERE skill_id = ?", (skill_id,)).fetchone()
    if exists is None:
        return None

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=hours)).isoformat(timespec="seconds")

    rows = conn.execute(
        "SELECT ts, ok, latency_ms FROM probes WHERE skill_id = ? AND ts >= ? ORDER BY ts",
        (skill_id, cutoff),
    ).fetchall()

    cycles: dict[str, dict] = {}
    for row in rows:
        cycle = cycles.setdefault(
            row["ts"], {"ts": row["ts"], "n_probes": 0, "ok_probes": 0, "latencies": []}
        )
        cycle["n_probes"] += 1
        if row["ok"]:
            cycle["ok_probes"] += 1
            if row["latency_ms"] is not None:
                cycle["latencies"].append(row["latency_ms"])

    cycle_list = [
        {
            "ts": cycle["ts"],
            "alive": cycle["ok_probes"] > 0,
            "n_probes": cycle["n_probes"],
            "ok_probes": cycle["ok_probes"],
            "p50_latency_ms": (
                int(median_latency(cycle["latencies"]))
                if median_latency(cycle["latencies"]) is not None
                else None
            ),
        }
        for cycle in sorted(cycles.values(), key=lambda c: c["ts"])
    ]

    return {"id": skill_id, "hours": hours, "cycles": cycle_list}


def _match_reason(need_tokens: list[str], row: sqlite3.Row) -> str | None:
    tags = normalize_tags(row["tags"])
    name = (row["name"] or "").lower()
    description = (row["description"] or "").lower()

    for token in need_tokens:
        if token in tags:
            return f"tag match: {token}"
    for token in need_tokens:
        if token in name:
            return f"name match: {token}"
    for token in need_tokens:
        if token in description:
            return f"description match: {token}"
    return None


def recommend(conn: sqlite3.Connection, need: str, min_uptime: float, limit: int) -> dict:
    """Best live skills for a stated need. Always 200, never empty: falls
    back to the most reliable active skills, overall, if nothing matches.
    """
    need_tokens = [t for t in _NEED_TOKEN_RE.split(need.strip().lower()) if t]

    rows = conn.execute(
        """
        SELECT sk.id, sk.name, sk.description, sk.tags, sk.source_type, sk.source_url,
               sk.endpoints_raw, sc.score, sc.alive_now, sc.uptime_24h, sc.p50_latency_ms
        FROM scores sc JOIN skills sk ON sk.id = sc.skill_id
        """
    ).fetchall()

    candidates: list[tuple[sqlite3.Row, str | None]] = [
        (row, reason)
        for row in rows
        if (reason := _match_reason(need_tokens, row)) is not None and row["uptime_24h"] >= min_uptime
    ]

    note = None
    if not candidates:
        pool = [row for row in rows if row["uptime_24h"] >= min_uptime] or list(rows)
        candidates = [(row, None) for row in pool]
        note = f"no direct match for '{need}'; returning most reliable live skills"

    candidates.sort(key=lambda pair: (pair[0]["alive_now"], pair[0]["score"]), reverse=True)

    matches_out = []
    for row, reason in candidates[:limit]:
        parsed = parse_endpoints(row["endpoints_raw"])
        endpoints = [f"{ep.method} {ep.url}" for ep in parsed.endpoints]
        skill_md = row["source_url"] if row["source_type"] in ("url", "github") else None

        why_parts = [reason or "most reliable live skill", f"uptime_24h {row['uptime_24h']:.2f}"]
        if row["p50_latency_ms"] is not None:
            why_parts.append(f"p50 {row['p50_latency_ms']}ms")

        matches_out.append(
            {
                "id": row["id"],
                "name": row["name"],
                "score": round(row["score"], 1),
                "alive_now": bool(row["alive_now"]),
                "uptime_24h": round(row["uptime_24h"], 2),
                "why": "; ".join(why_parts),
                "endpoints": endpoints,
                "skill_md": skill_md,
            }
        )

    return {"need": need, "matches": matches_out, "note": note}


def _top_by_score(conn: sqlite3.Connection, order: str, limit: int) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT sk.id, sk.name, sc.score FROM scores sc
        JOIN skills sk ON sk.id = sc.skill_id
        ORDER BY sc.score {order} LIMIT ?
        """,  # noqa: S608 -- `order` is one of two internal literals, never user input
        (limit,),
    ).fetchall()
    return [{"id": r["id"], "name": r["name"], "score": round(r["score"], 1)} for r in rows]


def build_report(conn: sqlite3.Connection) -> dict:
    """Registry-wide health summary, including the registry's own
    self-reported reachability (before) alongside our measured alive_now
    (after), and this cycle's probe-run aggregates.
    """
    skills_tracked = conn.execute("SELECT COUNT(*) AS n FROM scores").fetchone()["n"]
    alive_now = conn.execute("SELECT COUNT(*) AS n FROM scores WHERE alive_now = 1").fetchone()["n"]
    ever_dead = conn.execute(
        "SELECT COUNT(*) AS n FROM scores WHERE uptime_all < 1.0"
    ).fetchone()["n"]

    alive_now_pct = round(100.0 * alive_now / skills_tracked, 1) if skills_tracked else 0.0
    ever_dead_pct = round(100.0 * ever_dead / skills_tracked, 1) if skills_tracked else 0.0

    latencies = [
        row["p50_latency_ms"]
        for row in conn.execute(
            "SELECT p50_latency_ms FROM scores WHERE p50_latency_ms IS NOT NULL"
        ).fetchall()
    ]
    median = median_latency(latencies)
    median_latency_ms = int(median) if median is not None else None

    reachable_counts = {"true": 0, "false": 0, "null": 0}
    for row in conn.execute(
        "SELECT reachable_raw FROM skills WHERE superseded_by IS NULL"
    ).fetchall():
        if row["reachable_raw"] is None:
            reachable_counts["null"] += 1
        elif row["reachable_raw"]:
            reachable_counts["true"] += 1
        else:
            reachable_counts["false"] += 1

    total_records = conn.execute("SELECT COUNT(*) AS n FROM skills").fetchone()["n"]
    superseded = total_records - skills_tracked

    latest_ts = conn.execute("SELECT MAX(ts) AS ts FROM probes").fetchone()["ts"]
    targets_probed = 0
    ok_probes = 0
    if latest_ts is not None:
        cycle_row = conn.execute(
            "SELECT COUNT(*) AS n, SUM(ok) AS ok FROM probes WHERE ts = ?", (latest_ts,)
        ).fetchone()
        targets_probed = cycle_row["n"]
        ok_probes = cycle_row["ok"] or 0

    return {
        "skills_tracked": skills_tracked,
        "alive_now": alive_now,
        "alive_now_pct": alive_now_pct,
        "ever_dead_pct": ever_dead_pct,
        "median_latency_ms": median_latency_ms,
        "top": _top_by_score(conn, "DESC", 10),
        "worst": _top_by_score(conn, "ASC", 10),
        "registry_self_reported": reachable_counts,
        "probe_run": {
            "records_ingested": total_records,
            "active_after_dedup": skills_tracked,
            "superseded": superseded,
            "cycle_ts": latest_ts,
            "targets_probed": targets_probed,
            "ok_probes": ok_probes,
        },
    }
