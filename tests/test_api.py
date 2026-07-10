"""HTTP-layer tests via FastAPI's TestClient.

Deliberately instantiated WITHOUT `with TestClient(app) as client:` --
entering the context manager would run the app's lifespan, which starts the
real APScheduler and immediately fires a live registry fetch. Plain
instantiation skips lifespan entirely, so these tests stay fast and offline;
each fixture creates the schema itself instead of relying on startup to do it.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.cycle import ingest_records, recompute_scores
from app.db import get_connection, init_db

NOW = "2026-07-10T12:00:00+00:00"
SKILL_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "api_test.db")
    monkeypatch.setattr(main_module, "DATABASE_PATH", db_path)

    conn = get_connection(db_path)
    init_db(conn)
    ingest_records(
        conn,
        [
            {
                "id": SKILL_ID,
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
            }
        ],
        NOW,
    )
    conn.executemany(
        "INSERT INTO probes (skill_id, target, kind, ts, ok, status_code, latency_ms, error)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (SKILL_ID, "https://trustledger.example/skill.md", "docs", NOW, 1, 200, 300, None),
            (SKILL_ID, "https://trustledger.example/", "host", NOW, 1, 200, 320, None),
            (SKILL_ID, "https://trustledger.example/status", "endpoint", NOW, 1, 200, 310, None),
        ],
    )
    conn.commit()
    recompute_scores(conn, NOW)
    conn.close()

    return TestClient(main_module.app)


def test_skills_response_shape(client):
    resp = client.get("/skills")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    skill = body["skills"][0]
    assert set(skill.keys()) == {
        "id", "name", "score", "alive_now", "uptime_24h", "p50_latency_ms", "tags",
    }
    assert skill["id"] == SKILL_ID


def test_recommend_response_shape(client):
    resp = client.get("/recommend", params={"need": "escrow"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"need", "matches", "note"}
    assert body["note"] is None
    match = body["matches"][0]
    assert set(match.keys()) == {
        "id", "name", "score", "alive_now", "uptime_24h", "why", "endpoints", "skill_md",
    }


def test_recommend_never_dead_ends_on_nonsense_need(client):
    resp = client.get("/recommend", params={"need": "zzzz-nonsense-need"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["matches"]) > 0
    assert body["note"] is not None


def test_skill_detail_unknown_id_returns_404_with_hint(client):
    resp = client.get("/skills/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json() == {"error": "unknown skill id", "hint": "GET /skills for ids"}


def test_skill_history_unknown_id_returns_404_with_hint(client):
    resp = client.get("/skills/00000000-0000-0000-0000-000000000000/history")
    assert resp.status_code == 404
    assert resp.json() == {"error": "unknown skill id", "hint": "GET /skills for ids"}


def test_skill_detail_known_id(client):
    resp = client.get(f"/skills/{SKILL_ID}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "TrustLedger"


def test_report_response_shape(client):
    resp = client.get("/report")
    assert resp.status_code == 200
    body = resp.json()
    assert "registry_self_reported" in body
    assert "probe_run" in body
    assert body["probe_run"]["records_ingested"] == 1


def test_recommend_missing_need_returns_400_with_hint(client):
    # FastAPI query validation rejects this before the handler runs, so it
    # never touches the DB.
    resp = client.get("/recommend")
    assert resp.status_code == 400
    assert "hint" in resp.json()


def test_about_and_health(client):
    about_resp = client.get("/about")
    assert about_resp.status_code == 200
    assert "score_formula" in about_resp.json()

    health_resp = client.get("/health")
    assert health_resp.status_code == 200


def test_skill_md_404_when_not_yet_published(client):
    resp = client.get("/skill.md")
    assert resp.status_code == 404
    assert resp.json() == {
        "error": "SKILL.md not found",
        "hint": "SKILL.md has not been published yet",
    }


def test_skill_md_serves_file_content_when_present(client, tmp_path, monkeypatch):
    skill_md_path = tmp_path / "SKILL.md"
    skill_md_path.write_text("# Town Pulse\n\nBase URL: https://example\n")
    monkeypatch.setattr(main_module, "_SKILL_MD_PATH", skill_md_path)

    resp = client.get("/skill.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "Town Pulse" in resp.text
