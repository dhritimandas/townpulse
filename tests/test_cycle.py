import sqlite3

import httpx
import pytest
import respx

from app.config import REGISTRY_URL
from app.cycle import build_probe_targets, ingest_records, run_cycle
from app.db import init_db

FAKE_REGISTRY = {
    "count": 2,
    "skills": [
        {
            "id": "id-1",
            "name": "AliveSkill",
            "description": "test",
            "source_type": "url",
            "source_url": "https://alive.example/skill.md",
            "content": None,
            "endpoints": "GET https://alive.example/do\r\nPOST https://alive.example/write",
            "tags": "demo, test",
            "reachable": True,
            "created_at": "2026-07-10T01:00:00.000Z",
        },
        {
            "id": "id-2",
            "name": "DeadSkill",
            "description": "test",
            "source_type": "url",
            "source_url": "https://dead.example/skill.md",
            "content": None,
            "endpoints": "GET https://dead.example/do",
            "tags": None,
            "reachable": False,
            "created_at": "2026-07-10T01:00:00.000Z",
        },
    ],
}


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    yield connection
    connection.close()


@respx.mock
async def test_run_cycle_populates_all_tables(conn, tmp_path, monkeypatch):
    import app.prober as prober_module

    monkeypatch.setattr(prober_module, "PROBE_HOST_SPACING_SECONDS", 0.01)
    respx.get(REGISTRY_URL).mock(return_value=httpx.Response(200, json=FAKE_REGISTRY))
    respx.get("https://alive.example/skill.md").mock(return_value=httpx.Response(200))
    respx.get("https://alive.example/").mock(return_value=httpx.Response(200))
    respx.get("https://alive.example/do").mock(return_value=httpx.Response(200))
    respx.get("https://dead.example/skill.md").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://dead.example/").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://dead.example/do").mock(side_effect=httpx.ConnectError("down"))

    db_path = str(tmp_path / "test.db")
    summary = await run_cycle(conn, db_path)

    assert summary["registry_records"] == 2
    assert summary["targets_probed"] == 6  # 3 targets each: docs, host, one GET endpoint

    skills = conn.execute("SELECT id FROM skills").fetchall()
    assert {row["id"] for row in skills} == {"id-1", "id-2"}

    probes = conn.execute("SELECT skill_id, kind, ok FROM probes").fetchall()
    assert len(probes) == 6

    # the POST endpoint must never be probed
    probed_targets = {row["skill_id"] for row in probes}
    assert probed_targets == {"id-1", "id-2"}

    alive_score = conn.execute(
        "SELECT alive_now, score FROM scores WHERE skill_id = 'id-1'"
    ).fetchone()
    assert alive_score["alive_now"] == 1
    assert alive_score["score"] > 50

    dead_score = conn.execute(
        "SELECT alive_now, score FROM scores WHERE skill_id = 'id-2'"
    ).fetchone()
    assert dead_score["alive_now"] == 0
    assert dead_score["score"] < 20


@respx.mock
async def test_run_cycle_excludes_superseded_skills_from_scores(conn, tmp_path, monkeypatch):
    import app.prober as prober_module

    monkeypatch.setattr(prober_module, "PROBE_HOST_SPACING_SECONDS", 0.01)
    registry_with_duplicate = {
        "count": 3,
        "skills": [
            *FAKE_REGISTRY["skills"],
            {
                "id": "id-1-dup",
                "name": "aliveskill",
                "description": "resubmitted",
                "source_type": "url",
                "source_url": "https://alive.example/skill.md",
                "content": None,
                "endpoints": "GET https://alive.example/do",
                "tags": None,
                "reachable": True,
                "created_at": "2026-07-10T02:00:00.000Z",
            },
        ],
    }
    respx.get(REGISTRY_URL).mock(return_value=httpx.Response(200, json=registry_with_duplicate))
    respx.get("https://alive.example/skill.md").mock(return_value=httpx.Response(200))
    respx.get("https://alive.example/").mock(return_value=httpx.Response(200))
    respx.get("https://alive.example/do").mock(return_value=httpx.Response(200))
    respx.get("https://dead.example/skill.md").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://dead.example/").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://dead.example/do").mock(side_effect=httpx.ConnectError("down"))

    db_path = str(tmp_path / "test.db")
    await run_cycle(conn, db_path)

    superseded = conn.execute(
        "SELECT superseded_by FROM skills WHERE id = 'id-1'"
    ).fetchone()["superseded_by"]
    assert superseded == "id-1-dup"

    active = conn.execute(
        "SELECT superseded_by FROM skills WHERE id = 'id-1-dup'"
    ).fetchone()["superseded_by"]
    assert active is None

    score_ids = {row["skill_id"] for row in conn.execute("SELECT skill_id FROM scores").fetchall()}
    assert "id-1" not in score_ids
    assert "id-1-dup" in score_ids

    # the superseded skill must never be probed
    probed_ids = {row["skill_id"] for row in conn.execute("SELECT DISTINCT skill_id FROM probes").fetchall()}
    assert "id-1" not in probed_ids


def test_build_probe_targets_skips_relative_path_endpoints(conn):
    # Observed in the live registry: a skill can declare a relative-path
    # endpoint (e.g. "GET /leaderboard") with no host of its own. Such a
    # target is not directly probeable (httpx has nothing to connect to)
    # and must never reach the probe pool.
    ingest_records(
        conn,
        [
            {
                "id": "id-rel",
                "name": "RelativePathSkill",
                "description": "test",
                "source_type": "url",
                "source_url": "https://a.example/skill.md",
                "content": None,
                "endpoints": "GET /leaderboard\r\nGET https://a.example/two",
                "tags": None,
                "reachable": None,
                "created_at": "2026-07-10T01:00:00.000Z",
            }
        ],
        now="2026-07-10T02:00:00+00:00",
    )

    targets = build_probe_targets(conn)
    probed_urls = {t.target for t in targets}
    assert "/leaderboard" not in probed_urls
    assert "https://a.example/two" in probed_urls
