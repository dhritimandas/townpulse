import sqlite3

import pytest

from app.cycle import ingest_records, recompute_scores
from app.db import init_db
from app.queries import build_report, get_skill, get_skill_history, list_skills, recommend

NOW = "2026-07-10T12:00:00+00:00"

RECORDS = [
    {
        "id": "id-escrow",
        "name": "TrustLedger",
        "description": "Escrow and settlement for agent marketplaces",
        "source_type": "url",
        "source_url": "https://trustledger.example/skill.md",
        "content": None,
        "endpoints": (
            "POST https://trustledger.example/escrow\r\n"
            "GET https://trustledger.example/status"
        ),
        "tags": "escrow, reputation",
        "reachable": True,
        "created_at": "2026-07-10T01:00:00.000Z",
    },
    {
        "id": "id-weather",
        "name": "WeatherNow",
        "description": "Live weather data feed",
        "source_type": "url",
        "source_url": "https://weathernow.example/skill.md",
        "content": None,
        "endpoints": "GET https://weathernow.example/forecast",
        "tags": "weather",
        "reachable": False,
        "created_at": "2026-07-10T01:00:00.000Z",
    },
]

PROBES = [
    ("id-escrow", "https://trustledger.example/skill.md", "docs", NOW, 1, 200, 300, None),
    ("id-escrow", "https://trustledger.example/", "host", NOW, 1, 200, 320, None),
    ("id-escrow", "https://trustledger.example/status", "endpoint", NOW, 1, 200, 310, None),
    ("id-weather", "https://weathernow.example/skill.md", "docs", NOW, 0, None, None, "boom"),
    ("id-weather", "https://weathernow.example/", "host", NOW, 0, None, None, "boom"),
    ("id-weather", "https://weathernow.example/forecast", "endpoint", NOW, 0, None, None, "boom"),
]


@pytest.fixture
def seeded_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    ingest_records(conn, RECORDS, NOW)
    conn.executemany(
        "INSERT INTO probes (skill_id, target, kind, ts, ok, status_code, latency_ms, error)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        PROBES,
    )
    conn.commit()
    recompute_scores(conn, NOW)

    yield conn
    conn.close()


def test_list_skills_sorted_by_score_desc(seeded_conn):
    rows = list_skills(seeded_conn)
    assert [r["id"] for r in rows] == ["id-escrow", "id-weather"]
    assert rows[0]["tags"] == ["escrow", "reputation"]
    assert rows[0]["alive_now"] is True
    assert rows[1]["alive_now"] is False


def test_get_skill_returns_latest_evidence(seeded_conn):
    skill = get_skill(seeded_conn, "id-escrow")
    assert skill["name"] == "TrustLedger"
    assert skill["docs_ok"] is True
    assert len(skill["latest_evidence"]) == 3


def test_get_skill_unknown_id_returns_none(seeded_conn):
    assert get_skill(seeded_conn, "does-not-exist") is None


def test_get_skill_history_returns_cycles(seeded_conn):
    history = get_skill_history(seeded_conn, "id-escrow", hours=24)
    assert history["id"] == "id-escrow"
    assert len(history["cycles"]) == 1
    assert history["cycles"][0]["alive"] is True
    assert history["cycles"][0]["n_probes"] == 3


def test_get_skill_history_unknown_id_returns_none(seeded_conn):
    assert get_skill_history(seeded_conn, "does-not-exist", hours=24) is None


def test_recommend_tag_match(seeded_conn):
    result = recommend(seeded_conn, "escrow", min_uptime=0.0, limit=3)
    assert result["note"] is None
    assert result["matches"][0]["id"] == "id-escrow"
    assert "tag match" in result["matches"][0]["why"]
    assert "POST https://trustledger.example/escrow" in result["matches"][0]["endpoints"]


def test_recommend_never_dead_ends_on_nonsense_need(seeded_conn):
    result = recommend(seeded_conn, "zzzz-nonsense-need", min_uptime=0.0, limit=3)
    assert result["note"] is not None
    assert len(result["matches"]) > 0
    assert result["matches"][0]["id"] == "id-escrow"  # ranked by (alive_now, score)


def test_recommend_min_uptime_filters_then_falls_back(seeded_conn):
    # WeatherNow tag-matches "weather" but its uptime is 0 -- filtered out,
    # must still fall back rather than dead-end.
    result = recommend(seeded_conn, "weather", min_uptime=0.5, limit=3)
    assert result["note"] is not None
    assert len(result["matches"]) > 0


def test_build_report_shape(seeded_conn):
    report = build_report(seeded_conn)
    assert report["skills_tracked"] == 2
    assert report["alive_now"] == 1
    assert report["registry_self_reported"] == {"true": 1, "false": 1, "null": 0}
    assert report["probe_run"]["records_ingested"] == 2
    assert report["probe_run"]["active_after_dedup"] == 2
    assert report["probe_run"]["superseded"] == 0
    assert report["probe_run"]["targets_probed"] == 6
    assert report["probe_run"]["ok_probes"] == 3
