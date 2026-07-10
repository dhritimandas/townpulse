from app.db import get_connection, init_db


def test_get_connection_creates_missing_parent_directories(tmp_path):
    db_path = tmp_path / "nested" / "does" / "not" / "exist" / "pulse.db"
    assert not db_path.parent.exists()

    conn = get_connection(db_path)
    try:
        init_db(conn)
        assert db_path.parent.is_dir()
        assert db_path.exists()
    finally:
        conn.close()
