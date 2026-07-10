"""Cycle orchestration: fetch registry -> ingest+dedup -> probe -> score.

One ``run_cycle()`` call is one full prober cycle (spec §2 diagram),
scheduled every 15 minutes.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from app.dedup import compute_superseded
from app.parsing import distinct_probe_hosts, is_absolute_http_url, parse_endpoints
from app.prober import ProbeResult, ProbeTarget, run_probe_cycle
from app.registry_client import fetch_registry
from app.scoring import compute_score, median_latency


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cutoff_24h(now_iso: str) -> str:
    now_dt = datetime.fromisoformat(now_iso)
    return (now_dt - timedelta(hours=24)).isoformat(timespec="seconds")


def _reachable_to_int(value: object) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def ingest_records(conn: sqlite3.Connection, records: list[dict], now: str) -> None:
    """Upsert registry records into ``skills`` and recompute ``superseded_by``
    across ALL skills currently known (not just this fetch) -- a duplicate
    can arrive in a later cycle than its earlier sibling.
    """
    for record in records:
        conn.execute(
            """
            INSERT INTO skills (
                id, name, description, tags, source_type, source_url,
                content, endpoints_raw, reachable_raw, created_at,
                superseded_by, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                tags=excluded.tags,
                source_type=excluded.source_type,
                source_url=excluded.source_url,
                content=excluded.content,
                endpoints_raw=excluded.endpoints_raw,
                reachable_raw=excluded.reachable_raw,
                created_at=excluded.created_at,
                last_seen=excluded.last_seen
            """,
            (
                record["id"],
                record.get("name") or "",
                record.get("description"),
                record.get("tags"),
                record["source_type"],
                record.get("source_url"),
                record.get("content"),
                record.get("endpoints"),
                _reachable_to_int(record.get("reachable")),
                record.get("created_at"),
                now,
                now,
            ),
        )
    conn.commit()

    all_rows = conn.execute("SELECT id, name, created_at FROM skills").fetchall()
    mapping = compute_superseded([dict(row) for row in all_rows])
    conn.executemany(
        "UPDATE skills SET superseded_by = ? WHERE id = ?",
        [(active_id, skill_id) for skill_id, active_id in mapping.items()],
    )
    conn.commit()


def build_probe_targets(conn: sqlite3.Connection) -> list[ProbeTarget]:
    """Build this cycle's probe targets from active (non-superseded) skills."""
    rows = conn.execute(
        "SELECT id, source_type, source_url, endpoints_raw"
        " FROM skills WHERE superseded_by IS NULL"
    ).fetchall()

    targets: list[ProbeTarget] = []
    for row in rows:
        skill_id = row["id"]

        source_url = row["source_url"]
        if (
            row["source_type"] in ("url", "github")
            and source_url
            and is_absolute_http_url(source_url)
        ):
            targets.append(ProbeTarget(skill_id=skill_id, target=source_url, kind="docs"))

        parsed = parse_endpoints(row["endpoints_raw"])
        for host in distinct_probe_hosts(parsed.endpoints):
            targets.append(ProbeTarget(skill_id=skill_id, target=f"{host}/", kind="host"))
        for endpoint in parsed.endpoints:
            if (
                endpoint.method == "GET"
                and not endpoint.has_placeholder
                and is_absolute_http_url(endpoint.url)
            ):
                targets.append(ProbeTarget(skill_id=skill_id, target=endpoint.url, kind="endpoint"))

    return targets


def insert_probes(conn: sqlite3.Connection, results: list[ProbeResult]) -> None:
    conn.executemany(
        """
        INSERT INTO probes (skill_id, target, kind, ts, ok, status_code, latency_ms, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (r.skill_id, r.target, r.kind, r.ts, int(r.ok), r.status_code, r.latency_ms, r.error)
            for r in results
        ],
    )
    conn.commit()


def _compute_skill_score(conn: sqlite3.Connection, skill: sqlite3.Row, now: str) -> dict:
    skill_id = skill["id"]
    probe_rows = conn.execute(
        "SELECT ts, ok, latency_ms FROM probes WHERE skill_id = ?", (skill_id,)
    ).fetchall()

    n_probes = len(probe_rows)

    # A "cycle" is identified by the shared ts stamped across all probes
    # issued in one run_cycle() call; it counts as successful if any probe
    # in it succeeded.
    cycles: dict[str, bool] = {}
    for row in probe_rows:
        cycles[row["ts"]] = cycles.get(row["ts"], False) or bool(row["ok"])

    uptime_all = (sum(cycles.values()) / len(cycles)) if cycles else 0.0

    cutoff = _cutoff_24h(now)
    cycles_24h = {ts: ok for ts, ok in cycles.items() if ts >= cutoff}
    uptime_24h = (sum(cycles_24h.values()) / len(cycles_24h)) if cycles_24h else 0.0

    alive_now = bool(cycles.get(now, False))

    ok_latencies = [
        row["latency_ms"] for row in probe_rows if row["ok"] and row["latency_ms"] is not None
    ]
    p50 = median_latency(ok_latencies)

    parsed = parse_endpoints(skill["endpoints_raw"])
    if skill["source_type"] == "content":
        docs_ok = bool(skill["content"]) and parsed.n_parsed >= 1
    else:
        latest_docs = conn.execute(
            "SELECT ok FROM probes WHERE skill_id = ? AND kind = 'docs' ORDER BY ts DESC LIMIT 1",
            (skill_id,),
        ).fetchone()
        docs_ok = bool(latest_docs and latest_docs["ok"]) and parsed.n_parsed >= 1

    score = compute_score(
        alive_now=alive_now, uptime_24h=uptime_24h, docs_ok=docs_ok, p50_latency_ms=p50
    )

    return {
        "skill_id": skill_id,
        "alive_now": int(alive_now),
        "uptime_24h": uptime_24h,
        "uptime_all": uptime_all,
        "p50_latency_ms": int(p50) if p50 is not None else None,
        "docs_ok": int(docs_ok),
        "n_probes": n_probes,
        "score": score,
        "updated_at": now,
    }


def recompute_scores(conn: sqlite3.Connection, now: str) -> None:
    """Recompute ``scores`` from scratch for all active skills.

    Wholesale recompute (delete + reinsert) avoids stale rows for skills
    that just became superseded; at this dataset's scale (~100s of rows)
    that's cheap enough to do unconditionally every cycle.
    """
    active_skills = conn.execute(
        "SELECT id, source_type, endpoints_raw, content FROM skills WHERE superseded_by IS NULL"
    ).fetchall()

    rows = [_compute_skill_score(conn, skill, now) for skill in active_skills]

    conn.execute("DELETE FROM scores")
    conn.executemany(
        """
        INSERT INTO scores (
            skill_id, alive_now, uptime_24h, uptime_all, p50_latency_ms,
            docs_ok, n_probes, score, updated_at
        ) VALUES (:skill_id, :alive_now, :uptime_24h, :uptime_all, :p50_latency_ms,
                  :docs_ok, :n_probes, :score, :updated_at)
        """,
        rows,
    )
    conn.commit()


async def run_cycle(conn: sqlite3.Connection, db_path: str) -> dict:
    """Run one full prober cycle: fetch, ingest+dedup, probe, score."""
    now = _now_iso()
    records = await fetch_registry(db_path)
    ingest_records(conn, records, now)

    targets = build_probe_targets(conn)
    results = await run_probe_cycle(targets, now)
    insert_probes(conn, results)

    recompute_scores(conn, now)

    return {
        "ts": now,
        "registry_records": len(records),
        "targets_probed": len(targets),
        "ok_probes": sum(1 for r in results if r.ok),
    }
